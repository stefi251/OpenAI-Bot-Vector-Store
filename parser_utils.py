from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

PARSER_SYSTEM_PROMPT = (
    "You are a deterministic diagnostic parser for an industrial actuator support system.\n"
    "Your ONLY task is to emit a single JSON object with every required key listed below.\n"
    "If a field is unknown, set its value to null. Never omit keys and never return an empty object.\n"
    "Extract:\n"
    "- actuator_number_prefix\n"
    "- actuator_model\n"
    "- error_code\n"
    "- led_pattern\n"
    "- symptoms\n"
    "- user_question\n"
    "- language\n"
    "Rules:\n"
    "• actuator_number_prefix = digits from the actuator nameplate; strip spaces and non-digits.\n"
    "• error_code = numeric portion of error identifiers (remove E/e and leading zeros).\n"
    "• If data is not supplied, output null for that key.\n"
    "• Do not invent or rephrase user text; user_question must echo the user request verbatim (trimmed).\n"
    "• If multiple values exist, pick the most explicit.\n"
    "Output strictly in JSON with those keys."
)


class ParserDataError(RuntimeError):
    """Raised when the diagnostic parser response is unusable."""


def _parse_json_blob(blob: str) -> Optional[Dict[str, Any]]:
    if not blob:
        return None
    candidate = blob.strip()
    for fence in ("```json", "```"):
        if candidate.startswith(fence):
            candidate = candidate[len(fence) :].strip()
    if candidate.endswith("```"):
        candidate = candidate[:-3].strip()
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        return None


def _get_field(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _extract_json_from_response(response) -> Dict[str, Any]:
    payload = response.model_dump()
    for item in _get_field(payload, "output", []):
        contents = _get_field(item, "content", [])
        for content in contents:
            if isinstance(content, dict) and "json" in content:
                return content["json"]
            text_payload = _get_field(content, "text")
            text_value = ""
            if isinstance(text_payload, dict):
                text_value = text_payload.get("value", "")
            elif isinstance(text_payload, str):
                text_value = text_payload
            if not text_value:
                candidate = _get_field(content, "value")
                if isinstance(candidate, str):
                    text_value = candidate
            if text_value:
                parsed = _parse_json_blob(text_value)
                if parsed:
                    return parsed
    output_text = getattr(response, "output_text", None)
    if output_text:
        output_candidates = [output_text] if isinstance(output_text, str) else output_text
        for text_value in output_candidates:
            parsed = _parse_json_blob(text_value)
            if parsed:
                return parsed
    logger.error("Parser raw payload: %s", payload)
    raise ParserDataError("Parser returned no usable JSON payload")


def _request_parser_payload(question: str, client, model: str) -> Dict[str, Any]:
    messages = [
        {"role": "system", "content": PARSER_SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]
    response = client.responses.create(
        model=model,
        input=messages,
    )
    raw = _extract_json_from_response(response)
    if not isinstance(raw, dict) or not raw:
        logger.warning("Parser returned empty payload for question: %s", question)
        raise ParserDataError("Parser returned empty payload")
    required_keys = {
        "actuator_number_prefix",
        "actuator_model",
        "error_code",
        "led_pattern",
        "symptoms",
        "user_question",
        "language",
    }
    missing_keys = [key for key in required_keys if key not in raw]
    if missing_keys:
        raise ParserDataError(f"Parser payload missing keys: {', '.join(missing_keys)}")
    return raw


def parse_diagnostics(question: str, client, model: str, *, attempts: int = 2) -> Dict[str, Any]:
    last_error: Optional[Exception] = None
    for attempt in range(attempts):
        try:
            return _request_parser_payload(question, client, model)
        except ParserDataError as exc:  # noqa: PERF203
            last_error = exc
            logger.warning("Parser attempt %s failed: %s", attempt + 1, exc)
            time.sleep(0.5)
    assert last_error is not None
    raise last_error
