# JobPilot Web Layer Handoff Guide

This document describes the complete backend contract for building `jobpilot/web/` (FastAPI + Jinja2 + HTMX + Alpine.js).
All backend modules are fully implemented, tested, and ready.

---

## 1. Settings & Configuration (`jobpilot.settings`)

### Public Data Models
- **`AppConfig` (`pydantic.BaseModel`)**: Complete configuration matching `config.yaml`.
  - `.search`: `SearchConfig` (`titles`, `keywords`, `locations`, `remote_only`, `job_type`, `experience_level`, `posted_within_days`)
  - `.filters`: `FiltersConfig` (`must_include`, `exclude_keywords`, `exclude_companies`, `min_stipend`, `min_llm_score`)
  - `.limits`: `LimitsConfig` (`max_daily: dict[str, int]`, `max_per_run`, `delay_min`, `delay_max`, `active_hours`, `schedule`)
  - `.behavior`: `BehaviorConfig` (`dry_run`, `headless`, `easy_apply_only`, `restart_browser_every`)
  - `.platforms`: `PlatformsConfig` (`linkedin`, `internshala`, `google_jobs`, `mock` each with `.enabled`)
- **`Profile` (`pydantic.BaseModel`)**: Candidate profile matching `profile.yaml`.
  - `.personal`: `PersonalDetails` (`name`, `email`, `phone`, `current_city`, `linkedin_url`, `github_url`, `portfolio_url`)
  - `.education`: `list[EducationEntry]`
  - `.experience`: `list[ExperienceEntry]`
  - `.skills`: `list[str]`
  - `.answer_bank`: `dict[str, str]` (Common application Q&A pairs)
  - `.resume_path`: `str`
  - `.experience_summary`: `str` (~150 words used for LLM scoring)
- **`EnvSettings` (`pydantic_settings.BaseSettings`)**: Runtime environment settings loaded from `.env`.
  - `llm_base_url`, `llm_api_key`, `llm_model`, `llm_fallback_model`, `host`, `port`, `log_level`

### Public Functions
```python
def load_config() -> AppConfig
```
*Loads and validates `config.yaml` from disk; returns default `AppConfig` if missing.*

```python
def save_config(config: AppConfig) -> None
```
*Serializes and writes `AppConfig` back to `config.yaml` on disk.*

```python
def load_profile() -> Profile
```
*Loads and validates candidate `profile.yaml` from disk.*

```python
def save_profile(profile: Profile) -> None
```
*Serializes and writes candidate `Profile` back to `profile.yaml` on disk.*

```python
def load_env() -> EnvSettings
```
*Reads current environment variables and `.env` settings.*

---

## 2. Database & Repository Layer (`jobpilot.db`)

All DB operations use `sqlite3` with WAL mode enabled. Paths default to `data/jobpilot.db`.

### Connection & Lifecycle
```python
def init_db(db_path: Path | None = None) -> None
```
*Initializes database schema and ensures WAL mode is enabled.*

```python
def get_conn(db_path: Path | None = None) -> Generator[sqlite3.Connection, None, None]
```
*Context manager yielding a thread-safe `sqlite3.Connection` with row factories enabled.*

### Jobs Repository
```python
def insert_job(conn: sqlite3.Connection, platform: str, platform_job_id: str, title: str, company: str, location: str = "", url: str = "", description: str = "", posted_at: str | None = None, stipend: str | None = None, status: str = "found") -> int | None
```
*Inserts a new job listing; returns `job_id`, or `None` if `(platform, platform_job_id)` is a duplicate.*

```python
def job_exists(conn: sqlite3.Connection, platform: str, platform_job_id: str) -> bool
```
*Returns `True` if `(platform, platform_job_id)` is already recorded in the database.*

```python
def update_job_status(conn: sqlite3.Connection, job_id: int, status: str, score: int | None = None, reason: str | None = None, applied_at: str | None = None, error: str | None = None) -> None
```
*Updates job processing status (`found`, `filtered_out`, `low_score`, `queued`, `dry_run`, `applied`, `failed`, `manual_needed`).*

```python
def get_jobs(conn: sqlite3.Connection, platform: str | None = None, status: str | None = None, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]
```
*Fetches paginated job rows filtered by platform and/or status.*

```python
def count_jobs(conn: sqlite3.Connection, platform: str | None = None, status: str | None = None) -> int
```
*Returns total job counts matching optional platform and/or status filters.*

### Statistics & Caps
```python
def get_today_applied_count(conn: sqlite3.Connection, platform: str) -> int
```
*Returns number of jobs marked `applied` on the specified platform today (UTC).*

```python
def get_today_stats(conn: sqlite3.Connection) -> dict[str, int]
```
*Returns today's metrics: `{"applied_today": int, "found_today": int, "manual_needed": int}`.*

```python
def get_daily_application_counts(conn: sqlite3.Connection, days: int = 14) -> list[dict[str, Any]]
```
*Returns daily counts for charts: `[{"day": "YYYY-MM-DD", "count": int}, ...]`.*

```python
def get_total_tokens(conn: sqlite3.Connection) -> dict[str, int]
```
*Returns all-time token usage: `{"tokens_in": int, "tokens_out": int}`.*

```python
def get_today_tokens(conn: sqlite3.Connection) -> dict[str, int]
```
*Returns today's token usage: `{"tokens_in": int, "tokens_out": int}`.*

### Sessions Repository
```python
def update_session(conn: sqlite3.Connection, platform: str, status: str) -> None
```
*Updates platform session status (`ok`, `expired`, `checkpoint`, `missing`) with current timestamp.*

```python
def get_sessions(conn: sqlite3.Connection) -> dict[str, dict[str, str]]
```
*Returns map of `{platform: {"status": str, "checked_at": str}}`.*

### Runs Repository
```python
def create_run(conn: sqlite3.Connection, mode: str = "dry") -> int
```
*Creates a new run entry in `runs` table and returns `run_id`.*

```python
def update_run(conn: sqlite3.Connection, run_id: int, **kwargs: Any) -> None
```
*Updates run metrics upon completion (`ended_at`, `found`, `filtered`, `applied`, `failed`, `tokens_in`, `tokens_out`, `status`).*

```python
def get_latest_runs(conn: sqlite3.Connection, limit: int = 10) -> list[dict[str, Any]]
```
*Returns history of recent application runs.*

### QA Cache Repository
```python
def get_cached_answer(conn: sqlite3.Connection, question: str) -> str | None
```
*Retrieves cached answer by SHA256 of normalized question, or `None`.*

```python
def cache_answer(conn: sqlite3.Connection, question: str, answer: str, source: str = "llm") -> None
```
*Caches question and answer in `qa_cache` table.*

```python
def get_all_qa(conn: sqlite3.Connection) -> list[dict[str, Any]]
```
*Returns all cached question/answer pairs for UI inspection/editing.*

```python
def delete_qa(conn: sqlite3.Connection, question_hash: str) -> None
```
*Deletes an entry from `qa_cache` by its hash.*

### Event Logging Repository
```python
def insert_event(conn: sqlite3.Connection, message: str, level: str = "info", platform: str | None = None, run_id: int | None = None) -> int
```
*Persists a log event into the SQLite `events` table.*

```python
def get_events(conn: sqlite3.Connection, run_id: int | None = None, limit: int = 100) -> list[dict[str, Any]]
```
*Fetches stored log events from the database.*

---

## 3. Runner & Execution Control (`jobpilot.runner`)

### `run_state` (Global `RunState` Instance)
- `run_state.is_running`: `bool` — `True` when an execution is currently active.
- `run_state.status`: `str` — `"idle" | "running" | "stopped"`.
- `run_state.current_run_id`: `int | None` — Active database run ID.
- `run_state.mode`: `str` — `"dry" | "live"`.

### Public Functions
```python
def start_run_background(dry_run: bool = True) -> None
```
*Launches `execute_run(dry_run=dry_run)` as a background asyncio task from FastAPI.*

```python
def stop_run() -> None
```
*Sets the stop flag on `run_state`. The active runner checks this flag between actions and gracefully terminates.*

```python
async def execute_run(dry_run: bool = True, cli_mode: bool = False, config_override: AppConfig | None = None) -> dict[str, Any]
```
*Main execution pipeline (launches browser, checks sessions, searches, dedupes, filters, scores, applies, enforces delays and caps). Returns summary dict.*

---

## 4. Real-time Events & SSE (`jobpilot.events`)

### Event Model
```python
@dataclass
class Event:
    level: str        # "info" | "warning" | "error" | "debug"
    message: str      # Human-readable log line
    platform: str | None = None
    run_id: int | None = None
    timestamp: str    # ISO 8601 UTC string
    def to_dict(self) -> dict[str, Any]
```

### `event_bus` (`EventBus` Instance)
```python
async def event_bus.subscribe(include_history: bool = True) -> AsyncGenerator[Event, None]
```
*Async generator yielding events as they happen. If `include_history=True`, replays recent backlog on connection.*

```python
async def event_bus.publish(message: str, level: str = "info", platform: str | None = None, run_id: int | None = None) -> Event
```
*Publishes an event to all connected SSE clients and logs to loguru.*

```python
def event_bus.get_history() -> list[Event]
```
*Returns up to 500 recent events stored in memory.*

#### SSE Route Example for `jobpilot/web/routes_logs.py`:
```python
from sse_starlette.sse import EventSourceResponse
from jobpilot.events import event_bus

@router.get("/logs/stream")
async def stream_logs():
    async def generator():
        async for evt in event_bus.subscribe(include_history=True):
            yield {"event": "message", "data": evt.to_dict()}
    return EventSourceResponse(generator())
```

---

## 5. Cookie Management (`jobpilot.cookies`)

### Public Functions
```python
def parse_cookies(raw: str) -> list[dict[str, Any]]
```
*Auto-detects format (Cookie-Editor JSON array or Netscape `cookies.txt`) and parses into normalized cookie dicts.*

```python
def validate_cookies(cookies: list[dict[str, Any]], platform: str) -> dict[str, Any]
```
*Validates cookies for `platform` (`"linkedin" | "internshala" | "google"`).*
*Returns: `{"valid": bool, "count": int, "expired": int, "errors": list[str]}`.*

```python
def save_cookies_file(cookies: list[dict[str, Any]], platform: str) -> Path
```
*Saves normalized cookies to `cookies/<platform>.json` with permission `0600`.*

```python
def load_cookies_file(platform: str) -> list[dict[str, Any]]
```
*Loads saved cookies for a platform from disk; returns empty list if missing.*

```python
def delete_cookies_file(platform: str) -> bool
```
*Deletes `cookies/<platform>.json`. Returns `True` if deleted.*

---

## 6. Browser & Session Status (`jobpilot.browser`)

### Public Functions
```python
async def check_session(page: playwright.async_api.Page, platform: str) -> str
```
*Navigates to the platform and inspects login indicators.*
*Returns: `'ok'` (logged in), `'expired'` (login page), `'checkpoint'` (challenge / captcha detected), or `'missing'`.*

```python
class BrowserManager:
    async def launch(self, headless: bool = True) -> BrowserManager
    async def new_context(self, platform: str | None = None) -> Page
    async def take_screenshot(self, name: str) -> Path | None
    async def close(self) -> None
```
*Playwright browser manager with memory-saving route filters (blocks images, media, analytics) and screenshot captures.*

---

## 7. LLM Operations (`jobpilot.llm`)

### Public Functions
```python
async def list_models(base_url: str | None = None, api_key: str | None = None) -> list[dict[str, str]]
```
*Calls `GET {base_url}/models`. Returns list of `[{"id": str, "name": str}, ...]`. Used to populate Settings model dropdown.*

```python
async def test_connection(base_url: str | None = None, api_key: str | None = None, model: str | None = None) -> dict[str, Any]
```
*Sends a minimal 5-token ping to the model. Returns `{"ok": bool, "latency_ms": float, "model": str, "error": str | None}`.*

```python
async def score_job(title: str, company: str, description: str, candidate_summary: str, search_titles: list[str]) -> dict[str, Any]
```
*Scores job relevance from 0–100. Returns `{"score": int, "reason": str}` with automatic fallback to rule-based scoring.*

```python
async def answer_question(question: str, profile_summary: str, answer_bank: dict[str, str]) -> str
```
*Answers form questions by checking `answer_bank` first, then LLM.*

```python
async def generate_cover_note(job_title: str, company: str, description: str, profile_summary: str) -> str
```
*Generates a 2-3 sentence cover letter note for applications.*

```python
def get_run_tokens() -> TokenUsage
```
*Returns active run token usage accumulator (`.prompt_tokens`, `.completion_tokens`, `.to_dict()`).*

```python
def reset_run_tokens() -> None
```
*Resets run token count.*

---

## 8. Scheduler (`jobpilot.scheduler`)

### Public Functions
```python
def start_scheduler() -> None
```
*Initializes and starts the APScheduler AsyncIOScheduler.*

```python
def stop_scheduler() -> None
```
*Shuts down the scheduler.*

```python
def configure_schedule() -> None
```
*Reads `config.yaml` (`limits.schedule.enabled` and `.time`) and registers or removes the daily cron job.*

```python
def get_scheduler() -> AsyncIOScheduler
```
*Returns the underlying APScheduler instance.*

---

## 9. Web Application Structure Checklist

The web layer to be built in `jobpilot/web/` will provide:
1. `app.py`: FastAPI initialization, mounting static assets (`/static`), template directory (`/templates`), and including routers.
2. `routes_dashboard.py`:
   - `GET /`: Main dashboard (today's stats, active sessions, quick start/stop buttons, recent runs).
   - `POST /run/start`: Trigger `start_run_background(dry_run=...)`.
   - `POST /run/stop`: Trigger `stop_run()`.
   - `GET /run/status`: Polled by Alpine.js / HTMX for button states.
3. `routes_jobs.py`:
   - `GET /jobs`: Filterable, paginated table of jobs.
4. `routes_cookies.py`:
   - `GET /cookies`: Status of platform cookies.
   - `POST /cookies/upload` / `POST /cookies/paste`: Handle raw JSON or file, invoke `parse_cookies`, `validate_cookies`, `save_cookies_file`.
   - `POST /cookies/check`: Run session check for a platform.
5. `routes_settings.py`:
   - `GET /settings`: Form for `config.yaml` and `.env` parameters.
   - `POST /settings`: Save config via `save_config`.
   - `GET /settings/models`: HTMX endpoint loading `list_models()`.
   - `POST /settings/test-llm`: HTMX endpoint triggering `test_connection()`.
6. `routes_profile.py`:
   - `GET /profile`, `POST /profile`: Form for `profile.yaml` with resume upload.
   - `GET /profile/qa`, `DELETE /profile/qa/{hash}`: Manage `qa_cache`.
7. `routes_logs.py`:
   - `GET /logs`: Live terminal viewer.
   - `GET /logs/stream`: SSE endpoint consuming `event_bus.subscribe()`.
