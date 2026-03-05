from dotenv import load_dotenv
load_dotenv()
import asyncio
import csv
import html
import json
import os
import threading
import time
from base64 import b64decode, b64encode
from collections import defaultdict, deque
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Deque, Dict, List, Optional, Set, Tuple

import httpx
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
import logging
from openai import OpenAI, OpenAIError
from data_loader import lookup_actuator, lookup_error

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
PARSER_MODEL = os.getenv("PARSER_MODEL", "gpt-4.1-mini")
DEFAULT_LANGUAGE = os.getenv("DEFAULT_LANGUAGE", "en").lower()
SYSTEM_PROMPT = os.getenv(
    "REGADAM_SYSTEM_PROMPT",
    "Ste Regada Valve virtuálny technik. Odpovedajte po slovensky, buďte vecní "
    "a ak je to možné, opierajte sa o znalostnú bázu Regada Valve.",
)
VECTOR_STORE_ID = os.getenv("VECTOR_STORE_ID", "vs_ID")
LANGUAGE_CONFIG: Dict[str, Dict[str, Optional[str]]] = {
    "en": {
        "label": "English",
        "assistant_id": os.getenv("ASSISTANT_ID_EN"),
        "vector_store_id": os.getenv("VECTOR_STORE_ID_EN"),
    },
    "sk": {
        "label": "Slovak",
        "assistant_id": os.getenv("ASSISTANT_ID_SK"),
        "vector_store_id": os.getenv("VECTOR_STORE_ID_SK"),
    },
    "ru": {
        "label": "Russian",
        "assistant_id": os.getenv("ASSISTANT_ID_RU"),
        "vector_store_id": os.getenv("VECTOR_STORE_ID_RU"),
    },
}
TRANSLATIONS: Dict[str, Dict[str, str]] = {
    "en": {
        "lang_label": "English",
        "landing_title": "Regada Valve Assistant",
        "landing_intro": "Describe your actuator issue and RegAdam will guide you.",
        "textarea_placeholder": "Example: actuator shows E44 and won't rotate.",
        "submit_button": "Start Assistant",
        "conversation_history": "Conversation History",
        "your_question": "Your Question",
        "assistant_response": "Assistant Response",
        "helpful": "Helpful",
        "not_helpful": "Not Helpful",
        "continue_conversation": "Continue Conversation",
        "escalate": "Escalate to Human Support",
        "new_convo": "New Conversation",
        "admin_stats": "Admin Stats",
        "feedback_prompt": "Was this response helpful?",
        "language_select_label": "Language",
        "missing_prefix_title": "Need actuator ID",
        "missing_prefix_body": "Please provide the numeric prefix from the actuator nameplate (e.g., 280) before we continue troubleshooting.",
        "back_button": "Return Home",
    },
    "sk": {
        "lang_label": "Slovenčina",
        "landing_title": "Regada servis – AI asistent",
        "landing_intro": "Napíšte problém so servopohonom alebo ventilom a RegAdam vás prevedie ďalším postupom.",
        "textarea_placeholder": "Príklad: motor hučí a svieti E17.",
        "submit_button": "Spustiť asistenta",
        "conversation_history": "História konverzácie",
        "your_question": "Vaša otázka",
        "assistant_response": "Odpoveď asistenta",
        "helpful": "Pomohlo",
        "not_helpful": "Nepomohlo",
        "continue_conversation": "Pokračovať v konverzácii",
        "escalate": "Eskalovať na servis",
        "new_convo": "Nová konverzácia",
        "admin_stats": "Admin štatistiky",
        "feedback_prompt": "Bola odpoveď užitočná?",
        "language_select_label": "Jazyk",
        "missing_prefix_title": "Potrebujeme identifikáciu pohonu",
        "missing_prefix_body": "Zadajte prosím číselný prefix zo štítku servopohonu (napr. 280), až potom môžeme pokračovať v diagnostike.",
        "back_button": "Späť domov",
    },
    "ru": {
        "lang_label": "Русский",
        "landing_title": "Regada — технический ассистент",
        "landing_intro": "Опишите проблему с приводом, и RegAdam подскажет дальнейшие шаги.",
        "textarea_placeholder": "Пример: ошибка E44 и привод не вращается.",
        "submit_button": "Запустить ассистента",
        "conversation_history": "История диалога",
        "your_question": "Ваш вопрос",
        "assistant_response": "Ответ ассистента",
        "helpful": "Полезно",
        "not_helpful": "Не помогло",
        "continue_conversation": "Продолжить диалог",
        "escalate": "Эскалация в поддержку",
        "new_convo": "Новый разговор",
        "admin_stats": "Админ статистика",
        "feedback_prompt": "Ответ был полезным?",
        "language_select_label": "Язык",
        "missing_prefix_title": "Нужен номер привода",
        "missing_prefix_body": "Пожалуйста, укажите цифровой префикс с шильдика привода (например, 280), после этого мы продолжим диагностику.",
        "back_button": "Вернуться",
    },
}


def language_options_html(selected_lang: str) -> str:
    options = []
    for code in LANGUAGE_CONFIG:
        label = TRANSLATIONS.get(code, {}).get("lang_label", code.upper())
        selected_attr = " selected" if code == selected_lang else ""
        options.append(f'<option value="{code}"{selected_attr}>{html.escape(label)}</option>')
    return "".join(options)
PARSER_SYSTEM_PROMPT = """
You are a diagnostic parser for an industrial actuator support system.
Your task is ONLY to extract structured diagnostic information from the user message.
Do not provide explanations or solutions.
Extract the following fields if present:
- actuator_number_prefix
- actuator_model
- error_code
- led_pattern
- symptoms
- user_question
- language
Rules:
• actuator_number_prefix = first digits from actuator nameplate
• error_code = normalized numeric error code (remove E/e and leading zeros)
• if error code cannot be determined leave null
• do not guess missing values
• if multiple values appear return the most explicit one
Output strictly in JSON.
""".strip()
PARSER_JSON_SCHEMA = {
    "name": "diagnostic_parser",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "actuator_number_prefix": {"type": ["string", "null"]},
            "actuator_model": {"type": ["string", "null"]},
            "error_code": {"type": ["string", "null"]},
            "led_pattern": {"type": ["string", "null"]},
            "symptoms": {"type": ["string", "null"]},
            "user_question": {"type": "string"},
            "language": {"type": ["string", "null"]},
        },
        "required": [
            "actuator_number_prefix",
            "actuator_model",
            "error_code",
            "led_pattern",
            "symptoms",
            "user_question",
            "language",
        ],
    },
}


def _validate_language_config() -> None:
    if DEFAULT_LANGUAGE not in LANGUAGE_CONFIG:
        raise RuntimeError(f"DEFAULT_LANGUAGE '{DEFAULT_LANGUAGE}' not configured")
    missing = []
    for lang_code, cfg in LANGUAGE_CONFIG.items():
        if not cfg.get("assistant_id") or not cfg.get("vector_store_id"):
            missing.append(lang_code)
    if missing:
        raise RuntimeError(
            f"Missing assistant/vector store IDs for languages: {', '.join(sorted(missing))}"
        )


def resolve_language(lang: Optional[str]) -> str:
    candidate = (lang or DEFAULT_LANGUAGE).lower()
    if candidate not in LANGUAGE_CONFIG:
        return DEFAULT_LANGUAGE
    cfg = LANGUAGE_CONFIG.get(candidate, {})
    if not cfg.get("assistant_id") or not cfg.get("vector_store_id"):
        return DEFAULT_LANGUAGE
    return candidate


def get_language_config(lang: Optional[str]) -> Dict[str, Optional[str]]:
    resolved = resolve_language(lang)
    return LANGUAGE_CONFIG[resolved]


def get_translations(lang: Optional[str]) -> Dict[str, str]:
    resolved = resolve_language(lang)
    return TRANSLATIONS.get(resolved, TRANSLATIONS[DEFAULT_LANGUAGE])


_validate_language_config()


def _clean_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_error_code(value: Optional[str]) -> Optional[str]:
    text = _clean_text(value)
    if not text:
        return None
    text = text.lstrip("Ee")
    text = text.lstrip("0")
    return text or "0"


def _normalize_prefix(value: Optional[str]) -> Optional[str]:
    text = _clean_text(value)
    if not text:
        return None
    digits = "".join(ch for ch in text if ch.isdigit())
    return digits or text.upper()


@dataclass
class ParsedDiagnostics:
    actuator_number_prefix: Optional[str]
    actuator_model: Optional[str]
    error_code: Optional[str]
    led_pattern: Optional[str]
    symptoms: Optional[str]
    user_question: str
    language: str

    def to_dict(self) -> Dict[str, Optional[str]]:
        return {
            "actuator_number_prefix": self.actuator_number_prefix,
            "actuator_model": self.actuator_model,
            "error_code": self.error_code,
            "led_pattern": self.led_pattern,
            "symptoms": self.symptoms,
            "user_question": self.user_question,
            "language": self.language,
        }


@dataclass
class DiagnosticContext:
    parsed: ParsedDiagnostics
    actuator: Optional[Dict[str, str]]
    error: Optional[Dict[str, str]]

    def to_payload(self) -> Dict[str, Any]:
        return {
            "parsed": self.parsed.to_dict(),
            "actuator_lookup": self.actuator,
            "error_lookup": self.error,
        }


def _extract_json_from_response(response) -> Dict[str, Any]:
    payload = response.model_dump()
    for item in payload.get("output", []):
        for content in item.get("content", []):
            if "json" in content:
                return content["json"]
            text_payload = content.get("text")
            text_value = ""
            if isinstance(text_payload, dict):
                text_value = text_payload.get("value", "")
            elif isinstance(text_payload, str):
                text_value = text_payload
            if not text_value and isinstance(content, dict):
                candidate = content.get("value")
                if isinstance(candidate, str):
                    text_value = candidate
            if text_value:
                try:
                    return json.loads(text_value)
                except json.JSONDecodeError:
                    continue
    output_text = getattr(response, "output_text", None)
    if output_text:
        if isinstance(output_text, str):
            output_candidates = [output_text]
        else:
            output_candidates = output_text
        for text_value in output_candidates:
            try:
                return json.loads(text_value)
            except json.JSONDecodeError:
                continue
    logger.error("Parser raw payload: %s", payload)
    raise RuntimeError("Unable to extract JSON from parser response")


def call_diagnostic_parser(question: str) -> ParsedDiagnostics:
    messages = [
        {"role": "system", "content": PARSER_SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]
    response = client.responses.create(
        model=PARSER_MODEL,
        input=messages,
    )
    raw = _extract_json_from_response(response)
    parsed = ParsedDiagnostics(
        actuator_number_prefix=_normalize_prefix(raw.get("actuator_number_prefix")),
        actuator_model=_clean_text(raw.get("actuator_model")),
        error_code=_normalize_error_code(raw.get("error_code")),
        led_pattern=_clean_text(raw.get("led_pattern")),
        symptoms=_clean_text(raw.get("symptoms")),
        user_question=_clean_text(raw.get("user_question")) or question,
        language=resolve_language(raw.get("language")),
    )
    return parsed


def build_diagnostic_context(question: str) -> DiagnosticContext:
    parsed = call_diagnostic_parser(question)
    actuator = lookup_actuator(parsed.actuator_number_prefix)
    error = lookup_error(parsed.error_code)
    return DiagnosticContext(parsed=parsed, actuator=actuator, error=error)


def needs_prefix_request(context: DiagnosticContext) -> bool:
    return context.parsed.actuator_number_prefix is None


def _build_user_message(question: str, context: DiagnosticContext) -> List[Dict[str, str]]:
    payload = json.dumps(context.to_payload(), ensure_ascii=False)
    return [
        {"type": "text", "text": question},
        {"type": "text", "text": f"Structured diagnostics JSON:\n{payload}"},
    ]


def _resolve_file_name(file_id: Optional[str]) -> str:
    if not file_id:
        return "Reference"
    try:
        file_info = client.files.retrieve(file_id)
        return file_info.filename or f"File ID {file_id}"
    except Exception:
        return f"File ID {file_id}"


def _format_citations(annotation: Dict[str, Any]) -> str:
    citation = annotation.get("file_citation", {})
    file_id = citation.get("file_id")
    quote = citation.get("quote", "")
    filename = _resolve_file_name(file_id)
    filename_safe = html.escape(str(filename))
    quote_safe = html.escape(quote)
    return filename_safe + (f' ("{quote_safe}")' if quote_safe else "")


def _extract_answer_from_message(message) -> Tuple[str, str]:
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
                citations.add(_format_citations(ann))
    answer_text = "\n\n".join(parts).strip() or "[No answer returned]"
    citations_html = ""
    if citations:
        citations_html = "<h4>References:</h4><ul>" + "".join(f"<li>{c}</li>" for c in sorted(citations)) + "</ul>"
    return answer_text, citations_html


async def run_language_assistant(
    question: str,
    lang: str,
    diagnostic_context: DiagnosticContext,
    existing_thread_id: Optional[str],
) -> Tuple[str, str, str]:
    cfg = get_language_config(lang)
    assistant_id = cfg["assistant_id"]
    vector_store_id = cfg["vector_store_id"]

    user_content = _build_user_message(question, diagnostic_context)

    if existing_thread_id:
        thread_id = existing_thread_id
        await asyncio.to_thread(
            client.beta.threads.messages.create,
            thread_id=thread_id,
            role="user",
            content=user_content,
        )
    else:
        thread = await asyncio.to_thread(
            client.beta.threads.create,
            messages=[
                {
                    "role": "user",
                    "content": user_content,
                }
            ],
        )
        thread_id = thread.id

    run_kwargs = {
        "thread_id": thread_id,
        "assistant_id": assistant_id,
    }
    if vector_store_id:
        run_kwargs["tool_resources"] = {
            "file_search": {"vector_store_ids": [vector_store_id]}
        }
    run = await asyncio.to_thread(client.beta.threads.runs.create, **run_kwargs)

    start_time = time.time()
    timeout = 60
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
        await asyncio.sleep(1)

    messages = await asyncio.to_thread(client.beta.threads.messages.list, thread_id=thread_id)
    msgs_sorted = sorted(messages.data, key=lambda m: m.created_at)
    answer_msg = next((m for m in reversed(msgs_sorted) if m.role == "assistant"), None)
    answer_text, citations_html = await asyncio.to_thread(_extract_answer_from_message, answer_msg)
    return thread_id, answer_text, citations_html
RECAPTCHA_SITE_KEY = os.getenv("RECAPTCHA_SITE_KEY")
RECAPTCHA_SECRET_KEY = os.getenv("RECAPTCHA_SECRET_KEY")
ASK_RATE_LIMIT_MAX = int(os.getenv("ASK_RATE_LIMIT_MAX", "5"))
ASK_RATE_LIMIT_WINDOW = int(os.getenv("ASK_RATE_LIMIT_WINDOW", "10"))
FEEDBACK_RATE_LIMIT_MAX = int(os.getenv("FEEDBACK_RATE_LIMIT_MAX", "5"))
FEEDBACK_RATE_LIMIT_WINDOW = int(os.getenv("FEEDBACK_RATE_LIMIT_WINDOW", "60"))
LOG_FILE = "chat_metrics.csv"
FEEDBACK_LOG_FILE = "feedback_metrics.csv"

CSV_LOCK = threading.Lock()
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
async def html_form(lang: str = DEFAULT_LANGUAGE):
    selected_lang = resolve_language(lang)
    translations = get_translations(selected_lang)
    captcha_block = ""
    captcha_script = ""
    if RECAPTCHA_SITE_KEY:
        captcha_block = f'<div class=\"g-recaptcha\" data-sitekey=\"{RECAPTCHA_SITE_KEY}\"></div>'
        captcha_script = '<script src=\"https://www.google.com/recaptcha/api.js\" async defer></script>'
    contact_html = _contact_card_html()
    lang_options = language_options_html(selected_lang)
    t = {key: html.escape(value) for key, value in translations.items()}
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
            .form-row {{
                margin-bottom:16px;
                display:flex;
                flex-direction:column;
                gap:8px;
            }}
            textarea {{
                width:100%;
                border:1px solid #dbe2ec;
                border-radius:8px;
                padding:14px;
                font-size:16px;
                font-family:'Montserrat', sans-serif;
                min-height:140px;
                resize:vertical;
                box-sizing:border-box;
            }}
            select {{
                border:1px solid #dbe2ec;
                border-radius:8px;
                padding:10px;
                font-size:15px;
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
                <h2>{t["landing_title"]}</h2>
                <p>{t["landing_intro"]}</p>
                <form action=\"/ask\" method=\"post\">
                    <div class=\"form-row\">
                        <label for=\"lang-select\">{t["language_select_label"]}</label>
                        <select id=\"lang-select\" name=\"lang\">
                            {lang_options}
                        </select>
                    </div>
                    <div class=\"form-row\">
                        <textarea name=\"question\" placeholder=\"{t["textarea_placeholder"]}\"></textarea>
                    </div>
                    <input type=\"hidden\" name=\"thread_id\" value=\"\">
                    {captcha_block}
                    <button type=\"submit\" class=\"primary-btn\">{t["submit_button"]}</button>
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
    lang: str = Form(DEFAULT_LANGUAGE),
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

    selected_lang = resolve_language(lang)

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

    try:
        diagnostic_context = build_diagnostic_context(cleaned_question)
    except OpenAIError as exc:
        logger.error(f"Parser API error: {exc}")
        return HTMLResponse(
            content="""
        <html><body style='padding:20px;font-family:sans-serif;'>
            <h3>⚠️ Service Temporarily Unavailable</h3>
            <p>We're experiencing connectivity issues. Please try again shortly.</p>
            <a href='/'>← Return Home</a>
        </body></html>
        """,
            status_code=503,
        )
    except Exception as exc:
        logger.error(f"Parser failure: {exc}")
        return HTMLResponse(
            content="""
        <html><body style='padding:20px;font-family:sans-serif;'>
            <h3>⚠️ System Error</h3>
            <p>An unexpected error occurred while preparing your request.</p>
            <a href='/'>← Return Home</a>
        </body></html>
        """,
            status_code=500,
        )

    response_language = resolve_language(diagnostic_context.parsed.language or selected_lang)
    thread_id_value = (thread_id or "").strip()
    history_entries = _load_conversation_history(thread_id_value)
    translations = get_translations(response_language)

    if needs_prefix_request(diagnostic_context):
        t_safe = {key: html.escape(value) for key, value in translations.items()}
        safe_question = html.escape(cleaned_question)
        lang_param = html.escape(response_language)
        return HTMLResponse(
            content=f"""
        <html><body style='padding:20px;font-family:sans-serif;background:#f5f5f5;'>
            <div style="max-width:640px;margin:0 auto;background:#fff;padding:30px;border-radius:10px;box-shadow:0 4px 18px rgba(0,0,0,0.08);">
                <div style="text-transform:uppercase;font-size:12px;color:#6c757d;margin-bottom:8px;">{t_safe["language_select_label"]}: {t_safe["lang_label"]}</div>
                <h2>{t_safe["missing_prefix_title"]}</h2>
                <p>{t_safe["missing_prefix_body"]}</p>
                <p><b>{safe_question}</b></p>
                <a href="/?lang={lang_param}" style="display:inline-block;margin-top:16px;padding:10px 18px;border-radius:8px;background:#0066cc;color:#fff;text-decoration:none;">{t_safe["back_button"]}</a>
            </div>
        </body></html>
        """,
            status_code=200,
        )

    try:
        thread_id_value, answer_text, citations_html = await run_language_assistant(
            cleaned_question,
            response_language,
            diagnostic_context,
            thread_id_value,
        )
    except TimeoutError:
        return HTMLResponse(content="Assistant response timeout. Please try again later.", status_code=504)
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

    log_row = [
        datetime.now().isoformat(),
        _sanitize_csv_value(thread_id_value),
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

    safe_question = html.escape(cleaned_question)
    safe_answer = html.escape(answer_text)
    safe_thread_id = html.escape(thread_id_value)
    safe_citations = citations_html
    feedback_disabled_attr = "" if thread_id_value else "disabled"
    history_blob = b64encode(json.dumps(history_with_current).encode("utf-8")).decode("ascii")
    captcha_block = ""
    captcha_script = ""
    if RECAPTCHA_SITE_KEY:
        captcha_block = f'<div class="g-recaptcha" data-sitekey="{RECAPTCHA_SITE_KEY}"></div>'
        captcha_script = '<script src="https://www.google.com/recaptcha/api.js" async defer></script>'

    lang_badge = html.escape(TRANSLATIONS.get(response_language, {}).get("lang_label", response_language.upper()))
    lang_param = html.escape(response_language)
    contact_html = _contact_card_html()
    t_safe = {key: html.escape(value) for key, value in translations.items()}

    page_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>{t_safe["landing_title"]}</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <link rel="preconnect" href="https://fonts.googleapis.com">
        <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
        <link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@400;600;700&display=swap" rel="stylesheet">
        <style>
            body {{
                margin:0;
                background:#f5f6fb;
                font-family:'Montserrat', sans-serif;
                color:#1c2028;
            }}
            .page-shell {{
                max-width:1100px;
                margin:0 auto;
                padding:40px 20px;
                display:flex;
                gap:24px;
                flex-wrap:wrap;
            }}
            .primary-column {{
                flex:1 1 640px;
                display:flex;
                flex-direction:column;
                gap:24px;
            }}
            .card {{
                background:#fff;
                border-radius:14px;
                padding:28px;
                box-shadow:0 12px 30px rgba(4,32,96,0.08);
            }}
            .lang-chip {{
                display:inline-block;
                padding:6px 12px;
                border-radius:20px;
                background:#e3ebff;
                color:#0e4da1;
                font-size:13px;
                font-weight:600;
                margin-bottom:10px;
            }}
            .history-block {{
                background:#f5f7fb;
                border-radius:10px;
                padding:16px;
                line-height:1.6;
                max-height:240px;
                overflow:auto;
                border:1px solid #e0e7f6;
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
                border-radius:10px;
                padding:14px;
                font-family:'Montserrat', sans-serif;
                font-size:15px;
                min-height:120px;
                box-sizing:border-box;
                resize:vertical;
            }}
            .contact-panel {{
                flex:1 1 260px;
            }}
            .notice {{
                display:none;
                margin-top:12px;
                padding:12px 16px;
                border-radius:8px;
            }}
        </style>
        {captcha_script}
    </head>
    <body>
        <div class="page-shell">
            <div class="primary-column">
                <div class="card">
                    <input type="hidden" id="conversation-id" value="{safe_thread_id}">
                    <div class="lang-chip">{lang_badge}</div>
                    <h1>{t_safe["landing_title"]}</h1>
                    <h3>{t_safe["conversation_history"]}</h3>
                    <div class="history-block">{chat_html}</div>
                </div>
                <div class="card">
                    <h3>{t_safe["your_question"]}</h3>
                    <p><strong>{safe_question}</strong></p>
                    <h3>{t_safe["assistant_response"]}</h3>
                    <div class="response-box">{safe_answer}</div>
                    {safe_citations}
                </div>
                <div class="card">
                    <h3>{t_safe["continue_conversation"]}</h3>
                    <p>{t_safe["feedback_prompt"]}</p>
                    <div class="feedback-actions">
                        <button type="button" onclick="submitFeedback(1)" class="btn btn-outline" id="btn-helpful" {feedback_disabled_attr}>{t_safe["helpful"]}</button>
                        <button type="button" onclick="submitFeedback(-1)" class="btn btn-outline danger" id="btn-not-helpful" {feedback_disabled_attr}>{t_safe["not_helpful"]}</button>
                    </div>
                    <div id="feedback-result" class="notice"></div>
                    <form action="/ask" method="post" style="margin-top:20px;">
                        <textarea name="question" placeholder="{t_safe["textarea_placeholder"]}" required></textarea>
                        <input type="hidden" name="thread_id" value="{safe_thread_id}">
                        <input type="hidden" name="lang" value="{lang_param}">
                        {captcha_block}
                        <button type="submit" class="btn btn-solid" style="margin-top:12px;">{t_safe["continue_conversation"]}</button>
                    </form>
                    <div class="feedback-actions" style="margin-top:20px;">
                        <form action="/escalate" method="post">
                            <input type="hidden" name="thread_id" value="{safe_thread_id}">
                            <input type="hidden" name="history_blob" value="{history_blob}">
                            <input type="hidden" name="lang" value="{lang_param}">
                            <button type="submit" class="btn btn-outline" {"disabled" if not thread_id_value else ""}>{t_safe["escalate"]}</button>
                        </form>
                        <a href="/?lang={lang_param}" class="btn btn-outline">{t_safe["new_convo"]}</a>
                        <a href="/stats" class="btn btn-outline">{t_safe["admin_stats"]}</a>
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
                    feedbackResult.innerHTML = 'Feedback is available after the first answer.';
                    return;
                }}
                helpfulBtn.disabled = true;
                notHelpfulBtn.disabled = true;
                const formData = new FormData();
                formData.append('thread_id', threadId);
                formData.append('rating', rating);
                formData.append('comment', rating > 0 ? 'helpful' : 'not-helpful');
                fetch('/feedback', {{method: 'POST', body: formData}})
                .then(response => response.text())
                .then(() => {{
                    feedbackResult.style.display = 'block';
                    feedbackResult.style.background = '#dff5e2';
                    feedbackResult.style.color = '#166534';
                    feedbackResult.innerHTML = 'Thank you for your feedback!';
                }})
                .catch(() => {{
                    feedbackResult.style.display = 'block';
                    feedbackResult.style.background = '#fde2e2';
                    feedbackResult.style.color = '#7a1f1f';
                    feedbackResult.innerHTML = 'Error submitting feedback.';
                    helpfulBtn.disabled = false;
                    notHelpfulBtn.disabled = false;
                }});
            }}
        </script>
    </body>
    </html>
    """

    return HTMLResponse(content=page_html)


@app.post("/feedback")
async def feedback(request: Request, thread_id: str = Form(...), rating: int = Form(...), comment: str = Form(None)):
    client_host = request.client.host if request.client else "unknown"
    if not _check_rate_limit(f"feedback:{client_host}", FEEDBACK_RATE_LIMIT_MAX, FEEDBACK_RATE_LIMIT_WINDOW):
        return JSONResponse({"status": "error", "detail": "Too many feedback submissions"}, status_code=429)
    thread_id = (thread_id or "").strip()
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

    return HTMLResponse(content=f"""
    <html><body style="font-family:sans-serif;padding:20px;">
    <h2>Escalation Protocol</h2>
    <h4>Chat History:</h4>
    <pre style="background:#f1f1f1;padding:10px">{thread_text}</pre>
    <p>Môžete skopírovať históriu a poslať e-mail na <a href="mailto:servis@regada.sk?subject=Eskalácia%20RegAdam&body={html.escape(thread_text)}" target="_blank" rel="noopener">servis@regada.sk</a>. Pripomíname: uveďte číslo servopohonu, chybový kód a kontakt.</p>
    <a href='/'>Start new conversation</a>
    </body></html>
    """)

@app.get("/stats")
async def stats():
    try:
        chat_stats = {"n_chats": 0, "n_questions": 0}
        feedback_stats = {"total": 0, "positive": 0, "negative": 0, "rate": 0}
        require_key = os.getenv("ADMIN_STATS_KEY")
        provided_key = os.getenv("ADMIN_STATS_KEY_VALUE")
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


@app.get("/debug/error/{code}")
async def debug_error(code: str):
    """
    Lightweight helper to verify structured error lookups before wiring
    them into the two-stage pipeline.
    """
    record = lookup_error(code)
    if not record:
        raise HTTPException(status_code=404, detail="Error code not found")
    return record


@app.get("/debug/actuator/{prefix}")
async def debug_actuator(prefix: str):
    """
    Lightweight helper for checking actuator prefix normalization.
    """
    record = lookup_actuator(prefix)
    if not record:
        raise HTTPException(status_code=404, detail="Actuator prefix not found")
    return record

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
