# Repository Guidelines

## Project Structure & Module Organization
The FastAPI backend lives in `main.py`; `main2.py`, `main3_f.py`, and `main4.py` are experimental variants – corral new iterations in a dedicated submodule before promoting them to `main.py`. Uploaded chat logs are persisted in `chat_metrics.csv`. `.env` holds secrets such as `OPENAI_API_KEY`. The `mcp-server-demo/servers` workspace mirrors upstream Model Context Protocol servers (TypeScript); use it only for reference or to extend agent integrations, and keep archived variants in `mcp-servers-archived/`.

## Build, Test, and Development Commands
Create a virtual environment and install dependencies with `python -m venv .venv && source .venv/bin/activate` followed by `pip install fastapi uvicorn python-dotenv openai pandas`. Run the service locally with `uvicorn main:app --reload`. When hacking on the demo MCP servers, run `npm install` inside `mcp-server-demo/servers` and use `npm run build` to compile all workspaces.

## Coding Style & Naming Conventions
Adhere to PEP 8: 4-space indentation, snake_case for module-level functions, and PascalCase for FastAPI request models. Keep handler functions lean; push helpers into `utils_*.py` files if they grow. Use descriptive names like `validate_upload()` or `log_chat_metrics()` and keep environment variable constants in upper snake case (e.g., `REGADAM_ID`). Prefer `black` (line length 88) and `ruff` for linting before opening a pull request.

## HTML Touchpoints & Customisation Map
All user-facing markup lives in `main.py`. When adapting the UI, focus on these sections:

| Feature | Location | Notes |
| --- | --- | --- |
| Landing form | `main.py`, `html_form()` | Simple upload/question form; adjust styling in the returned HTML string. |
| Ask response view | `main.py`, `ask()` return block | Contains conversation history, assistant reply, feedback buttons, and embedded `<script>` for feedback POST. Escape helpers already applied—keep them in place when refactoring. |
| Escalation confirmation | `main.py`, `escalate()` return block | Displays the sanitized chat transcript for handoff. |
| Analytics dashboard | `main.py`, `stats()` return block | Server-rendered cards/table; update CSS or layout here. |

If the UI grows beyond simple templated strings, migrate these blocks to Jinja2 templates under a `templates/` directory and replace the inline HTML with `TemplateResponse` calls.

## Testing Guidelines
Adopt `pytest` and place tests under `tests/` mirroring the module path (e.g., `tests/test_main.py`). Name async tests `test_<feature>__<scenario>()` to highlight behavior. Use `pytest -k ask` to target the chat workflow and include fixtures for OpenAI stubs to avoid live API calls. Aim for coverage on file upload guardrails, OpenAI error handling, and escalation flow; add regression tests whenever logs capture a production failure.

## Commit & Pull Request Guidelines
Write commits in the imperative mood with ≤72-character subjects (e.g., `Add escalation summary email helper`). Group related Python, TypeScript, and config changes together, and document cross-language impacts in the body. Pull requests should include a short summary, explicit test results (`pytest`, `uvicorn` smoke run, or `npm run build` as applicable), and links to matching support tickets. Add screenshots or terminal captures for any UI or stats changes.

## Security & Configuration Tips
Never commit `.env` or `chat_metrics.csv`—they can contain customer data. Rotate API keys regularly and verify `REGADAM_ID` and `VECTOR_STORE_ID` before deploying. When sharing logs, scrub customer prompts and answers, and prefer read-only service keys in staging environments. Set `ALLOWED_ORIGINS` in the runtime environment (comma-separated) to lock CORS down to approved front-end hosts.
