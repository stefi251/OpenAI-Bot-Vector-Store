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

7. **OpenAI Efficiency**
   - Switch Stage 2 to streaming or a slower poll cadence to cut the 10+ GET requests currently required per response.
   - Block new `/ask` submissions on a thread while a run is still “queued/in_progress” (guard added in code, but keep monitoring for edge cases).

8. **Manual Actuator Guidance**
   - Ensure Slovak/Russian assistants have the SK/RU manuals ingested (e.g., SPO_280_SK) and explicitly search them for LED patterns when no error code exists.
   - Update prompts to mention LED diagnostics for manual actuators so Stage 2 doesn’t return the generic “not found” response.

9. **Conversation UX**
   - Improve history labels to show “Prefix 382” / “Error E17” rather than raw snippets, and surface short confirmation messages so users see context instead of one-letter entries.
