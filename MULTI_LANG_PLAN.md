# RegAdam Multilingual Plan
- [ ] Load EN/SK/RU assistant + vector store IDs from `.env` and build a `LANGUAGE_CONFIG` map with validation/fallback logic.
- [ ] Add a language selector (default English, options Slovak + Russian) to the landing form and ensure every follow-up form preserves `lang`.
- [ ] Localize all visible strings (landing page, conversation view, feedback/escalation copy) via a `TRANSLATIONS` dict keyed by language.
- [ ] Route OpenAI calls through the per-language assistant/vector store IDs and prepend the correct language instruction to the system prompt.
- [ ] Extend the regression tests to cover: selector rendering, invalid-language fallback, and OpenAI payload selection for each language.
- [ ] Document the new `.env` variables and usage notes in `AGENTS.md` or a new README section for deployment.
