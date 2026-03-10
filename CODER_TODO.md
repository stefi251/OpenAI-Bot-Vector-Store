# Client Adaptation TODOs

1. **Secure Metrics & Admin Endpoints**
   - Add authentication/authorization around `/stats`, `/feedback`, `/escalate`, and `/health`.
   - Decide on OAuth, session cookies, or API keys appropriate for the client deployment.

2. **Harden Data Storage**
   - Replace flat CSV logging with a managed datastore (database or secure object store).
   - Implement retention/rotation and redact PII before persistence.

3. **Reintroduce File Uploads Safely**
   - If uploads are required, add MIME/type sniffing, double-extension guards, and malware scanning.
   - Store uploads in isolated storage; never feed raw user files directly to OpenAI.

4. **Environment Configuration**
   - Move `REGADAM_ID` and `VECTOR_STORE_ID` to environment variables; document required values per environment.
   - Review `.env` handling and secrets rotation policies.

5. **Frontend Refactor**
   - Consider migrating inline HTML responses to Jinja2 templates for maintainability.
   - Apply shared styling consistent with the client brand.

6. **Rate Limiting & Monitoring**
   - Introduce per-user/IP rate limits to avoid abuse of OpenAI resources.
   - Add structured logging/metrics for observability.

7. **OpenAI Efficiency**
   - Switch Stage 2 to streaming or a slower poll cadence to cut the 10+ GET requests currently required per response.
   - Block new `/ask` submissions on a thread while a run is still “queued/in_progress” (guard added in code, but keep monitoring for edge cases).

8. **Manual Actuator Guidance**
   - Ensure Slovak/Russian assistants have the SK/RU manuals ingested (e.g., SPO_280_SK) and explicitly search them for LED patterns when no error code exists.
   - Update prompts to mention LED diagnostics for manual actuators so Stage 2 doesn’t return the generic “not found” response.

9. **Conversation UX**
   - Improve history labels to show “Prefix 382” / “Error E17” rather than raw snippets, and surface short confirmation messages so users see context instead of one-letter entries.
