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

