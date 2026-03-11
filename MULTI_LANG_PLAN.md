# RegAdam Multilingual Plan
- [x] Move the actuator tree + error table into `data/private/` (ignored by git), expose their paths via env vars (`ERROR_DB_PATH`, `ACTUATOR_TREE_PATH`), and load them with pandas so lookups are deterministic.
- [ ] Load EN/SK/RU assistant + vector store IDs from `.env` (plus `PARSER_MODEL`) and build a validated `LANGUAGE_CONFIG` map with fallbacks.
- [ ] Add a language selector (default English, options Slovak + Russian) to the landing form and ensure every follow-up form preserves `lang`.
- [ ] Localize all visible strings (landing page, conversation view, feedback/escalation copy) via a `TRANSLATIONS` dict keyed by language.
- [ ] Implement Stage 1 parser (Responses API + JSON schema) and routing logic before Stage 2.
- [ ] Route OpenAI Stage 2 calls through the per-language assistant/vector store IDs, injecting parser JSON + CSV lookups, and enforce the workflow.
- [ ] Extend the regression tests to cover: selector rendering, invalid-language fallback, parser normalization, and assistant selection.
- [ ] Document the new `.env` variables and usage notes in `AGENTS.md` or a README section for deployment.
