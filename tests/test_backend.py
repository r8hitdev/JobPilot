"""
Unit tests for JobPilot backend.
Tests: cookie parsing, filters, caps/dedupe, LLM JSON parsing (LLM mocked).
"""

from __future__ import annotations

import json
import asyncio
import pytest

# ═══════════════════════════════════════════════════════════════
# Cookie Parsing Tests
# ═══════════════════════════════════════════════════════════════

class TestCookieParsing:
    """Test Cookie-Editor JSON and Netscape cookies.txt parsing."""

    def test_parse_cookie_editor_json_basic(self):
        from jobpilot.cookies import parse_cookie_editor_json

        raw = json.dumps([
            {
                "name": "li_at",
                "value": "AQEDARtest123",
                "domain": ".linkedin.com",
                "path": "/",
                "expirationDate": 1735689600,
                "httpOnly": True,
                "secure": True,
                "sameSite": "None",
            },
            {
                "name": "JSESSIONID",
                "value": "ajax:1234567890",
                "domain": "www.linkedin.com",
                "path": "/",
                "expirationDate": 1735689600,
                "httpOnly": False,
                "secure": True,
                "sameSite": "Lax",
            },
        ])

        cookies = parse_cookie_editor_json(raw)
        assert len(cookies) == 2
        assert cookies[0]["name"] == "li_at"
        assert cookies[0]["value"] == "AQEDARtest123"
        assert cookies[0]["domain"] == ".linkedin.com"
        assert cookies[0]["httpOnly"] is True
        assert cookies[0]["secure"] is True
        assert cookies[0]["sameSite"] == "None"
        assert cookies[0]["expires"] == 1735689600

    def test_parse_cookie_editor_json_normalizes_domain(self):
        from jobpilot.cookies import parse_cookie_editor_json

        raw = json.dumps([
            {"name": "test", "value": "val", "domain": "linkedin.com", "path": "/"},
        ])
        cookies = parse_cookie_editor_json(raw)
        assert cookies[0]["domain"] == ".linkedin.com"

    def test_parse_cookie_editor_json_normalizes_same_site(self):
        from jobpilot.cookies import parse_cookie_editor_json

        raw = json.dumps([
            {"name": "a", "value": "1", "domain": ".x.com", "path": "/", "sameSite": "strict"},
            {"name": "b", "value": "2", "domain": ".x.com", "path": "/", "sameSite": "NONE"},
            {"name": "c", "value": "3", "domain": ".x.com", "path": "/", "sameSite": "invalid"},
            {"name": "d", "value": "4", "domain": ".x.com", "path": "/"},
        ])
        cookies = parse_cookie_editor_json(raw)
        assert cookies[0]["sameSite"] == "Strict"
        assert cookies[1]["sameSite"] == "None"
        assert cookies[2]["sameSite"] == "Lax"  # fallback
        assert cookies[3]["sameSite"] == "Lax"  # default

    def test_parse_cookie_editor_json_skips_empty_entries(self):
        from jobpilot.cookies import parse_cookie_editor_json

        raw = json.dumps([
            {"name": "", "value": "v", "domain": ".x.com", "path": "/"},
            {"name": "n", "value": "", "domain": ".x.com", "path": "/"},
            {"name": "good", "value": "val", "domain": ".x.com", "path": "/"},
        ])
        cookies = parse_cookie_editor_json(raw)
        assert len(cookies) == 1
        assert cookies[0]["name"] == "good"

    def test_parse_cookie_editor_json_invalid_json(self):
        from jobpilot.cookies import parse_cookie_editor_json

        with pytest.raises(ValueError, match="Invalid JSON"):
            parse_cookie_editor_json("not json at all")

    def test_parse_cookie_editor_json_not_array(self):
        from jobpilot.cookies import parse_cookie_editor_json

        with pytest.raises(ValueError, match="Expected a JSON array"):
            parse_cookie_editor_json('{"name": "x"}')

    def test_parse_netscape_cookies_txt(self):
        from jobpilot.cookies import parse_netscape_cookies_txt

        raw = """# Netscape HTTP Cookie File
.linkedin.com\tTRUE\t/\tTRUE\t1735689600\tli_at\tAQEDARtest123
www.linkedin.com\tFALSE\t/\tTRUE\t1735689600\tJSESSIONID\tajax:123
# comment line
"""
        cookies = parse_netscape_cookies_txt(raw)
        assert len(cookies) == 2
        assert cookies[0]["name"] == "li_at"
        assert cookies[0]["value"] == "AQEDARtest123"
        assert cookies[0]["domain"] == ".linkedin.com"
        assert cookies[0]["secure"] is True
        assert cookies[0]["expires"] == 1735689600.0

        assert cookies[1]["name"] == "JSESSIONID"
        assert cookies[1]["domain"] == ".www.linkedin.com"

    def test_parse_netscape_cookies_txt_skips_bad_lines(self):
        from jobpilot.cookies import parse_netscape_cookies_txt

        raw = """# header
short\tline
.x.com\tTRUE\t/\tFALSE\t0\tgood\tvalue
"""
        cookies = parse_netscape_cookies_txt(raw)
        assert len(cookies) == 1
        assert cookies[0]["name"] == "good"

    def test_parse_cookies_auto_detect_json(self):
        from jobpilot.cookies import parse_cookies

        raw = json.dumps([
            {"name": "test", "value": "v", "domain": ".x.com", "path": "/"},
        ])
        cookies = parse_cookies(raw)
        assert len(cookies) == 1
        assert cookies[0]["name"] == "test"

    def test_parse_cookies_auto_detect_netscape(self):
        from jobpilot.cookies import parse_cookies

        raw = ".x.com\tTRUE\t/\tFALSE\t0\ttest\tvalue"
        cookies = parse_cookies(raw)
        assert len(cookies) == 1
        assert cookies[0]["name"] == "test"

    def test_filter_cookies_for_platform(self):
        from jobpilot.cookies import filter_cookies_for_platform

        cookies = [
            {"name": "li_at", "value": "x", "domain": ".linkedin.com"},
            {"name": "gid", "value": "y", "domain": ".google.com"},
            {"name": "is", "value": "z", "domain": ".internshala.com"},
        ]
        linkedin = filter_cookies_for_platform(cookies, "linkedin")
        assert len(linkedin) == 1
        assert linkedin[0]["name"] == "li_at"

        internshala = filter_cookies_for_platform(cookies, "internshala")
        assert len(internshala) == 1
        assert internshala[0]["name"] == "is"

    def test_validate_cookies_valid(self):
        from jobpilot.cookies import validate_cookies
        import time

        future = time.time() + 86400
        cookies = [
            {"name": "li_at", "value": "x", "domain": ".linkedin.com", "expires": future},
        ]
        result = validate_cookies(cookies, "linkedin")
        assert result["valid"] is True
        assert result["count"] == 1
        assert result["expired"] == 0

    def test_validate_cookies_all_expired(self):
        from jobpilot.cookies import validate_cookies

        cookies = [
            {"name": "li_at", "value": "x", "domain": ".linkedin.com", "expires": 1000},
        ]
        result = validate_cookies(cookies, "linkedin")
        assert result["valid"] is False
        assert result["expired"] == 1

    def test_validate_cookies_no_matching_platform(self):
        from jobpilot.cookies import validate_cookies

        cookies = [
            {"name": "x", "value": "y", "domain": ".other.com"},
        ]
        result = validate_cookies(cookies, "linkedin")
        assert result["valid"] is False
        assert "No cookies found" in result["errors"][0]

    def test_cookies_to_playwright(self):
        from jobpilot.cookies import cookies_to_playwright

        cookies = [
            {
                "name": "test", "value": "val",
                "domain": ".x.com", "path": "/",
                "httpOnly": True, "secure": True,
                "sameSite": "None", "expires": 999999,
            },
        ]
        pw = cookies_to_playwright(cookies)
        assert len(pw) == 1
        assert pw[0]["name"] == "test"
        assert pw[0]["domain"] == ".x.com"
        assert pw[0]["expires"] == 999999


# ═══════════════════════════════════════════════════════════════
# Filter Tests
# ═══════════════════════════════════════════════════════════════

class TestFilters:
    """Test deterministic job filters."""

    def test_check_must_include_passes_when_empty(self):
        from jobpilot.filters import check_must_include

        result = check_must_include("SWE", "some desc", [])
        assert result.passed is True

    def test_check_must_include_passes_when_found(self):
        from jobpilot.filters import check_must_include

        result = check_must_include("Python Developer", "Build APIs", ["python"])
        assert result.passed is True

    def test_check_must_include_fails(self):
        from jobpilot.filters import check_must_include

        result = check_must_include("Java Dev", "Java Spring Boot", ["python"])
        assert result.passed is False

    def test_check_exclude_keywords_passes(self):
        from jobpilot.filters import check_exclude_keywords

        result = check_exclude_keywords("Python Dev", "Build stuff", ["PhD required"])
        assert result.passed is True

    def test_check_exclude_keywords_fails(self):
        from jobpilot.filters import check_exclude_keywords

        result = check_exclude_keywords("Senior Dev", "PhD required, 10 years", ["PhD required"])
        assert result.passed is False

    def test_check_exclude_companies_passes(self):
        from jobpilot.filters import check_exclude_companies

        result = check_exclude_companies("GoodCorp", ["SpamCorp"])
        assert result.passed is True

    def test_check_exclude_companies_fails(self):
        from jobpilot.filters import check_exclude_companies

        result = check_exclude_companies("SpamCorp", ["SpamCorp"])
        assert result.passed is False

    def test_check_exclude_companies_case_insensitive(self):
        from jobpilot.filters import check_exclude_companies

        result = check_exclude_companies("spamcorp", ["SpamCorp"])
        assert result.passed is False

    def test_check_min_stipend_no_minimum(self):
        from jobpilot.filters import check_min_stipend

        result = check_min_stipend("₹5,000", 0)
        assert result.passed is True

    def test_check_min_stipend_passes(self):
        from jobpilot.filters import check_min_stipend

        result = check_min_stipend("₹15,000/month", 10000)
        assert result.passed is True

    def test_check_min_stipend_fails(self):
        from jobpilot.filters import check_min_stipend

        result = check_min_stipend("₹5,000/month", 10000)
        assert result.passed is False

    def test_check_min_stipend_empty(self):
        from jobpilot.filters import check_min_stipend

        result = check_min_stipend("", 10000)
        assert result.passed is True  # No info, let it through

    def test_check_location_no_restrictions(self):
        from jobpilot.filters import check_location

        result = check_location("Bangalore", [], False)
        assert result.passed is True

    def test_check_location_allowed(self):
        from jobpilot.filters import check_location

        result = check_location("Bangalore, India", ["Bangalore"], False)
        assert result.passed is True

    def test_check_location_not_allowed(self):
        from jobpilot.filters import check_location

        result = check_location("New York", ["Bangalore", "Mumbai"], False)
        assert result.passed is False

    def test_check_location_remote_only_passes(self):
        from jobpilot.filters import check_location

        result = check_location("Remote", [], True)
        assert result.passed is True

    def test_check_location_remote_only_fails(self):
        from jobpilot.filters import check_location

        result = check_location("Bangalore Office", [], True)
        assert result.passed is False

    def test_is_duplicate_no_match(self):
        from jobpilot.filters import is_duplicate

        existing = [
            {"title": "Java Developer", "company": "OtherCorp"},
        ]
        result = is_duplicate("Python Developer", "TechCorp", existing)
        assert result.passed is True

    def test_is_duplicate_match(self):
        from jobpilot.filters import is_duplicate

        existing = [
            {"title": "Python Developer", "company": "TechCorp"},
        ]
        result = is_duplicate("Python Developer", "TechCorp", existing)
        assert result.passed is False

    def test_is_duplicate_fuzzy_match(self):
        from jobpilot.filters import is_duplicate

        existing = [
            {"title": "Python Developer", "company": "TechCorp"},
        ]
        result = is_duplicate("Python Software Developer", "TechCorp", existing, threshold=70)
        assert result.passed is False

    def test_apply_all_filters_passes(self):
        from jobpilot.filters import apply_all_filters

        result = apply_all_filters(
            title="Python Developer",
            company="GoodCorp",
            location="Bangalore",
            description="Build APIs with FastAPI",
            stipend="₹15,000",
            config_filters={"exclude_companies": ["SpamCorp"], "exclude_keywords": [], "must_include": [], "min_stipend": 0},
            config_search={"locations": ["Bangalore"], "remote_only": False},
        )
        assert result.passed is True

    def test_apply_all_filters_fails_on_company(self):
        from jobpilot.filters import apply_all_filters

        result = apply_all_filters(
            title="Python Developer",
            company="SpamCorp",
            location="Bangalore",
            description="Build APIs",
            stipend="",
            config_filters={"exclude_companies": ["SpamCorp"], "exclude_keywords": [], "must_include": [], "min_stipend": 0},
            config_search={"locations": [], "remote_only": False},
        )
        assert result.passed is False
        assert "blacklisted" in result.reason.lower()


# ═══════════════════════════════════════════════════════════════
# Caps and Dedupe Tests
# ═══════════════════════════════════════════════════════════════

class TestCapsAndDedupe:
    """Test daily caps and database deduplication."""

    def test_daily_cap_count(self, tmp_path):
        from jobpilot.db import init_db, get_conn, insert_job, get_today_applied_count, update_job_status
        from datetime import datetime, timezone

        db_path = tmp_path / "test.db"
        init_db(db_path)

        with get_conn(db_path) as conn:
            # Insert 3 jobs as applied today
            for i in range(3):
                jid = insert_job(conn, platform="linkedin", platform_job_id=f"j{i}",
                                title=f"Job {i}", company="Corp")
                now = datetime.now(timezone.utc).isoformat()
                update_job_status(conn, jid, "applied", applied_at=now)

            count = get_today_applied_count(conn, "linkedin")
            assert count == 3

    def test_job_exists_dedup(self, tmp_path):
        from jobpilot.db import init_db, get_conn, insert_job, job_exists

        db_path = tmp_path / "test.db"
        init_db(db_path)

        with get_conn(db_path) as conn:
            insert_job(conn, platform="linkedin", platform_job_id="abc123",
                       title="Dev", company="Corp")
            assert job_exists(conn, "linkedin", "abc123") is True
            assert job_exists(conn, "linkedin", "xyz999") is False

    def test_insert_job_duplicate_returns_none(self, tmp_path):
        from jobpilot.db import init_db, get_conn, insert_job

        db_path = tmp_path / "test.db"
        init_db(db_path)

        with get_conn(db_path) as conn:
            id1 = insert_job(conn, platform="linkedin", platform_job_id="dup1",
                            title="Dev", company="Corp")
            assert id1 is not None
            id2 = insert_job(conn, platform="linkedin", platform_job_id="dup1",
                            title="Dev2", company="Corp2")
            assert id2 is None

    def test_qa_cache(self, tmp_path):
        from jobpilot.db import init_db, get_conn, cache_answer, get_cached_answer

        db_path = tmp_path / "test.db"
        init_db(db_path)

        with get_conn(db_path) as conn:
            assert get_cached_answer(conn, "What is your notice period?") is None

            cache_answer(conn, "What is your notice period?", "15 days", source="bank")
            answer = get_cached_answer(conn, "What is your notice period?")
            assert answer == "15 days"

            # Updating the same question should work
            cache_answer(conn, "What is your notice period?", "Immediate", source="user")
            answer = get_cached_answer(conn, "What is your notice period?")
            assert answer == "Immediate"


# ═══════════════════════════════════════════════════════════════
# LLM JSON Parsing Tests (LLM mocked)
# ═══════════════════════════════════════════════════════════════

class TestLLMJsonParsing:
    """Test LLM output JSON parsing with various formats."""

    def test_parse_clean_json(self):
        from jobpilot.llm import parse_llm_json

        result = parse_llm_json('{"score": 85, "reason": "Good match"}')
        assert result["score"] == 85
        assert result["reason"] == "Good match"

    def test_parse_json_with_code_fence(self):
        from jobpilot.llm import parse_llm_json

        raw = '```json\n{"score": 90, "reason": "Excellent fit"}\n```'
        result = parse_llm_json(raw)
        assert result["score"] == 90

    def test_parse_json_embedded_in_prose(self):
        from jobpilot.llm import parse_llm_json

        raw = 'Here is my assessment: {"score": 75, "reason": "Decent match"} as you can see.'
        result = parse_llm_json(raw)
        assert result["score"] == 75

    def test_parse_json_with_think_tags(self):
        from jobpilot.llm import parse_llm_json

        raw = '<think>Let me analyze this...</think>{"score": 60, "reason": "Okay match"}'
        result = parse_llm_json(raw)
        assert result["score"] == 60

    def test_parse_unparseable_returns_default(self):
        from jobpilot.llm import parse_llm_json

        result = parse_llm_json("This is not JSON at all, just text.")
        assert result["score"] == 0
        assert "unparseable" in result["reason"].lower()

    def test_parse_empty_string(self):
        from jobpilot.llm import parse_llm_json

        result = parse_llm_json("")
        assert result["score"] == 0

    def test_parse_answer_json(self):
        from jobpilot.llm import parse_llm_json

        raw = '{"answer": "Yes, I am available immediately."}'
        result = parse_llm_json(raw)
        assert result["answer"] == "Yes, I am available immediately."

    def test_rule_based_score(self):
        from jobpilot.llm import _rule_based_score

        result = _rule_based_score(
            "Python Developer",
            "We need someone with Python and FastAPI experience",
            ["Python Developer", "Backend Engineer"],
        )
        assert result["score"] > 0
        assert "Rule-based" in result["reason"]

    def test_rule_based_score_no_match(self):
        from jobpilot.llm import _rule_based_score

        result = _rule_based_score(
            "Java Developer",
            "Spring Boot and Hibernate required",
            ["Python Developer"],
        )
        assert result["score"] == 0 or result["score"] < 40

    def test_strip_think_tags(self):
        from jobpilot.llm import _strip_think_tags

        text = "<think>reasoning here</think>actual output"
        assert _strip_think_tags(text) == "actual output"

    def test_strip_think_tags_multiline(self):
        from jobpilot.llm import _strip_think_tags

        text = "<think>\nlong\nreasoning\n</think>\nclean output"
        assert _strip_think_tags(text).strip() == "clean output"

    def test_strip_think_tags_no_tags(self):
        from jobpilot.llm import _strip_think_tags

        text = "no think tags here"
        assert _strip_think_tags(text) == "no think tags here"


# ═══════════════════════════════════════════════════════════════
# LLM Scoring / Answering (mocked)
# ═══════════════════════════════════════════════════════════════

class TestLLMFunctions:
    """Test LLM scoring and answering with the LLM client mocked."""

    @pytest.mark.asyncio
    async def test_score_job_with_mock(self, monkeypatch):
        from jobpilot import llm

        async def mock_chat_with_fallback(messages, max_tokens=80):
            return '{"score": 82, "reason": "Strong Python match"}'

        monkeypatch.setattr(llm, "_chat_with_fallback", mock_chat_with_fallback)

        result = await llm.score_job(
            title="Python Developer",
            company="TechCorp",
            description="Build APIs with Python and FastAPI",
            candidate_summary="Python developer with FastAPI experience",
            search_titles=["Python Developer"],
        )
        assert result["score"] == 82
        assert "Python" in result["reason"]

    @pytest.mark.asyncio
    async def test_score_job_llm_unavailable_fallback(self, monkeypatch):
        from jobpilot import llm

        async def mock_chat_with_fallback(messages, max_tokens=80):
            return None  # Simulate LLM failure

        monkeypatch.setattr(llm, "_chat_with_fallback", mock_chat_with_fallback)

        result = await llm.score_job(
            title="Python Developer",
            company="TechCorp",
            description="Build APIs with Python and FastAPI",
            candidate_summary="Python developer",
            search_titles=["Python Developer"],
        )
        assert "Rule-based" in result["reason"]
        assert result["score"] >= 0

    @pytest.mark.asyncio
    async def test_answer_question_from_bank(self):
        from jobpilot.llm import answer_question

        answer = await answer_question(
            "What is your notice period?",
            "Python developer",
            {"notice period": "15 days"},
        )
        assert answer == "15 days"

    @pytest.mark.asyncio
    async def test_answer_question_from_llm(self, monkeypatch):
        from jobpilot import llm

        async def mock_chat_with_fallback(messages, max_tokens=80):
            return '{"answer": "I have 2 years of experience."}'

        monkeypatch.setattr(llm, "_chat_with_fallback", mock_chat_with_fallback)

        answer = await llm.answer_question(
            "How many years of experience do you have?",
            "2 years of Python development",
            {},  # Empty answer bank
        )
        assert "2 years" in answer

    @pytest.mark.asyncio
    async def test_generate_cover_note_with_mock(self, monkeypatch):
        from jobpilot import llm

        async def mock_chat_with_fallback(messages, max_tokens=80):
            return '{"cover_note": "I am excited to apply for this role."}'

        monkeypatch.setattr(llm, "_chat_with_fallback", mock_chat_with_fallback)

        note = await llm.generate_cover_note(
            "Python Dev", "TechCorp", "Build stuff", "Python experience",
        )
        assert "excited" in note.lower()

    @pytest.mark.asyncio
    async def test_generate_cover_note_llm_fallback(self, monkeypatch):
        from jobpilot import llm

        async def mock_chat_with_fallback(messages, max_tokens=80):
            return None

        monkeypatch.setattr(llm, "_chat_with_fallback", mock_chat_with_fallback)

        note = await llm.generate_cover_note(
            "Python Dev", "TechCorp", "Build stuff", "Python experience",
        )
        assert "Python Dev" in note  # Falls back to template


# ═══════════════════════════════════════════════════════════════
# Token Tracking Tests
# ═══════════════════════════════════════════════════════════════

class TestTokenTracking:
    def test_token_usage_accumulation(self):
        from jobpilot.llm import TokenUsage

        usage = TokenUsage()
        usage.add(100, 50)
        usage.add(200, 75)
        assert usage.prompt_tokens == 300
        assert usage.completion_tokens == 125
        assert usage.total == 425

    def test_token_usage_to_dict(self):
        from jobpilot.llm import TokenUsage

        usage = TokenUsage()
        usage.add(10, 5)
        d = usage.to_dict()
        assert d == {"tokens_in": 10, "tokens_out": 5}

    def test_reset_run_tokens(self):
        from jobpilot.llm import get_run_tokens, reset_run_tokens

        get_run_tokens().add(100, 50)
        reset_run_tokens()
        t = get_run_tokens()
        assert t.prompt_tokens == 0
        assert t.completion_tokens == 0


# ═══════════════════════════════════════════════════════════════
# Event Bus Tests
# ═══════════════════════════════════════════════════════════════

class TestEventBus:
    @pytest.mark.asyncio
    async def test_publish_and_history(self):
        from jobpilot.events import EventBus

        bus = EventBus()
        await bus.publish("test message", level="info", platform="mock")
        history = bus.get_history()
        assert len(history) == 1
        assert history[0].message == "test message"
        assert history[0].platform == "mock"

    @pytest.mark.asyncio
    async def test_subscribe_receives_events(self):
        from jobpilot.events import EventBus

        bus = EventBus()
        received = []

        async def consumer():
            async for event in bus.subscribe(include_history=False):
                received.append(event)
                if len(received) >= 2:
                    break

        task = asyncio.create_task(consumer())
        await asyncio.sleep(0.05)
        await bus.publish("msg1")
        await bus.publish("msg2")
        await asyncio.wait_for(task, timeout=2.0)

        assert len(received) == 2
        assert received[0].message == "msg1"
        assert received[1].message == "msg2"


# ═══════════════════════════════════════════════════════════════
# Settings Tests
# ═══════════════════════════════════════════════════════════════

class TestSettings:
    def test_load_config_defaults(self, tmp_path):
        from jobpilot.settings import load_config

        empty_path = tmp_path / "empty.yaml"
        empty_path.write_text("")
        config = load_config(empty_path)
        assert config.behavior.dry_run is True
        assert config.limits.max_daily["linkedin"] == 15

    def test_load_save_config_roundtrip(self, tmp_path):
        from jobpilot.settings import load_config, save_config

        path = tmp_path / "config.yaml"
        path.write_text("")

        config = load_config(path)
        config.search.titles = ["Data Scientist"]
        save_config(config, path)

        loaded = load_config(path)
        assert loaded.search.titles == ["Data Scientist"]

    def test_load_profile_defaults(self, tmp_path):
        from jobpilot.settings import load_profile

        empty_path = tmp_path / "empty.yaml"
        empty_path.write_text("")
        profile = load_profile(empty_path)
        assert profile.personal.full_name == ""

    def test_load_save_profile_roundtrip(self, tmp_path):
        from jobpilot.settings import load_profile, save_profile

        path = tmp_path / "profile.yaml"
        path.write_text("")

        profile = load_profile(path)
        profile.personal.full_name = "Test User"
        profile.answer_bank["test q"] = "test a"
        save_profile(profile, path)

        loaded = load_profile(path)
        assert loaded.personal.full_name == "Test User"
        assert loaded.answer_bank["test q"] == "test a"


# ═══════════════════════════════════════════════════════════════
# Database Tests
# ═══════════════════════════════════════════════════════════════

class TestDatabase:
    def test_init_and_insert(self, tmp_path):
        from jobpilot.db import init_db, get_conn, insert_job, get_jobs

        db_path = tmp_path / "test.db"
        init_db(db_path)

        with get_conn(db_path) as conn:
            jid = insert_job(conn, platform="mock", platform_job_id="m1",
                            title="Test Job", company="TestCo", location="Remote")
            assert jid is not None

            jobs = get_jobs(conn)
            assert len(jobs) == 1
            assert jobs[0]["title"] == "Test Job"

    def test_run_tracking(self, tmp_path):
        from jobpilot.db import init_db, get_conn, create_run, update_run, get_latest_runs

        db_path = tmp_path / "test.db"
        init_db(db_path)

        with get_conn(db_path) as conn:
            rid = create_run(conn, mode="dry")
            update_run(conn, rid, found=10, applied=5, status="completed")

            runs = get_latest_runs(conn)
            assert len(runs) == 1
            assert runs[0]["found"] == 10
            assert runs[0]["applied"] == 5

    def test_session_tracking(self, tmp_path):
        from jobpilot.db import init_db, get_conn, update_session, get_sessions

        db_path = tmp_path / "test.db"
        init_db(db_path)

        with get_conn(db_path) as conn:
            update_session(conn, "linkedin", "ok")
            update_session(conn, "internshala", "expired")
            sessions = get_sessions(conn)
            assert sessions["linkedin"]["status"] == "ok"
            assert sessions["internshala"]["status"] == "expired"

    def test_event_tracking(self, tmp_path):
        from jobpilot.db import init_db, get_conn, insert_event, get_events

        db_path = tmp_path / "test.db"
        init_db(db_path)

        with get_conn(db_path) as conn:
            insert_event(conn, "Test event", level="info", platform="mock", run_id=1)
            events = get_events(conn, run_id=1)
            assert len(events) == 1
            assert events[0]["message"] == "Test event"


# ═══════════════════════════════════════════════════════════════
# Mock Platform Tests
# ═══════════════════════════════════════════════════════════════

class TestMockPlatform:
    @pytest.mark.asyncio
    async def test_mock_check_login(self):
        from jobpilot.platforms.mock import MockPlatform
        from jobpilot.settings import load_config, load_profile

        config = load_config()
        profile = load_profile()
        platform = MockPlatform(config, profile)

        status = await platform.check_login(None)
        assert status == "ok"

    @pytest.mark.asyncio
    async def test_mock_search_returns_jobs(self):
        from jobpilot.platforms.mock import MockPlatform
        from jobpilot.settings import load_config, load_profile

        config = load_config()
        profile = load_profile()
        platform = MockPlatform(config, profile)

        jobs = await platform.search(None)
        assert len(jobs) > 0
        for job in jobs:
            assert "title" in job
            assert "company" in job
            assert "platform_job_id" in job

    @pytest.mark.asyncio
    async def test_mock_apply_succeeds(self):
        from jobpilot.platforms.mock import MockPlatform
        from jobpilot.settings import load_config, load_profile

        config = load_config()
        profile = load_profile()
        platform = MockPlatform(config, profile)

        result = await platform.apply(None, {"title": "Test", "url": "http://mock"})
        assert result["success"] is True
