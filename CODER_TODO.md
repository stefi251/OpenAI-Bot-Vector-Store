# Client Adaptation TODOs

Items marked ✅ were completed during the March 2026 security hardening sprint.

---

## Critical

1. ✅ **Protect sensitive endpoints**
   - `/stats`, `/health`, `/debug/error/{code}`, and `/debug/actuator/{prefix}` all require `X-Admin-Stats-Key` header.
   - `/feedback` and `/escalate` are rate-limited (5 requests / 60 s per IP).
   - CSRF tokens are required on all POST routes; tokens are single-use and expire after 10 minutes.
   - Document key rotation procedure — see SETUP.md.

---

## High

2. ✅ **Harden conversation lifecycle**
   - Rate-limit buckets are cleaned up after each request to prevent unbounded memory growth.
   - CSRF token store is pruned on every write; expired entries are removed automatically.
   - **Still open:** Use shared state (Redis/database) if running multiple Uvicorn workers or requiring restart resilience. Currently, in-memory state is lost on restart — acceptable for a single-worker deployment.

3. ✅ **Harden data storage and privacy**
   - Chat log entries (`chat_metrics.csv`, `feedback_metrics.csv`) are truncated to 500 characters per field before writing.
   - **Still open:** Replace CSV files with managed storage and access control (database with proper retention policy).
   - **Still open:** Hash or redact PII before persistence/export if compliance requires it.

4. ✅ **Escalation flow safety**
   - `mailto:` body is URL-encoded before embedding user-derived text.
   - Conversation history size is bounded by CSV truncation (500 chars/field).
   - CSRF and rate limiting applied to `/escalate`.

---

## Medium

5. ✅ **Configuration consistency**
   - Required env vars: `OPENAI_API_KEY`, `ASSISTANT_ID_EN/SK/RU`, `VECTOR_STORE_ID*`, `MASTER_ACTUATOR_TREE_PATH`, `ERROR_DB_PATH`, `ALLOWED_ORIGINS`
   - New security env vars: `ADMIN_STATS_KEY` (protects admin endpoints), `BLOB_HMAC_SECRET` (signs conversation history blob)
   - See SETUP.md for full `.env` template and key generation instructions.

6. **Frontend maintainability**
   - Large inline HTML blocks remain in `main.py`.
   - Migrate to Jinja2 templates under `templates/` if UI complexity grows.
   - Current inline escaping is correct — keep `html.escape()` calls in place when refactoring.

7. **Testing and observability**
   - No automated tests yet. Add `pytest` coverage for:
     - Rate limits (expect 429 after threshold)
     - CSRF token lifecycle (single-use, expiry)
     - Stats auth guard (expect 403 without correct key)
     - Escalation flow (history reconstruction from blob)
     - OpenAI error handling (network failure, timeout)
   - Add structured logging and alert thresholds for 429/5xx spikes.
   - Log file rotates at 10 MB, keeps 5 files — monitor disk usage on VPS.

---

## Security Architecture Summary (as of March 2026)

| Layer | Mechanism |
|---|---|
| CORS | `ALLOWED_ORIGINS` env var; strict allowlist |
| Rate limiting | Per real client IP (X-Real-IP from Nginx); 10/60s on `/ask`, 5/60s on `/feedback` and `/escalate` |
| CSRF | Single-use token per action (feedback, continue, escalate); expires in 10 min |
| Conversation history integrity | HMAC-SHA256 signed `history_blob` (BLOB_HMAC_SECRET); tampered blobs are rejected |
| Thread ID validation | Regex `^thread_[A-Za-z0-9]{10,}$`; invalid values are discarded |
| Admin endpoints | `X-Admin-Stats-Key` header required |
| Response headers | X-Content-Type-Options, X-Frame-Options, Referrer-Policy, Permissions-Policy, CSP |
| Log management | RotatingFileHandler (10 MB × 5 files) |
| CSV data safety | Fields truncated to 500 chars before write |
| Input visibility | Feedback rating validated to {1, -1} only |
| Error detail | `/health` returns only `{"status": "unhealthy"}` — no stack traces exposed |
| Dev server | Binds to 127.0.0.1 only; `reload=False` |
