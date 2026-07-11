# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

Knowix (repo/legacy name "umimeanglicky") is a Czech-language Flask web app for playful English
practice: song-based vocabulary exercises, AI chat lessons, grammar games (hangman, wordle, pexeso,
"slovní fotbal"...), streaks/XP, and a teacher/admin layer. Production runs on Railway at knowix.cz.

## Running locally

- All app code lives under `anglictina/app/`, organized into `core/` (db, security),
  `services/` (streak, XP-adjacent helpers, caches), `routes/<area>/` (blueprints grouped by
  user/music/ai/grammar/games/math/misc) and `scripts/`. Modules still use flat imports
  (`from db import ...`, not package-qualified) — they resolve because `_paths.py` adds all
  those subdirectories to `sys.path`; every entry script imports `_paths` before any local
  import. Run via `python anglictina/app/main.py`; note `nepravidelna_slovesa.py` opens
  `verbs.json` relative to the CWD, so the safest CWD is `anglictina/app/`.
- Install deps: `pip install -r anglictina/app/requirements.txt`
- Config comes from `anglictina/app/.env` (gitignored — create it locally). `SECRET_KEY` is
  required; the app raises `RuntimeError` at import time without it. Other vars used across the
  codebase: `DB_HOST`/`DB_PORT`/`DB_USER`/`DB_PASS`/`DB_NAME` (MySQL), `REDIS_URL`,
  `GENIUS_ACCESS_TOKEN`, `DEEPL_API_KEY`, `AI_API_KEY`, `OPENAI_API_KEY`, `REMINDER_INTERVAL_SECS`,
  `START_WORKER_IN_WEB`, `FLASK_DEBUG`, `DISABLE_RATE_LIMIT`, `RATE_LIMIT_DEFAULTS`.
- Web app: `python anglictina/app/main.py` — runs the Flask dev server on port 9999 with
  `debug=True` hardcoded (no separate dev/prod entrypoint).
- Reminder worker: `python anglictina/app/worker_main.py`, or set `START_WORKER_IN_WEB=1` to run
  it as a daemon thread inside the web process instead of a separate process.
- Deployment (Railway) uses the **root** `Procfile` (`web: python -u anglictina/app/main.py`,
  `worker: python -u anglictina/app/worker_main.py`). There's a second `Procfile` inside
  `anglictina/app/` left over from an earlier deploy layout — don't assume it's the active one.

## Tests

There is no automated test suite (no pytest config, no CI wiring). What exists today:
- `tests/test.py` — a Locust load-test script, run via `locust -f tests/test.py`, not a unit test.
- `anglictina/app/scripts/test_freeze.py` — a manual CLI script for the streak-freeze feature
  (`python scripts/test_freeze.py <user_id>`), runs against a real DB and asserts for interactive
  debugging, not part of any suite.
After changing behavior, verify by running the app and exercising the route manually.

## Architecture

### Entry point and blueprint registration
`anglictina/app/main.py` is the only place things get wired together: it imports ~30 feature
modules, each exposing one `Blueprint`, and registers them via the `BLUEPRINTS` list on a single
`Flask(__name__)` app. The `routes/math/` blueprints are fully implemented but currently commented
out/disabled in main.py. When adding a feature, follow the existing pattern: a new module in the
matching `anglictina/app/routes/<area>/` folder exporting a `Blueprint`, imported in `main.py` and
added to `BLUEPRINTS`. (New route subfolders are picked up by `_paths.py` automatically.)

main.py also directly owns (not delegated to any module):
- **Session backend selection** — Redis when `REDIS_URL` is set and `FLASK_DEBUG` is not, filesystem
  (under `~/knowix_sessions`, deliberately outside OneDrive to dodge sync conflicts) otherwise.
- **Per-host cookie rules** in `before_request` — `*.knowix.cz` gets `Secure` + domain-scoped
  cookies, localhost/private LAN IPs (so the app can be tested from a phone on the same network)
  get relaxed cookie settings, and bare `knowix.cz` redirects to `www`.
- **Guest account bootstrap** — any request without `user_id` in session creates a row in `users`
  (`is_guest=1`) plus a linked row in `guest`, and stores the new `users.id` in session, so
  unauthenticated visitors get a fully working account transparently. Downstream features (XP,
  stats, streak) just key off `session['user_id']` and don't need to know it's a guest.
- **Security headers / CSP** in `after_request`, with a relaxed CSP carve-out specifically for the
  `vlastni_music_bp` blueprint (it embeds YouTube).
- A catch-all error handler returning JSON or `error.html` depending on `Accept`/path, logging full
  tracebacks either way.

### Database layer (`core/db.py`)
Dual-backend by design: MySQL in production via `mysql.connector`, with automatic fallback to a
local SQLite file (`anglictina/app/knowix_local.db`) if `DB_HOST` is unset or the MySQL connection
fails at startup — this is what makes local dev possible without a DB server.
- `_SQLiteCursor`/`_SQLiteConnection` wrap `sqlite3` to emulate the `mysql.connector` API
  (`cursor(dictionary=True)`, `%s` placeholders rewritten to `?`, `NOW()` → `CURRENT_TIMESTAMP`), so
  feature modules can write MySQL-style SQL without backend branches.
- `is_sqlite_mode()` is the sanctioned place to branch on backend; e.g. `_ensure_user_columns()` in
  main.py uses it to skip MySQL-only `ALTER TABLE` migrations since the SQLite schema is always
  created complete.
- The full SQLite schema lives in `_SQLITE_SCHEMA_STMTS` in db.py. When adding a column/table that
  must work on both backends, update both the MySQL `ALTER TABLE`/`CREATE TABLE` call site and this
  list (plus the ad-hoc migration block in `_ensure_sqlite_schema()`, for existing local DB files
  that predate the new column).

### AI integrations
Most AI features (`ai.py`, `AI_gramatika.py`, `AI_poslech.py`, `roleplaying.py`, etc.) call a single
external gateway, `https://api.aimlapi.com/v1/chat/completions`, using `AI_API_KEY`, picking a model
per call site (e.g. `mistralai/mistral-nemo`, `gpt-4o-mini`). `vlastni_music.py` is the exception —
it uses the OpenAI Python SDK directly with `OPENAI_API_KEY`. There's no shared AI client wrapper;
each module makes its own `requests.post` calls.

### Security (`core/security_ext.py`)
`init_security(app)` wires up Flask-Limiter (Redis-backed in prod, in-memory in dev or when
`DISABLE_RATE_LIMIT=1`) and a custom CSRF check on `before_request` for POST/PUT/PATCH/DELETE,
comparing a session-stored token against `csrf_token` in the form/JSON body or the `X-CSRFToken`
header. Endpoints whose blueprint name starts with anything in `EXEMPT_PREFIXES` (currently just
`vlastni_music_bp.`) skip both CSRF and rate limiting.

### Background worker
`worker_main.py` loops `reminders.send_daily_reminders()` (interval via `REMINDER_INTERVAL_SECS`,
default 900s) to send email/push reminders. It's a separate Railway process (`worker` in the root
Procfile) and is not started inside the web process unless `START_WORKER_IN_WEB=1`.

### Knowix_VR/
A separate, standalone Flask app (VR/music presentation) with its own templates/static — not
imported or registered by `anglictina/app/main.py`. Treat it as an independent mini-project.

## Conventions worth knowing
- Code, comments, and log messages are predominantly in Czech; match that in new code in this area
  unless told otherwise.
- Feature modules manage their own DB connection lifecycle inline
  (`conn = get_db_connection(); ...; conn.close()`, usually in a `finally`) rather than going
  through a shared pool or app-level teardown hook — follow that pattern rather than introducing one.
- Logging is a live mix of `print(...)` (often `[module_name] ...`-prefixed) and the `logging`
  module; both are in active use in main.py, so don't assume one has replaced the other.
