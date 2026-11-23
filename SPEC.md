You are building "JobPilot": a lightweight, local, autonomous job-application agent with a web dashboard. Make all technical decisions within the constraints below and do not ask me questions. Deliver complete, runnable code with no placeholders or TODOs. At the end, run the app, run the tests and a dry-run, fix all errors, and write a short README.

# 1. WHAT IT DOES
Logs into LinkedIn and Internshala using cookies I export from my own Chrome (no password logins), searches jobs/internships by my filters, scores relevance with a cheap LLM, and applies automatically (LinkedIn Easy Apply, Internshala Apply). Google is used only for job discovery (Google Jobs search) and for Google-session cookies. Everything is controlled from a local web dashboard at http://127.0.0.1:8000. Runs on a low-RAM laptop.

# 2. TECH STACK (fixed, do not substitute)
- Language: Python 3.11+ (Rust gives no real RAM benefit; Chromium uses nearly all the memory)
- Browser automation: Playwright async API, Chromium only
- Backend/UI server: FastAPI + Uvicorn (single worker)
- Frontend: server-rendered Jinja2 templates + HTMX + Alpine.js + Tailwind CSS (all via CDN, no Node/npm build step, no React)
- Live logs: Server-Sent Events (sse-starlette)
- DB: SQLite via stdlib sqlite3 (WAL mode), thin repository layer
- Scheduler: APScheduler (AsyncIOScheduler) for optional daily runs
- LLM client: official `openai` SDK pointed at any OpenAI-compatible base_url
- Config: PyYAML + pydantic v2 + pydantic-settings + python-dotenv
- Utilities: tenacity (retries/backoff), loguru (logging), rapidfuzz (dedupe/fuzzy matching), python-multipart (uploads), beautifulsoup4+lxml (parsing when useful)
- Testing: pytest, pytest-asyncio
- DO NOT use: playwright-stealth or any anti-detection/captcha-bypass tools, Selenium, Streamlit, heavy ORMs, Docker, Redis, Celery.

# 3. LLM MODEL (runtime model used by the agent)
- Provider: OpenAI-compatible endpoint, fully configurable in .env: LLM_BASE_URL, LLM_API_KEY, LLM_MODEL, LLM_FALLBACK_MODEL.
- Default provider: NVIDIA NIM free tier (https://integrate.api.nvidia.com/v1) with the smallest available Nemotron instruct model (e.g. a Nemotron Nano ~4B-9B). Second option: OpenRouter free-tier models (https://openrouter.ai/api/v1) using the smallest ":free" instruct model.
- Model IDs change often. On startup and in Settings, call GET {base_url}/models, show the list in a dropdown, and let me pick. Pre-select the smallest instruct model that matches the default. Never hardcode one ID as the only option.
- If the chosen model is a "reasoning/thinking" model, disable thinking (use "/no_think" in the system prompt or the provider's parameter) and strip any <think>...</think> text from output. Token minimization is the priority.
- Parameters: temperature 0, max_tokens 80 for scoring, 150 for form answers, 120 for cover note. Ask for strict JSON, parse with a safe fallback.
- Token-saving rules: deterministic filters run BEFORE any LLM call; truncate JD to ~1200 chars; candidate summary ~150 words; cache every answer in SQLite (qa_cache keyed by normalized question); hit the answer bank in profile.yaml first; on 429 use exponential backoff (tenacity), then switch to the fallback model, then to rule-only mode. Track prompt/completion tokens per call and per run.
- "Test connection" button in Settings that sends a 5-token ping and shows latency.

# 4. PROJECT STRUCTURE
jobpilot/
  main.py                      (CLI: serve | run [--dry-run] | stats)
  requirements.txt, .env.example, .gitignore, README.md
  config.yaml, profile.yaml    (created with realistic samples; editable from UI)
  jobpilot/
    settings.py                (pydantic models for config/profile/env, load/save YAML)
    db.py                      (schema, migrations, repositories)
    llm.py                     (client, scoring, form-answering, token accounting, fallback chain)
    cookies.py                 (parse Cookie-Editor JSON + Netscape cookies.txt, normalize sameSite/expiry/domain, validate)
    browser.py                 (launch Chromium, context, route-blocking, session check, screenshots)
    filters.py                 (keyword/location/stipend/company blacklist/dedupe rules)
    humanize.py                (random delays, small scrolls, active-hours check)
    runner.py                  (orchestrates a run, daily caps, stop flag, event emitter)
    events.py                  (in-memory pub/sub feeding SSE log stream)
    scheduler.py
    platforms/
      base.py                  (abstract Platform: check_login, search, parse_listing, apply)
      linkedin.py, internshala.py, google_jobs.py
      selectors_linkedin.py, selectors_internshala.py, selectors_google.py   (all selectors isolated here, prefer role/text locators)
    web/
      app.py                   (FastAPI app, routes)
      routes_*.py              (dashboard, jobs, settings, profile, cookies, logs)
      templates/               (base.html + one template per page + partials/)
      static/                  (minimal custom css/js only)
  cookies/.gitkeep, logs/.gitkeep, data/.gitkeep, tests/

# 5. DATABASE (SQLite)
- jobs: id, platform, platform_job_id, title, company, location, url, description, posted_at, stipend, status, score, reason, applied_at, error, created_at. UNIQUE(platform, platform_job_id).
- Statuses: found, filtered_out, low_score, queued, applied, failed, manual_needed, dry_run.
- qa_cache: question_hash, question, answer, source (bank/llm/user), created_at.
- runs: id, started_at, ended_at, mode (dry/live), found, filtered, applied, failed, manual, tokens_in, tokens_out, status.
- sessions: platform, status (ok/expired/checkpoint/missing), checked_at.
- events: id, run_id, ts, level, platform, message (used for the live log).

# 6. CORE BEHAVIOR
Run flow: load config -> check active-hours and daily caps -> for each enabled platform: inject cookies, verify login, search with filters, paginate, collect listings -> dedupe against DB -> rule filters -> LLM score (only survivors) -> apply if score >= min_llm_score and caps allow -> record result -> random delay -> next.

- Cookie auth: cookies are exported by me with a Chrome extension (Cookie-Editor, or "Get cookies.txt LOCALLY"). Accept pasted JSON or an uploaded file via the UI. Validate domains. Never log cookie values; store files under cookies/ (gitignored, chmod 600).
- Login check: look for a logged-in element. If expired, or a captcha/checkpoint/2FA/"unusual activity" page appears, STOP that platform immediately, mark session status, show a red banner in the UI, and continue with the other platforms. Never attempt to bypass captchas or verification.
- LinkedIn: Jobs search URL with filter params, handle ONLY the Easy Apply multi-step modal. Fill fields from profile/answer bank/LLM, upload resume. If a required field cannot be answered confidently, abort and mark manual_needed. External-apply jobs: skip, mark manual_needed with URL.
- Internshala: search internships/jobs with filters, open listing, Apply, fill cover letter and custom assignment questions (LLM with cache), submit.
- Google Jobs: query "<title> <location>", collect listing links, keep only ones pointing to LinkedIn/Internshala, dedupe.
- Safety: one Chromium, one context, one tab at a time. Random delay 8-25s (configurable), small random scrolling, strict per-platform daily caps stored in DB (defaults: LinkedIn 15, Internshala 30), active-hours window, never apply twice. On any error: screenshot to logs/, mark failed, continue; a single failure never crashes the run.
- RAM budget: block images/fonts/media/analytics via route interception, launch args --disable-gpu --disable-extensions --disable-dev-shm-usage --js-flags=--max-old-space-size=256, close pages after each job, restart the browser every 50 jobs. Target total app RAM under ~700 MB.
- Dry-run: does everything except the final submit click; logs what it would have applied to. Default is dry-run ON until I turn it off in the UI.
- Runs execute as a background asyncio task inside the server; Start/Stop buttons control it via a stop flag checked between every action.

# 7. WEB DASHBOARD (design spec)
Style: clean, minimal, dark mode default with light toggle, Tailwind, rounded-xl cards, one accent color (indigo), Inter font, responsive down to mobile width. Left sidebar (icons + labels) on desktop, bottom tab bar on mobile. Toast notifications for save/errors. No page reloads for actions (HTMX).

Sidebar: Dashboard | Jobs | Settings | Profile | Cookies | Logs

PAGE 1: DASHBOARD
  Top bar: "JobPilot"  [Dry-run ON/OFF toggle]  [Start run] [Stop]  status pill (Idle/Running/Stopped)
  Row of 4 stat cards: Applied today | Found today | Needs manual | Tokens used today
  Row of 3 platform cards (LinkedIn / Internshala / Google): session status dot (green/amber/red), daily cap progress bar (e.g. 7/15), enable switch, "Check session" button
  Left (2/3 width): "Recent applications" table (last 10: time, platform badge, title, company, status badge, score)
  Right (1/3 width): live activity feed (SSE), newest on top, colored by level
  Bottom: 14-day bar chart of applications per day (lightweight inline SVG/CSS, no chart library)

PAGE 2: JOBS
  Filter bar: search box, platform select, status select, score slider, date range
  Table: Title/Company, Platform, Location, Score + one-line reason, Status badge, Date, row actions (Open link, Mark applied manually, Retry, Skip/Blacklist company)
  Pagination 25/page, CSV export button. Click row opens a side drawer with the JD text and the application log.

PAGE 3: SETTINGS (tabs; every field maps to config.yaml and saves via HTMX with validation)
  Tab Search: tag-input for job titles/keywords, locations, remote-only switch, job type (internship/full-time/both), experience level, posted-within-days slider
  Tab Filters: must-include keywords, exclude keywords, exclude companies, min stipend, min LLM score slider (default 70)
  Tab Limits: max per day per platform, max per run, delay range (min/max sliders), active hours (from/to), schedule (off / daily at HH:MM)
  Tab Behavior: dry-run, headless, Easy-Apply-only, restart-browser interval
  Tab LLM: base URL, API key (masked, stored in .env), model dropdown (fetched from /models), fallback model, max tokens, enable/disable LLM, "Test connection" button, token usage chart

PAGE 4: PROFILE
  Form sections: personal info, education, skills (tags), experience summary (textarea used for LLM scoring, shows word count, warns above 150 words), resume PDF upload, links, and an editable "Answer bank" table (question pattern -> answer) pre-filled with notice period, expected salary, work authorization, relocation, years of experience per skill. Also lists cached LLM answers from qa_cache so I can correct or delete them.

PAGE 5: COOKIES
  One card per platform: status badge, last updated, [Upload file] [Paste JSON/text] [Test login] [Delete]. Collapsible "How to export" help with the extension names and 4 steps. Warning note: a cookie file equals full account access, keep it private.

PAGE 6: LOGS
  Full-screen live log stream with level filter, platform filter, pause/auto-scroll toggle, download button, and a gallery of recent error screenshots from logs/.

# 8. CLI
- python main.py serve      -> starts the dashboard (default port 8000, bound to 127.0.0.1 only)
- python main.py run [--dry-run]
- python main.py stats

# 9. DELIVERABLES / ACCEPTANCE
1. All files above, complete and working.
2. Unit tests for cookie parsing, filters, caps/dedupe logic, and LLM JSON parsing (LLM mocked).
3. A mock/fixture mode so the dashboard can be demoed with fake jobs without touching any real site.
4. README: install, `playwright install chromium`, how to export cookies, how to get a free NVIDIA/OpenRouter key, how to start the dashboard, how to do a dry-run, then a live run.
5. Finish by running: pytest, `python main.py serve` (confirm all 6 pages load without errors), and `python main.py run --dry-run` in mock mode. Fix everything before reporting done.