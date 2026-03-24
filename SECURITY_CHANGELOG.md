# Security Hardening Changelog

Applied March 2026. All changes are in `main.py` unless noted.

---

## Step 1 — Critical & Trivial Fixes

### C1 — Real client IP for rate limiting
**Before:** Rate limit used `request.client.host`, which is always `127.0.0.1` behind Nginx.
**After:** Reads `X-Real-IP` header (set by Nginx), falls back to `X-Forwarded-For`, then `request.client.host`. Applied to `/ask` and `/feedback`.
**Why it matters:** Without this, all users shared one rate-limit bucket — one user could exhaust it for everyone, and a single attacker could never be blocked.

### M1 — Escalation double-escape removed
**Before:** `mailto:` body was run through `html.escape()` before `urllib.parse.quote()`, producing corrupt `%26amp%3B` sequences in the email subject.
**After:** Removed the `html.escape()` call; only `urllib.parse.quote()` is used.

### M5 — Feedback rating validation
**Before:** Any integer could be submitted as a rating.
**After:** Returns HTTP 422 if rating is not exactly `1` or `-1`.

### L1 — Health endpoint error detail removed
**Before:** `/health` returned exception text in the response body on failure.
**After:** Returns only `{"status": "unhealthy"}`. Exception is logged server-side only.

### L2 — Dev server hardened
**Before:** `__main__` block bound to `0.0.0.0` with `reload=True`.
**After:** Binds to `127.0.0.1` only; `reload=False`. Uvicorn is never exposed directly to the internet.

---

## Between Steps — Escalation History Fix

**Problem:** Russian (and other) conversations showed only 1 turn in the escalation email when the conversation started before a thread was created (the prefix/error identification phase).

**Root cause:** Pre-thread turns were logged to CSV with an empty `thread_id`. The history lookup by `thread_id` missed them. The `history_blob` was not being passed through the continue-conversation form, so it was lost after the first round-trip.

**Fix:**
- `history_blob` is now carried as a hidden form field through every continue-conversation page
- When `thread_id` is empty at escalation time, the blob is decoded to reconstruct pre-thread history
- Escalation uses whichever source (CSV or blob) has more entries

---

## Step 2 — Low-Effort Fixes

### L3 — Log rotation
**Before:** `logging.basicConfig()` wrote to stdout only; no file rotation.
**After:** `RotatingFileHandler('regadam.log', maxBytes=10MB, backupCount=5)` — log survives service restarts, disk usage is bounded.

### H2 — Rate limit memory cleanup
**Before:** Rate-limit buckets for each IP accumulated indefinitely in memory.
**After:** Stale buckets (all timestamps older than the window) are removed after each request.

### H1+C3 — CSRF token hardening
**Before:** CSRF tokens were not pruned; old tokens accumulated in memory.
**After:**
- `_generate_csrf_token()` prunes all expired tokens on every write
- `_validate_csrf_token()` uses `pop()` — tokens are **single-use** and destroyed on first validation
- Tokens expire after 10 minutes

### M2 — Security response headers
**Before:** No security headers beyond CORS.
**After:** `SecurityHeadersMiddleware` adds:
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Permissions-Policy: geolocation=(), microphone=(), camera=()`
- `Content-Security-Policy` (see AGENTS.md for details)

### M4 — Escalation rate limiting
**Before:** `/escalate` had no rate limiting.
**After:** Rate-limited at 5 requests / 60 s per IP (same as `/feedback`).

### H3 — Debug endpoints protected
**Before:** `/debug/error/{code}` and `/debug/actuator/{prefix}` were publicly accessible.
**After:** Require `X-Admin-Stats-Key` header — same key as `/stats`.

---

## Step 3 — Medium-Effort Fixes

### H4 — Thread ID validation
**Before:** `thread_id` from the form was passed directly to OpenAI API with no validation.
**After:** `_is_valid_thread_id()` validates against regex `^thread_[A-Za-z0-9]{10,}$`. Invalid values are logged as warnings and discarded (treated as a new conversation).
**Why it matters:** Prevents an attacker from injecting arbitrary strings into OpenAI API calls.

### C2 — Conversation history blob signing
**Before:** `history_blob` was plain base64-encoded JSON; a client could forge or tamper with conversation history.
**After:**
- On generation: `_sign_blob(blob)` prepends an HMAC-SHA256 signature using `BLOB_HMAC_SECRET`
- On receipt: `_verify_blob(signed)` verifies the signature using `hmac.compare_digest()`; tampered blobs are rejected and logged
- Requires `BLOB_HMAC_SECRET` in `.env`

### M3 — CSV field truncation
**Before:** Full question and answer text was written to CSV — unlimited length, potential for large log files and privacy exposure.
**After:** Question and answer are truncated to 500 characters before appending to CSV.

---

## Post-Step 3 Bug Fixes

### CSP inline script regression
**Problem:** After adding CSP headers, feedback thumbs-up/thumbs-down buttons stopped working in all languages.
**Root cause:** CSP `script-src 'self'` blocked the inline `<script>` block and `onclick=` handlers in the response page.
**Fix:** Added `'unsafe-inline'` to `script-src`. Note: this is a pragmatic trade-off. The full mitigation (external JS with CSP nonces) requires migrating the UI to Jinja2 templates — tracked in CODER_TODO.md.

### CSRF token conflict (escalation dead after feedback fix)
**Problem:** After fixing feedback buttons, the escalation form stopped working. Only one of the three actions (feedback, continue, escalate) worked per page load.
**Root cause:** The response page used a single `page_csrf_token` shared across all three forms. Because tokens are single-use, the first action consumed the token, leaving the other two with an invalid token.
**Fix:** The response page now generates three independent tokens: `csrf_feedback`, `csrf_continue`, `csrf_escalate`. Each action has its own token and they do not interfere with each other.

---

## New `.env` Variables Required

| Variable | Purpose | How to generate |
|---|---|---|
| `ADMIN_STATS_KEY` | Protects `/stats`, `/health`, `/debug/*` | `python3 -c "import secrets; print(secrets.token_hex(32))"` |
| `BLOB_HMAC_SECRET` | Signs conversation history blob | `python3 -c "import secrets; print(secrets.token_hex(32))"` |

Both must be set before starting the service. If `BLOB_HMAC_SECRET` is empty, blob signing is skipped (insecure — only acceptable for local development).
