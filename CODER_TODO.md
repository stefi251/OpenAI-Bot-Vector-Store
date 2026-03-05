# Client Adaptation TODOs

## Critical

1. **Protect sensitive endpoints**
   - Require authentication/authorization for `/feedback`, `/escalate`, and `/health`.
   - Keep `/stats` behind `X-Admin-Stats-Key` (already implemented) and document key rotation.
   - If browser sessions/cookies are added later, enforce CSRF protection on POST routes.

## High

2. **Harden conversation lifecycle**
   - Add TTL cleanup for `conversation_state` to prevent unbounded in-memory growth.
   - Use shared state (Redis/database) if running multiple workers or requiring restart resilience.

3. **Harden data storage and privacy**
   - Replace CSV files (`chat_metrics.csv`, `feedback_metrics.csv`) with managed storage and access control.
   - Add retention/rotation and redact or hash PII before persistence/export.

4. **Escalation flow safety**
   - Keep escalation `mailto:` body URL-encoded before embedding user-derived text.
   - Add practical payload limits to avoid oversized `mailto:` links and client truncation.

## Medium

5. **Configuration consistency**
   - Standardize required env vars (`OPENAI_API_KEY`, `VECTOR_STORE_ID`, `ALLOWED_ORIGINS`, optional `ADMIN_STATS_KEY`).
   - Document secure production defaults (strict CORS allowlist, hardened rate limits, reCAPTCHA where needed).

6. **Frontend maintainability**
   - Migrate large inline HTML blocks from `main.py` to Jinja2 templates if UI complexity grows.
   - Keep explicit escaping rules for user-provided values in templates and JS sinks.

7. **Testing and observability**
   - Add `pytest` coverage for rate limits, stats auth guard, escalation flow, and OpenAI error handling.
   - Add structured logging and alert thresholds for 429/5xx spikes.
