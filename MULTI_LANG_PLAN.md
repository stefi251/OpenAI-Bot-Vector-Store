# RegAdam Multilingual Plan
- [x] Move the actuator tree + error table into `data/private/` (ignored by git), expose their paths via env vars (`ERROR_DB_PATH`, `ACTUATOR_TREE_PATH`), and load them with pandas so lookups are deterministic.
- [x] Load EN/SK/RU assistant + vector store IDs from `.env` and route each language to its own assistant.
- [x] Add a language selector (default English, options Slovak + Russian) to the landing form; every follow-up form preserves `lang`.
- [x] Localize all visible strings (landing page, conversation view, feedback/escalation copy) via a `TRANSLATIONS` dict keyed by language.
- [x] Route OpenAI calls through the per-language assistant/vector store IDs, injecting parser JSON + CSV lookups.
- [x] Document the `.env` variables and deployment notes in `AGENTS.md` and `SETUP.md`.
- [ ] Implement Stage 1 parser (Responses API + JSON schema) for structured actuator/error extraction before Stage 2 assistant call.
- [ ] Extend the regression tests to cover: selector rendering, invalid-language fallback, parser normalization, and assistant selection.

## Platform Notes (March 2026)
- File Search **must be enabled** on all three assistants in OpenAI Platform — it is a toggle in assistant settings.
- SK and RU assistants were found with File Search disabled; re-enabled manually.
- The deprecated `gpt-4-0613` model was replaced with a current supported model on SK and RU assistants.
