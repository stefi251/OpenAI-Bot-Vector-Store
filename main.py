from dotenv import load_dotenv
load_dotenv()
import asyncio
import csv
import html
import json
import os
import threading
import time
import uuid
from base64 import b64decode, b64encode
from collections import defaultdict, deque
from datetime import datetime
from typing import Deque, Dict, List, Optional, Set
from urllib.parse import quote

import httpx
from fastapi import FastAPI, Form, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
import logging
from openai import OpenAI, OpenAIError

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('regadam.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise RuntimeError("Please set OPENAI_API_KEY (in your environment or a .env file)")

client = OpenAI()

REGADAM_MODEL = os.getenv("REGADAM_MODEL", "o4-mini")
SYSTEM_PROMPT = os.getenv(
    "REGADAM_SYSTEM_PROMPT",
    "Ste Regada Valve virtuálny technik. Odpovedajte po slovensky, buďte vecní "
    "a ak je to možné, opierajte sa o znalostnú bázu Regada Valve.",
)
VECTOR_STORE_ID = os.getenv("VECTOR_STORE_ID", "vs_ID")
RECAPTCHA_SITE_KEY = os.getenv("RECAPTCHA_SITE_KEY")
RECAPTCHA_SECRET_KEY = os.getenv("RECAPTCHA_SECRET_KEY")
ASK_RATE_LIMIT_MAX = int(os.getenv("ASK_RATE_LIMIT_MAX", "5"))
ASK_RATE_LIMIT_WINDOW = int(os.getenv("ASK_RATE_LIMIT_WINDOW", "10"))
FEEDBACK_RATE_LIMIT_MAX = int(os.getenv("FEEDBACK_RATE_LIMIT_MAX", "5"))
FEEDBACK_RATE_LIMIT_WINDOW = int(os.getenv("FEEDBACK_RATE_LIMIT_WINDOW", "60"))
LOG_FILE = "chat_metrics.csv"
FEEDBACK_LOG_FILE = "feedback_metrics.csv"

CSV_LOCK = threading.Lock()
conversation_state: Dict[str, Dict[str, Optional[str]]] = {}
conversation_lock = threading.Lock()
rate_limit_lock = threading.Lock()
rate_limit_data: Dict[str, Deque[float]] = defaultdict(deque)

if VECTOR_STORE_ID and VECTOR_STORE_ID not in {"vs_ID", ""}:
    try:
        client.vector_stores.retrieve(VECTOR_STORE_ID)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Unable to retrieve vector store {VECTOR_STORE_ID}: {exc}") from exc

app = FastAPI()

ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost,http://127.0.0.1").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in ALLOWED_ORIGINS if origin.strip()],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _sanitize_csv_value(value: Optional[str]) -> str:
    if value is None:
        return ""
    value = value.replace("\r", " ").replace("\n", " ").strip()
    if value.startswith(("=", "+", "-", "@")):
        return f"'{value}"
    return value


def _check_rate_limit(identifier: str, max_calls: int, window_seconds: int) -> bool:
    if max_calls <= 0 or window_seconds <= 0:
        return True
    now = time.time()
    with rate_limit_lock:
        bucket = rate_limit_data[identifier]
        while bucket and now - bucket[0] > window_seconds:
            bucket.popleft()
        if len(bucket) >= max_calls:
            return False
        bucket.append(now)
        return True


def _verify_recaptcha(token: Optional[str]) -> bool:
    if not RECAPTCHA_SECRET_KEY:
        return True
    if not token:
        return False
    try:
        response = httpx.post(
            "https://www.google.com/recaptcha/api/siteverify",
            data={"secret": RECAPTCHA_SECRET_KEY, "response": token},
            timeout=5,
        )
        response.raise_for_status()
        payload = response.json()
        return payload.get("success", False)
    except Exception as exc:  # noqa: BLE001
        logger.error(f"reCAPTCHA verification failed: {exc}")
        return False


def _iter_chat_rows() -> List[Dict[str, str]]:
    if not os.path.exists(LOG_FILE):
        return []
    rows: List[Dict[str, str]] = []
    try:
        with open(LOG_FILE, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            use_dict = reader.fieldnames and "thread_id" in reader.fieldnames
            if use_dict:
                for row in reader:
                    rows.append(
                        {
                            "datetime": row.get("datetime", ""),
                            "thread_id": row.get("thread_id", ""),
                            "question": row.get("question", ""),
                            "answer": row.get("answer", ""),
                        }
                    )
            else:
                f.seek(0)
                raw_reader = csv.reader(f)
                for raw in raw_reader:
                    if len(raw) < 4:
                        continue
                    rows.append(
                        {
                            "datetime": raw[0],
                            "thread_id": raw[1],
                            "question": raw[2],
                            "answer": raw[3],
                        }
                    )
    except Exception as exc:
        logger.error(f"Failed to read chat log: {exc}")
    return rows


def _load_conversation_history(conversation_id: str) -> List[Dict[str, str]]:
    if not conversation_id:
        return []
    rows: List[Dict[str, str]] = []
    for entry in _iter_chat_rows():
        if entry.get("thread_id") == conversation_id:
            rows.append({"question": entry.get("question", ""), "answer": entry.get("answer", "")})
    return rows


def _render_chat_html(entries: List[Dict[str, str]]) -> str:
    fragments: List[str] = []
    for entry in entries:
        question = entry.get("question") or ""
        answer = entry.get("answer") or ""
        if question:
            fragments.append(f"<b>User:</b> {html.escape(question)}<br>")
        if answer:
            fragments.append(f"<b>Assistant:</b> {html.escape(answer)}<br>")
    return "".join(fragments)


def _contact_card_html() -> str:
    return """
    <div class="contact-card">
        <h3>Kontakt</h3>
        <p class="contact-greeting">Dobrý deň, volám sa Marko a som tu pre vás.</p>
        <div class="contact-name">Ing. Marko Štofan</div>
        <div class="contact-meta">+421 51 7480 462</div>
        <div class="contact-meta">servis@regada.sk</div>
        <a class="contact-button" target="_blank" rel="noopener" href="https://www.regada.sk/servis/sluzby-zakaznikom#kontakt">Viac o servise</a>
    </div>
    """

@app.get("/", response_class=HTMLResponse)
async def html_form():
    conversation_id = str(uuid.uuid4())
    with conversation_lock:
        conversation_state[conversation_id] = {"last_response_id": None}
    captcha_block = ""
    captcha_script = ""
    if RECAPTCHA_SITE_KEY:
        captcha_block = f'<div class=\"g-recaptcha\" data-sitekey=\"{RECAPTCHA_SITE_KEY}\"></div>'
        captcha_script = '<script src=\"https://www.google.com/recaptcha/api.js\" async defer></script>'
    contact_html = _contact_card_html()
    return HTMLResponse(
        f"""
    <html>
    <head>
        <meta charset=\"UTF-8\">
        <link rel=\"preconnect\" href=\"https://fonts.googleapis.com\">
        <link rel=\"preconnect\" href=\"https://fonts.gstatic.com\" crossorigin>
        <link href=\"https://fonts.googleapis.com/css2?family=Montserrat:wght@400;600;700&display=swap\" rel=\"stylesheet\">
        <style>
            body {{
                font-family: 'Montserrat', sans-serif;
                background:#f4f6f9;
                color:#1c2028;
                margin:0;
            }}
            .page-shell {{
                max-width:1100px;
                margin:0 auto;
                padding:50px 20px;
                display:flex;
                gap:24px;
                flex-wrap:wrap;
            }}
            .hero-card {{
                flex:1 1 600px;
                background:#fff;
                border-radius:12px;
                box-shadow:0 10px 30px rgba(15,66,118,0.08);
                padding:32px;
            }}
            .hero-card h2 {{
                color:#0e4da1;
                margin-top:0;
                margin-bottom:12px;
                font-weight:700;
            }}
            .hero-card p {{
                margin-top:0;
                color:#4b5563;
                line-height:1.6;
            }}
            .hero-card textarea {{
                width:100%;
                border:1px solid #dbe2ec;
                border-radius:8px;
                padding:14px;
                font-size:16px;
                font-family:'Montserrat', sans-serif;
                min-height:140px;
                resize:vertical;
                box-sizing:border-box;
                margin-bottom:16px;
            }}
            .primary-btn {{
                background:#0066cc;
                color:#fff;
                border:none;
                padding:12px 28px;
                border-radius:8px;
                font-size:16px;
                cursor:pointer;
                font-weight:600;
            }}
            .contact-panel {{
                flex:1 1 260px;
            }}
            .contact-card {{
                background:#e9eff7;
                border-radius:12px;
                padding:24px;
                box-shadow:0 10px 25px rgba(14,77,161,0.08);
            }}
            .contact-card h3 {{
                margin-top:0;
                color:#0e4da1;
            }}
            .contact-greeting {{
                margin:8px 0 14px;
                color:#24324c;
                line-height:1.4;
            }}
            .contact-name {{
                font-weight:600;
                color:#1c2028;
            }}
            .contact-meta {{
                color:#24324c;
                margin-bottom:4px;
            }}
            .contact-button {{
                display:inline-block;
                margin-top:12px;
                background:#0066cc;
                color:#fff;
                padding:10px 18px;
                border-radius:6px;
                text-decoration:none;
                font-weight:600;
            }}
            @media (max-width:768px) {{
                .page-shell {{
                    padding:30px 16px;
                }}
            }}
        </style>
        {captcha_script}
    </head>
    <body>
        <div class=\"page-shell\">
            <div class=\"hero-card\">
                <h2>Regada servis – AI asistent</h2>
                <p>Napíšte problém so servopohonom alebo ventilom a RegAdam vás prevedie ďalším postupom.</p>
                <form action=\"/ask\" method=\"post\">
                    <textarea name=\"question\" placeholder=\"Popíšte problém, napr. „motor hučí a svieti E17“\"></textarea>
                    <input type=\"hidden\" name=\"thread_id\" value=\"{conversation_id}\">
                    {captcha_block}
                    <button type=\"submit\" class=\"primary-btn\">Spustiť asistenta</button>
                </form>
            </div>
            <div class=\"contact-panel\">
                {contact_html}
            </div>
        </div>
    </body></html>
    """
    )

@app.post("/ask")
async def ask(
    request: Request,
    question: str = Form(...),
    thread_id: str = Form(None),
    captcha_token: Optional[str] = Form(None, alias="g-recaptcha-response"),
):  # noqa: PLR0912
    client_host = request.client.host if request.client else "unknown"
    if not _check_rate_limit(f"ask:{client_host}", ASK_RATE_LIMIT_MAX, ASK_RATE_LIMIT_WINDOW):
        return HTMLResponse(
            content="""
        <html><body style='padding:20px;font-family:sans-serif;'>
            <h3>Too Many Requests</h3>
            <p>Please wait a moment before sending another question.</p>
            <a href='/'>← Return Home</a>
        </body></html>
        """,
            status_code=429,
        )

    if RECAPTCHA_SECRET_KEY and not _verify_recaptcha(captcha_token):
        return HTMLResponse(
            content="""
        <html><body style='padding:20px;font-family:sans-serif;'>
            <h3>Captcha Verification Failed</h3>
            <p>Please complete the captcha before submitting.</p>
            <a href='/'>← Return Home</a>
        </body></html>
        """,
            status_code=400,
        )

    if question is None:
        return HTMLResponse(
            content=(
                "<html><body><h3>Error</h3><p>Question is required.</p>"
                "<a href='/'>Return</a></body></html>"
            ),
            status_code=400,
        )

    cleaned_question = question.strip()
    if not cleaned_question:
        logger.warning("Blank question submitted")
        return HTMLResponse(
            content=(
                "<html><body><h3>Error</h3><p>Please enter a question or code.</p>"
                "<a href='/'>Return</a></body></html>"
            ),
            status_code=400,
        )
    if len(cleaned_question) < 3 and not thread_id:
        logger.warning("Initial question too short submitted")
        return HTMLResponse(
            content=(
                "<html><body><h3>Error</h3><p>Please provide at least three "
                "characters for the first question.</p><a href='/'>Return</a></body></html>"
            ),
            status_code=400,
        )
    if len(cleaned_question) > 2000:
        logger.warning("Question too long submitted")
        return HTMLResponse(
            content=(
                "<html><body><h3>Error</h3><p>Please limit the question to "
                "2000 characters.</p><a href='/'>Return</a></body></html>"
            ),
            status_code=400,
        )

    conversation_id = (thread_id or "").strip()
    if not conversation_id:
        return HTMLResponse(
            content="""
        <html><body style='padding:20px;font-family:sans-serif;'>
            <h3>⚠️ Session Expired</h3>
            <p>Please start a new conversation.</p>
            <a href='/'>← Return Home</a>
        </body></html>
        """,
            status_code=400,
        )

    with conversation_lock:
        state = conversation_state.get(conversation_id)
    if state is None:
        return HTMLResponse(
            content="""
        <html><body style='padding:20px;font-family:sans-serif;'>
            <h3>⚠️ Unknown Conversation</h3>
            <p>The conversation ID is invalid or has expired. Please start a new chat.</p>
            <a href='/'>← Return Home</a>
        </body></html>
        """,
            status_code=400,
        )

    history_entries = _load_conversation_history(conversation_id)
    previous_response_id = state.get("last_response_id")

    def _create_response():
        request_kwargs = {
            "model": REGADAM_MODEL,
            "instructions": SYSTEM_PROMPT,
            "input": [{"role": "user", "content": cleaned_question}],
            "store": True,
        }
        if previous_response_id:
            request_kwargs["previous_response_id"] = previous_response_id
        if VECTOR_STORE_ID:
            request_kwargs["tools"] = [
                {
                    "type": "file_search",
                    "vector_store_ids": [VECTOR_STORE_ID],
                }
            ]
        return client.responses.create(**request_kwargs)

    try:
        response = await asyncio.to_thread(_create_response)
    except OpenAIError as exc:
        logger.error(f"OpenAI API error: {exc}")
        return HTMLResponse(
            content="""
        <html><body style='padding:20px;font-family:sans-serif;'>
            <h3>⚠️ Service Temporarily Unavailable</h3>
            <p>We're experiencing connectivity issues with our AI service.</p>
            <p>Please try again in a few moments or contact support.</p>
            <a href='/'>← Return Home</a>
        </body></html>
        """,
            status_code=503,
        )
    except Exception as exc:
        logger.error(f"Unexpected error creating response: {exc}")
        return HTMLResponse(
            content="""
        <html><body style='padding:20px;font-family:sans-serif;'>
            <h3>⚠️ System Error</h3>
            <p>An unexpected error occurred. Our team has been notified.</p>
            <a href='/'>← Return Home</a>
        </body></html>
        """,
            status_code=500,
        )

    response_id = getattr(response, "id", "")
    with conversation_lock:
        if conversation_id in conversation_state:
            conversation_state[conversation_id]["last_response_id"] = response_id or conversation_state[conversation_id].get("last_response_id")
    response_payload = response.model_dump()
    answer_parts: List[str] = []
    file_citations: Set[str] = set()

    for item in response_payload.get("output", []) or []:
        for content in item.get("content", []) or []:
            text_value = content.get("text")
            if text_value:
                answer_parts.append(text_value)
            for annotation in content.get("annotations") or []:
                if annotation.get("type") == "file_citation":
                    citation = annotation.get("file_citation", {})
                    file_id = citation.get("file_id")
                    quote_part = citation.get("quote") or ""
                    filename = f"File ID {file_id}" if file_id else "Reference"
                    if file_id:
                        try:
                            file_info = await asyncio.to_thread(
                                client.files.retrieve,
                                file_id,
                            )
                            filename = file_info.filename
                        except Exception:
                            filename = f"File ID {file_id}"
                    filename_safe = html.escape(str(filename))
                    quote_safe = html.escape(quote_part)
                    citation_text = (
                        f"{filename_safe}" + (f" (\"{quote_safe}\")" if quote_safe else "")
                    )
                    file_citations.add(citation_text)

    answer_text = "\n\n".join(answer_parts).strip() or "[No answer returned]"

    log_row = [
        datetime.now().isoformat(),
        _sanitize_csv_value(conversation_id),
        _sanitize_csv_value(cleaned_question),
        _sanitize_csv_value(answer_text),
    ]
    try:
        with CSV_LOCK:
            file_exists = os.path.exists(LOG_FILE)
            with open(LOG_FILE, "a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                if not file_exists:
                    writer.writerow(["datetime", "thread_id", "question", "answer"])
                writer.writerow(log_row)
    except Exception as exc:
        logger.error(f"Failed to log chat: {exc}")

    history_with_current = history_entries + [
        {"question": cleaned_question, "answer": answer_text}
    ]
    chat_html = _render_chat_html(history_with_current)

    citations_html = ""
    if file_citations:
        citations_html = "<h4>References:</h4><ul>" + "".join(
            f"<li>{c}</li>" for c in sorted(file_citations)
        ) + "</ul>"
    safe_question = html.escape(cleaned_question)
    safe_answer = html.escape(answer_text)
    safe_thread_id = html.escape(conversation_id)
    safe_citations = citations_html
    feedback_disabled_attr = "" if conversation_id else "disabled"
    history_blob = b64encode(json.dumps(history_with_current).encode("utf-8")).decode("ascii")
    captcha_block = ""
    captcha_script = ""
    if RECAPTCHA_SITE_KEY:
        captcha_block = f'<div class="g-recaptcha" data-sitekey="{RECAPTCHA_SITE_KEY}"></div>'
        captcha_script = '<script src="https://www.google.com/recaptcha/api.js" async defer></script>'
    contact_html = _contact_card_html()

    return HTMLResponse(content=f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Regada servis – AI asistent</title>
        <link rel="preconnect" href="https://fonts.googleapis.com">
        <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
        <link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@400;600;700&display=swap" rel="stylesheet">
        <style>
            body {{
                font-family:'Montserrat', sans-serif;
                background:#f4f6f9;
                margin:0;
                color:#1c2028;
            }}
            .page-shell {{
                max-width:1100px;
                margin:0 auto;
                padding:40px 20px 60px;
                display:flex;
                gap:24px;
                flex-wrap:wrap;
            }}
            .primary-column {{
                flex:1 1 680px;
                display:flex;
                flex-direction:column;
                gap:24px;
            }}
            .card {{
                background:#fff;
                border-radius:12px;
                box-shadow:0 15px 35px rgba(10,57,101,0.08);
                padding:28px;
            }}
            .card h1, .card h2, .card h3 {{
                color:#0e4da1;
                margin-top:0;
            }}
            .history-block {{
                background:#f5f7fb;
                border-radius:10px;
                padding:18px;
                border:1px solid #dfe6f2;
                min-height:100px;
            }}
            .response-box {{
                background:#eef5ff;
                border-left:4px solid #0e4da1;
                padding:18px;
                border-radius:8px;
                line-height:1.6;
                color:#1c2028;
            }}
            .feedback-actions {{
                display:flex;
                gap:12px;
                flex-wrap:wrap;
                margin-top:16px;
            }}
            .btn {{
                border-radius:8px;
                padding:10px 18px;
                font-weight:600;
                cursor:pointer;
                border:1px solid transparent;
                font-family:'Montserrat', sans-serif;
            }}
            .btn:disabled {{ opacity:0.5; cursor:not-allowed; }}
            .btn-solid {{
                background:#0066cc;
                color:#fff;
            }}
            .btn-outline {{
                background:#fff;
                color:#0e4da1;
                border:1px solid #a9c2e3;
            }}
            .btn-outline.danger {{ color:#c33a3a; border-color:#f0b8b8; }}
            textarea {{
                width:100%;
                border:1px solid #dbe2ec;
                border-radius:8px;
                padding:14px;
                font-size:16px;
                font-family:'Montserrat', sans-serif;
                min-height:120px;
                resize:vertical;
                box-sizing:border-box;
            }}
            .contact-panel {{
                flex:1 1 260px;
            }}
            .contact-card {{
                background:#e9eff7;
                border-radius:12px;
                padding:24px;
                box-shadow:0 10px 25px rgba(14,77,161,0.08);
            }}
            .contact-card h3 {{
                margin-top:0;
                color:#0e4da1;
            }}
            .contact-greeting {{
                margin:8px 0 14px;
                color:#24324c;
                line-height:1.4;
            }}
            .contact-name {{
                font-weight:600;
                color:#1c2028;
            }}
            .contact-meta {{
                color:#24324c;
                margin-bottom:4px;
            }}
            .contact-button {{
                display:inline-block;
                margin-top:12px;
                background:#0066cc;
                color:#fff;
                padding:10px 18px;
                border-radius:6px;
                text-decoration:none;
                font-weight:600;
            }}
            .notice {{
                background:#fef2d7;
                border-radius:10px;
                padding:14px;
                color:#8b5a06;
                margin-top:16px;
                display:none;
            }}
            @media (max-width:768px) {{
                .page-shell {{ padding:30px 16px; }}
            }}
        </style>
        {captcha_script}
    </head>
    <body>
        <div class="page-shell">
            <div class="primary-column">
                <div class="card">
                    <input type="hidden" id="conversation-id" value="{safe_thread_id}">
                    <h1>Regada servis – AI asistent</h1>
                    <div class="history-block">{chat_html}</div>
                </div>
                <div class="card">
                    <h3>Aktuálna otázka</h3>
                    <p><strong>{safe_question}</strong></p>
                    <h3>Odpoveď asistenta</h3>
                    <div class="response-box">{safe_answer}</div>
                    {safe_citations}
                </div>
                <div class="card">
                    <h3>Ďalšie kroky</h3>
                    <p>Pomohli sme vám? Dajte nám vedieť a pokračujte v konverzácii alebo eskalujte na servis.</p>
                    <div class="feedback-actions">
                        <button type="button" onclick="submitFeedback(1)" class="btn btn-outline" id="btn-helpful" {feedback_disabled_attr}>👍 Bolo to užitočné</button>
                        <button type="button" onclick="submitFeedback(-1)" class="btn btn-outline danger" id="btn-not-helpful" {feedback_disabled_attr}>👎 Nepomohlo</button>
                    </div>
                    <div id="feedback-result" class="notice"></div>
                    <form action="/ask" method="post" style="margin-top:20px;">
                        <textarea name="question" placeholder="Napíšte doplňujúcu otázku..." required></textarea>
                        <input type="hidden" name="thread_id" value="{safe_thread_id}">
                        {captcha_block}
                        <button type="submit" class="btn btn-solid" style="margin-top:12px;">Odoslať ďalšiu otázku</button>
                    </form>
                    <div class="feedback-actions" style="margin-top:20px;">
                        <form action="/escalate" method="post">
                            <input type="hidden" name="thread_id" value="{safe_thread_id}">
                            <input type="hidden" name="history_blob" value="{history_blob}">
                            <button type="submit" class="btn btn-outline" {"disabled" if not conversation_id else ""}>Eskalovať na Regada servis</button>
                        </form>
                        <a href="/" class="btn btn-outline">Nová konverzácia</a>
                        <a href="/stats" class="btn btn-outline">Admin štatistiky</a>
                    </div>
                </div>
            </div>
            <div class="contact-panel">
                {contact_html}
            </div>
        </div>
        <script>
            function submitFeedback(rating) {{
                const threadId = document.getElementById('conversation-id').value;
                const helpfulBtn = document.getElementById('btn-helpful');
                const notHelpfulBtn = document.getElementById('btn-not-helpful');
                const feedbackResult = document.getElementById('feedback-result');
                if (!threadId) {{
                    feedbackResult.style.display = 'block';
                    feedbackResult.innerHTML = 'Hodnotenie bude dostupné po prvej odpovedi.';
                    return;
                }}
                helpfulBtn.disabled = true;
                notHelpfulBtn.disabled = true;
                const formData = new FormData();
                formData.append('thread_id', threadId);
                formData.append('rating', rating);
                formData.append('comment', rating > 0 ? 'helpful' : 'not-helpful');
                fetch('/feedback', {{method: 'POST', body: formData}})
                .then(response => response.json().catch(() => ({{}})))
                .then(data => {{
                    if (data.status === 'ok') {{
                        feedbackResult.style.display = 'block';
                        feedbackResult.style.background = '#dff5e2';
                        feedbackResult.style.color = '#166534';
                        feedbackResult.innerHTML = 'Ďakujeme za hodnotenie!';
                    }} else {{
                        feedbackResult.style.display = 'block';
                        feedbackResult.style.background = '#fde2e2';
                        feedbackResult.style.color = '#7a1f1f';
                        feedbackResult.innerHTML = 'Nepodarilo sa uložiť spätnú väzbu.';
                        helpfulBtn.disabled = false;
                        notHelpfulBtn.disabled = false;
                    }}
                }})
                .catch(error => {{
                    feedbackResult.style.display = 'block';
                    feedbackResult.style.background = '#fde2e2';
                    feedbackResult.style.color = '#7a1f1f';
                    feedbackResult.innerHTML = 'Chyba pri odoslaní hodnotenia.';
                    helpfulBtn.disabled = false;
                    notHelpfulBtn.disabled = false;
                }});
            }}
        </script>
    </body>
    </html>
    """)

@app.post("/feedback")
async def feedback(request: Request, thread_id: str = Form(...), rating: int = Form(...), comment: str = Form(None)):
    client_host = request.client.host if request.client else "unknown"
    if not _check_rate_limit(f"feedback:{client_host}", FEEDBACK_RATE_LIMIT_MAX, FEEDBACK_RATE_LIMIT_WINDOW):
        return JSONResponse({"status": "error", "detail": "Too many feedback submissions"}, status_code=429)
    thread_id = (thread_id or "").strip()
    with conversation_lock:
        if thread_id not in conversation_state:
            return JSONResponse({"status": "error", "detail": "Unknown conversation"}, status_code=400)
    feedback_row = [
        datetime.now().isoformat(),
        _sanitize_csv_value(thread_id),
        rating,
        _sanitize_csv_value(comment or ""),
    ]
    try:
        with CSV_LOCK:
            file_exists = os.path.exists(FEEDBACK_LOG_FILE)
            with open(FEEDBACK_LOG_FILE, "a", newline='', encoding="utf-8") as f:
                writer = csv.writer(f)
                if not file_exists:
                    writer.writerow(["datetime", "thread_id", "rating", "comment"])
                writer.writerow(feedback_row)
        logger.info(f"Feedback received: Thread {thread_id}, Rating {rating}")
        return JSONResponse({"status": "ok"})
    except Exception as exc:
        logger.error(f"Feedback error: {exc}")
        return JSONResponse({"status": "error", "detail": str(exc)}, status_code=500)

@app.post("/escalate")
async def escalate(thread_id: str = Form(...), history_blob: str = Form(None)):
    conversation_id = (thread_id or "").strip()
    with conversation_lock:
        if conversation_id not in conversation_state:
            return HTMLResponse(
                content="<p>No conversation history found for escalation.</p>",
                status_code=404,
            )
    history_entries = _load_conversation_history(conversation_id)
    if not history_entries and history_blob:
        try:
            history_entries = json.loads(b64decode(history_blob).decode("utf-8"))
        except Exception:
            history_entries = []
    if not history_entries:
        return HTMLResponse(
            content="<p>No conversation history found for escalation.</p>",
            status_code=200,
        )

    chat_history_lines = []
    for entry in history_entries:
        question_text = entry.get("question")
        answer_text = entry.get("answer")
        if question_text:
            chat_history_lines.append(f"User: {html.escape(question_text)}")
        if answer_text:
            chat_history_lines.append(f"Assistant: {html.escape(answer_text)}")
    thread_text = "\n".join(chat_history_lines)
    mailto_body = quote(thread_text)

    return HTMLResponse(content=f"""
    <html><body style="font-family:sans-serif;padding:20px;">
    <h2>Escalation Protocol</h2>
    <h4>Chat History:</h4>
    <pre style="background:#f1f1f1;padding:10px">{thread_text}</pre>
    <p>Môžete skopírovať históriu a poslať e-mail na <a href="mailto:servis@regada.sk?subject=Eskalácia%20RegAdam&body={mailto_body}" target="_blank" rel="noopener">servis@regada.sk</a>. Pripomíname: uveďte číslo servopohonu, chybový kód a kontakt.</p>
    <a href='/'>Start new conversation</a>
    </body></html>
    """)

@app.get("/stats")
async def stats(request: Request):
    try:
        chat_stats = {"n_chats": 0, "n_questions": 0}
        feedback_stats = {"total": 0, "positive": 0, "negative": 0, "rate": 0}
        require_key = os.getenv("ADMIN_STATS_KEY")
        if require_key and request.headers.get("X-Admin-Stats-Key") != require_key:
            return HTMLResponse(content="<p>Admin statistics are disabled on this deployment.</p>", status_code=403)
        chat_rows = _iter_chat_rows()
        if chat_rows:
            chat_stats["n_questions"] = len(chat_rows)
            chat_stats["n_chats"] = len({row.get("thread_id") for row in chat_rows if row.get("thread_id")})

        if os.path.exists(FEEDBACK_LOG_FILE):
            with open(FEEDBACK_LOG_FILE, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                use_dict = reader.fieldnames and "thread_id" in reader.fieldnames
                feedback_entries: List[Dict[str, str]] = []
                if use_dict:
                    feedback_entries.extend(reader)
                else:
                    f.seek(0)
                    raw_reader = csv.reader(f)
                    for raw in raw_reader:
                        if len(raw) < 4:
                            continue
                        feedback_entries.append(
                            {
                                "datetime": raw[0],
                                "thread_id": raw[1],
                                "rating": raw[2],
                                "comment": raw[3],
                            }
                        )
                if feedback_entries:
                    feedback_stats["total"] = len(feedback_entries)
                    positives = 0
                    negatives = 0
                    for entry in feedback_entries:
                        try:
                            rating_val = int(str(entry.get("rating", "0")).strip())
                        except ValueError:
                            rating_val = 0
                        if rating_val > 0:
                            positives += 1
                        elif rating_val < 0:
                            negatives += 1
                    feedback_stats["positive"] = positives
                    feedback_stats["negative"] = negatives
                    if feedback_stats["total"] > 0:
                        feedback_stats["rate"] = (positives / feedback_stats["total"]) * 100

        return HTMLResponse(content=f"""
        <html><body style="font-family:sans-serif;padding:20px;">
        <h1>RegAdam Analytics</h1>
        <p><b>Total Conversations:</b> {chat_stats["n_chats"]}</p>
        <p><b>Total Questions:</b> {chat_stats["n_questions"]}</p>
        <p><b>Total Feedback:</b> {feedback_stats["total"]}</p>
        <p><b>Satisfaction Rate:</b> {feedback_stats["rate"]:.1f}% ({feedback_stats["positive"]} positive / {feedback_stats["negative"]} negative)</p>
        <a href="/">Back to Assistant</a>
        </body></html>
        """)
    except Exception as exc:
        logger.error(f"Stats error: {exc}")
        return HTMLResponse(
            content="<p>Unable to load statistics right now. Please try again later.</p>",
            status_code=500,
        )

@app.get("/health")
async def health_check():
    try:
        await asyncio.to_thread(client.models.list)
        return {"status": "healthy", "timestamp": datetime.now().isoformat()}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
