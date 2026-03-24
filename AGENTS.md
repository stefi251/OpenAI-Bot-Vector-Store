# Repository Guidelines

## Project Structure & Module Organization

The FastAPI backend lives in `main.py`. Supporting modules:

| File | Purpose |
|---|---|
| `main.py` | FastAPI app — all routes, HTML rendering, CSRF, rate limiting, security headers |
| `assistant_client.py` | OpenAI Assistants API wrapper (threads, runs, polling, citations) |
| `data_loader.py` | Deterministic lookups from private CSV/JSON data files |
| `data/private/` | Private data files — not in Git; provided separately as a zip archive |
| `.env` | Secrets and configuration — never commit |
| `chat_metrics.csv` | Appended chat log (question, answer, language, timestamp) |
| `feedback_metrics.csv` | Feedback log (rating, thread_id, timestamp) |
| `regadam.log` | Rotating application log (10 MB × 5 files) |

Experimental variants (`main2.py`, `main3_f.py`, `main4.py`) are kept for reference only — do not deploy them.

---

## Environment Variables

All configuration is via `.env`. Required:

```
OPENAI_API_KEY
ASSISTANT_ID_EN, ASSISTANT_ID_SK, ASSISTANT_ID_RU
VECTOR_STORE_ID, VECTOR_STORE_ID_EN, VECTOR_STORE_ID_SK, VECTOR_STORE_ID_RU
MASTER_ACTUATOR_TREE_PATH
ERROR_DB_PATH
ALLOWED_ORIGINS
```

Security keys (required in production — see SETUP.md for generation):

```
ADMIN_STATS_KEY        # protects /stats, /health, /debug/* endpoints
BLOB_HMAC_SECRET       # signs the conversation history_blob
```

---

## Build, Test, and Development Commands

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --host 127.0.0.1 --port 8000
```

> Do not use `--reload` in production. The `__main__` block already sets `host="127.0.0.1"` and `reload=False`.

Syntax check before committing:
```bash
python3 -c "import ast; ast.parse(open('main.py').read()); print('OK')"
```

---

## Coding Style & Naming Conventions

- PEP 8: 4-space indentation, `snake_case` for functions, `PascalCase` for Pydantic/FastAPI models
- Environment variable constants in `UPPER_SNAKE_CASE`
- Keep handler functions lean; push helpers into separate `utils_*.py` files if they grow
- Prefer `black` (line length 88) and `ruff` for linting before opening a pull request

---

## HTML Touchpoints & Customisation Map

All user-facing markup lives in `main.py`. Key sections:

| Feature | Location | Notes |
|---|---|---|
| Landing form | `html_form()` | Language selector, question input |
| Ask response view | `ask()` return block | History, reply, feedback buttons, continue/escalate forms. Each form gets its own CSRF token. |
| Escalation confirmation | `escalate()` return block | Sanitized transcript for handoff |
| Analytics dashboard | `stats()` return block | Server-rendered; requires X-Admin-Stats-Key |

**Escaping rules:**
- User-provided text rendered in HTML: always pass through `html.escape()`
- User-provided text in `mailto:` links: always `urllib.parse.quote()`
- Do not remove these — they are the primary XSS and injection defences

**CSRF tokens:**
- Each response page generates **three separate single-use tokens**: `csrf_feedback`, `csrf_continue`, `csrf_escalate`
- Do not merge them into one token — the tokens are consumed on use, and all three actions may be available on the same page

**Content Security Policy:**
- CSP is applied via `SecurityHeadersMiddleware`
- `script-src` includes `'unsafe-inline'` because the response page uses inline `<script>` blocks and `onclick=` handlers
- If migrating to Jinja2 templates with external JS files, remove `'unsafe-inline'` and use nonces instead

---

## Security Architecture

| Layer | Implementation |
|---|---|
| CORS | `CORSMiddleware` with `ALLOWED_ORIGINS` allowlist |
| Rate limiting | In-memory per real client IP (X-Real-IP header from Nginx); 10/60s on `/ask`, 5/60s on `/feedback` and `/escalate` |
| CSRF | Single-use tokens; prune-on-write; 10-minute expiry |
| Conversation history integrity | HMAC-SHA256 (`_sign_blob` / `_verify_blob`); uses `BLOB_HMAC_SECRET` |
| Thread ID validation | `_is_valid_thread_id()` — regex `^thread_[A-Za-z0-9]{10,}$` |
| Admin guard | `X-Admin-Stats-Key` header on `/stats`, `/health`, `/debug/*` |
| Security headers | `SecurityHeadersMiddleware` — X-Content-Type-Options, X-Frame-Options, Referrer-Policy, Permissions-Policy, CSP |
| Log rotation | `RotatingFileHandler` — 10 MB per file, 5 files kept |
| CSV safety | Question and answer truncated to 500 chars before appending |
| Feedback validation | Rating accepted only as `1` or `-1`; others return HTTP 422 |
| Error exposure | `/health` returns only `{"status": "unhealthy"}` — no exception detail |

---

## Testing Guidelines

Adopt `pytest` and place tests under `tests/` mirroring the module path (e.g., `tests/test_main.py`). Name async tests `test_<feature>__<scenario>()`. Priority coverage targets:

- Rate limit enforcement (expect 429 after threshold)
- CSRF token lifecycle (single-use, expiry at 10 min)
- Admin guard on `/stats` and `/debug/*` (expect 403 without key)
- Escalation history reconstruction (blob vs CSV preference logic)
- OpenAI error handling (`OpenAIError` propagation, timeout)
- `data_loader.py` — error code normalization, actuator prefix matching

Use fixtures for OpenAI stubs to avoid live API calls in CI.

---

## Commit & Pull Request Guidelines

- Imperative mood, ≤72-character subject (e.g., `fix: restore feedback buttons broken by CSP`)
- Group related changes; document cross-file impacts in the commit body
- Pull requests must include: short summary, test results (syntax check + smoke run), screenshots for UI changes
- Never commit `.env`, `chat_metrics.csv`, `feedback_metrics.csv`, or any file under `data/private/`

---

## OpenAI Platform Configuration Notes

Each language (EN, SK, RU) has its own assistant in OpenAI Platform:

- **File Search must be enabled** on every assistant — it is a toggle in the assistant settings. If disabled, the assistant answers from model memory only and ignores uploaded manuals.
- The shared vector store contains all manuals (EN, SK, RU). All three assistants are configured to use it.
- Model: use a current supported model. `gpt-4-0613` is deprecated (sunset August 2025) — use `gpt-4o` or `gpt-4-turbo`.
- Set a monthly spend cap in the OpenAI dashboard to prevent runaway token costs.
