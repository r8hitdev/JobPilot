"""
JobPilot LLM client — scoring, form-answering, token accounting, fallback chain.
Uses the official openai SDK pointed at any OpenAI-compatible endpoint.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from loguru import logger
from openai import AsyncOpenAI, APIError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from jobpilot.settings import load_env


@dataclass
class TokenUsage:
    """Accumulates prompt and completion token counts."""
    prompt_tokens: int = 0
    completion_tokens: int = 0

    def add(self, prompt: int, completion: int) -> None:
        self.prompt_tokens += prompt
        self.completion_tokens += completion

    @property
    def total(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def to_dict(self) -> dict[str, int]:
        return {"tokens_in": self.prompt_tokens, "tokens_out": self.completion_tokens}


# Global per-run token accumulator
_run_tokens = TokenUsage()


def get_run_tokens() -> TokenUsage:
    return _run_tokens


def reset_run_tokens() -> None:
    global _run_tokens
    _run_tokens = TokenUsage()


def _strip_think_tags(text: str) -> str:
    """Remove <think>...</think> blocks from reasoning model output."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def _build_client(base_url: str | None = None, api_key: str | None = None) -> AsyncOpenAI:
    env = load_env()
    return AsyncOpenAI(
        base_url=base_url or env.llm_base_url,
        api_key=api_key or env.llm_api_key,
    )


def parse_llm_json(text: str) -> dict[str, Any]:
    """
    Extract JSON from LLM output. Handles:
    - Clean JSON
    - JSON inside ```json code fences
    - JSON embedded in prose
    Falls back to a default dict on failure.
    """
    text = _strip_think_tags(text)

    # Try direct parse
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        pass

    # Try extracting from code fence
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    # Try finding any JSON object
    m = re.search(r"\{[^{}]*\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass

    logger.warning(f"Failed to parse JSON from LLM output: {text[:200]}")
    return {"score": 0, "reason": "LLM output unparseable", "answer": ""}


async def list_models(base_url: str | None = None, api_key: str | None = None) -> list[dict[str, str]]:
    """Fetch available models from the endpoint. Returns list of {id, name}."""
    client = _build_client(base_url, api_key)
    try:
        resp = await client.models.list()
        models = []
        for m in resp.data:
            models.append({"id": m.id, "name": getattr(m, "name", m.id)})
        return sorted(models, key=lambda x: x["id"])
    except Exception as e:
        logger.error(f"Failed to list models: {e}")
        return []


async def test_connection(base_url: str | None = None, api_key: str | None = None, model: str | None = None) -> dict[str, Any]:
    """
    Send a minimal ping to test the LLM connection.
    Returns {"ok": bool, "latency_ms": float, "error": str}.
    """
    import time
    env = load_env()
    client = _build_client(base_url, api_key)
    mdl = model or env.llm_model
    start = time.monotonic()
    try:
        resp = await client.chat.completions.create(
            model=mdl,
            messages=[{"role": "user", "content": "Hi"}],
            max_tokens=5,
            temperature=0,
        )
        latency = (time.monotonic() - start) * 1000
        return {"ok": True, "latency_ms": round(latency, 1), "error": ""}
    except Exception as e:
        latency = (time.monotonic() - start) * 1000
        return {"ok": False, "latency_ms": round(latency, 1), "error": str(e)}


@retry(
    retry=retry_if_exception_type((APIError, ConnectionError, TimeoutError)),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    stop=stop_after_attempt(3),
    reraise=True,
)
async def _chat(
    messages: list[dict[str, str]],
    max_tokens: int = 80,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
) -> str:
    """Low-level chat completion with retries and token accounting."""
    env = load_env()
    client = _build_client(base_url, api_key)
    mdl = model or env.llm_model

    resp = await client.chat.completions.create(
        model=mdl,
        messages=messages,
        max_tokens=max_tokens,
        temperature=0,
    )
    text = resp.choices[0].message.content or ""
    usage = resp.usage
    if usage:
        _run_tokens.add(usage.prompt_tokens, usage.completion_tokens)
    return _strip_think_tags(text)


async def _chat_with_fallback(
    messages: list[dict[str, str]],
    max_tokens: int = 80,
) -> str | None:
    """Try primary model, then fallback, then return None for rule-only mode."""
    env = load_env()
    try:
        return await _chat(messages, max_tokens=max_tokens)
    except Exception as e:
        logger.warning(f"Primary model failed: {e}")
        if env.llm_fallback_model:
            try:
                return await _chat(messages, max_tokens=max_tokens, model=env.llm_fallback_model)
            except Exception as e2:
                logger.warning(f"Fallback model failed: {e2}")
        return None


def _build_no_think_system() -> str:
    return "You are a concise job-matching assistant. Output only valid JSON. /no_think"


async def score_job(
    title: str,
    company: str,
    description: str,
    candidate_summary: str,
    search_titles: list[str],
) -> dict[str, Any]:
    """
    Score a job listing for relevance. Returns {"score": int 0-100, "reason": str}.
    If the LLM is unavailable, returns a rule-based score.
    """
    desc_truncated = description[:1200]
    candidate_truncated = candidate_summary[:600]

    messages = [
        {"role": "system", "content": _build_no_think_system()},
        {"role": "user", "content": (
            f"Rate this job for the candidate (0-100). Consider title match, skill overlap, and seniority.\n\n"
            f"CANDIDATE LOOKING FOR: {', '.join(search_titles)}\n"
            f"CANDIDATE PROFILE: {candidate_truncated}\n\n"
            f"JOB: {title} at {company}\n"
            f"DESCRIPTION: {desc_truncated}\n\n"
            f"Reply with ONLY this JSON: {{\"score\": <int>, \"reason\": \"<one sentence>\"}}"
        )},
    ]
    raw = await _chat_with_fallback(messages, max_tokens=80)
    if raw is None:
        # Rule-only fallback: simple keyword matching
        return _rule_based_score(title, description, search_titles)
    parsed = parse_llm_json(raw)
    return {
        "score": max(0, min(100, int(parsed.get("score", 0)))),
        "reason": str(parsed.get("reason", "")),
    }


def _rule_based_score(title: str, description: str, search_titles: list[str]) -> dict[str, Any]:
    """Simple keyword-based scoring when the LLM is unavailable."""
    title_lower = title.lower()
    desc_lower = description.lower()
    score = 0
    for st in search_titles:
        st_lower = st.lower()
        if st_lower in title_lower:
            score += 40
        words = st_lower.split()
        for w in words:
            if w in desc_lower:
                score += 10
    score = min(score, 100)
    return {"score": score, "reason": "Rule-based score (LLM unavailable)"}


async def answer_question(question: str, profile_summary: str, answer_bank: dict[str, str]) -> str:
    """
    Answer an application form question. Checks the answer bank first, then uses the LLM.
    Returns the answer string.
    """
    # Check answer bank (fuzzy match on keys)
    q_lower = question.strip().lower()
    for key, val in answer_bank.items():
        if key.lower() in q_lower or q_lower in key.lower():
            return val

    messages = [
        {"role": "system", "content": _build_no_think_system()},
        {"role": "user", "content": (
            f"Answer this job application question based on the candidate profile.\n"
            f"Question: {question}\n"
            f"Profile: {profile_summary[:600]}\n\n"
            f"Reply with ONLY this JSON: {{\"answer\": \"<concise answer>\"}}"
        )},
    ]
    raw = await _chat_with_fallback(messages, max_tokens=150)
    if raw is None:
        return ""
    parsed = parse_llm_json(raw)
    return str(parsed.get("answer", ""))


async def generate_cover_note(
    job_title: str,
    company: str,
    description: str,
    profile_summary: str,
) -> str:
    """Generate a brief cover note for Internshala applications."""
    messages = [
        {"role": "system", "content": _build_no_think_system()},
        {"role": "user", "content": (
            f"Write a 2-3 sentence cover note for applying to: {job_title} at {company}.\n"
            f"Job: {description[:600]}\n"
            f"Profile: {profile_summary[:600]}\n\n"
            f"Reply with ONLY this JSON: {{\"cover_note\": \"<text>\"}}"
        )},
    ]
    raw = await _chat_with_fallback(messages, max_tokens=120)
    if raw is None:
        return f"I am excited to apply for the {job_title} position at {company}. My skills and experience align well with the role requirements."
    parsed = parse_llm_json(raw)
    return str(parsed.get("cover_note", ""))
