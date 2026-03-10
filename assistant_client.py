from __future__ import annotations

import asyncio
import html
import logging
import time
from typing import Dict, List, Optional, Set, Tuple

from openai import OpenAIError

logger = logging.getLogger(__name__)


def _resolve_file_name(client, file_id: Optional[str]) -> str:
    if not file_id:
        return "Reference"
    try:
        file_info = client.files.retrieve(file_id)
        return file_info.filename or f"File ID {file_id}"
    except Exception:
        return f"File ID {file_id}"


def _format_citations(client, annotation: Dict[str, any]) -> str:
    citation = annotation.get("file_citation", {})
    file_id = citation.get("file_id")
    quote = citation.get("quote", "")
    filename = _resolve_file_name(client, file_id)
    filename_safe = html.escape(str(filename))
    quote_safe = html.escape(quote)
    return filename_safe + (f' ("{quote_safe}")' if quote_safe else "")


def _extract_answer_from_message(client, message) -> Tuple[str, str]:
    if not message:
        return "[No answer returned]", ""
    message_dict = message.model_dump()
    parts: List[str] = []
    citations: Set[str] = set()
    for item in message_dict.get("content", []):
        if item.get("type") != "text":
            continue
        text_payload = item.get("text") or {}
        text_value = text_payload.get("value")
        if text_value:
            parts.append(text_value)
        for ann in text_payload.get("annotations") or []:
            if ann.get("type") == "file_citation":
                citations.add(_format_citations(client, ann))
    answer_text = "\n\n".join(parts).strip() or "[No answer returned]"
    citations_html = ""
    if citations:
        citations_html = "<h4>References:</h4><ul>" + "".join(f"<li>{c}</li>" for c in sorted(citations)) + "</ul>"
    return answer_text, citations_html


async def _wait_for_available_thread(client, thread_id: str, *, max_checks: int = 5, interval: float = 1.0) -> None:
    try:
        for _ in range(max_checks):
            runs = await asyncio.to_thread(client.beta.threads.runs.list, thread_id=thread_id, limit=1)
            data = runs.data or []
            if not data:
                return
            status = data[0].status
            if status not in {"queued", "in_progress"}:
                return
            await asyncio.sleep(interval)
    except Exception:
        logger.warning("Failed to check thread run status; proceeding anyway.")


async def run_assistant_request(
    client,
    assistant_id: str,
    user_content: List[Dict[str, str]],
    existing_thread_id: Optional[str],
    *,
    timeout: int = 60,
    poll_interval: float = 2.0,
) -> Tuple[str, str, str]:
    try:
        if existing_thread_id:
            thread_id = existing_thread_id
            await _wait_for_available_thread(client, thread_id)
            await asyncio.to_thread(
                client.beta.threads.messages.create,
                thread_id=thread_id,
                role="user",
                content=user_content,
            )
        else:
            thread = await asyncio.to_thread(
                client.beta.threads.create,
                messages=[{"role": "user", "content": user_content}],
            )
            thread_id = thread.id

        run = await asyncio.to_thread(
            client.beta.threads.runs.create,
            thread_id=thread_id,
            assistant_id=assistant_id,
        )

        start_time = time.time()
        while True:
            run_status = await asyncio.to_thread(
                client.beta.threads.runs.retrieve,
                thread_id=thread_id,
                run_id=run.id,
            )
            if run_status.status == "completed":
                break
            if run_status.status in {"failed", "cancelled", "expired"}:
                raise RuntimeError(f"Assistant run {run_status.status}")
            if time.time() - start_time > timeout:
                raise TimeoutError("Assistant response timeout.")
            await asyncio.sleep(poll_interval)

        messages = await asyncio.to_thread(client.beta.threads.messages.list, thread_id=thread_id)
        msgs_sorted = sorted(messages.data, key=lambda m: m.created_at)
        answer_msg = next((m for m in reversed(msgs_sorted) if m.role == "assistant"), None)
        answer_text, citations_html = await asyncio.to_thread(_extract_answer_from_message, client, answer_msg)
        return thread_id, answer_text, citations_html
    except OpenAIError:
        raise
    except Exception as exc:
        logger.error("Assistant workflow failure: %s", exc, exc_info=True)
        raise RuntimeError("Assistant workflow failure") from exc
