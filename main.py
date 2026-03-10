from dotenv import load_dotenv

load_dotenv()
import asyncio
import csv
import html
import json
import os
import secrets
import threading
import time
from base64 import b64decode, b64encode
from collections import defaultdict, deque
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Deque, Dict, List, Optional, Tuple

import httpx
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
import logging
from openai import OpenAI, OpenAIError
from data_loader import lookup_actuator, lookup_error
from parser_utils import ParserDataError, parse_diagnostics
from conversation_state import ConversationState
from assistant_client import run_assistant_request
from text_utils import (
    clean_text,
    extract_prefix_candidates,
    normalize_error_code,
    normalize_prefix,
)

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
        "textarea_placeholder": "Example: my actuator number is 381.",
        "placeholder_need_prefix": "Example: my actuator number is 381.",
        "placeholder_need_error": "Example: error E17.",
        "placeholder_followup": "Example: the engine is making noise and does not turn.",
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
        "prompt_need_prefix": "Thanks for the details. Please provide the numeric prefix from the actuator nameplate (for example 280) so I can identify the device.",
        "prompt_need_prefix_error": "I see the error code you shared, but I still need the three-digit actuator prefix (for example 381) to decode it correctly.",
        "prompt_need_error": "Great. Now please share the error code, LED pattern, or alarm message shown on the actuator.",
        "manual_error_mismatch": "Thanks for the info. The actuator you identified uses mechanical indicators, so it does not display digital error codes like E17. Please describe the LED pattern or mechanical symptoms, or refer to the manual section on LED diagnostics.",
        "prompt_continue_button": "Send follow-up question",
        "actuator_summary_title": "Actuator identification",
        "error_summary_title": "Error reference",
        "prefix_label": "Prefix",
        "model_label": "Model",
        "type_label": "Type",
        "control_label": "Control",
        "document_label": "Manual section",
        "manual_primary_label": "Manual",
        "fallback_manuals_label": "Fallback manuals",
        "manual_availability_label": "Manual availability",
        "error_number_label": "Error number",
        "error_name_label": "Error name",
        "error_cause_label": "Cause",
        "error_action_label": "Corrective action",
        "escalation_title": "Escalation Protocol",
        "escalation_history_label": "Chat History",
        "escalation_instruction": "You can copy the transcript and email it to servis@regada.sk. Include the actuator number, error code, and your contact details.",
        "history_user_label": "User",
        "history_assistant_label": "Assistant",
        "contact_title": "Contact",
        "contact_greeting": "Hello, my name is Marko and I'm here for you.",
        "contact_button": "Service website",
    },
    "sk": {
        "lang_label": "Slovenčina",
        "landing_title": "Regada servis – AI asistent",
        "landing_intro": "Napíšte problém so servopohonom alebo ventilom a RegAdam vás prevedie ďalším postupom.",
        "textarea_placeholder": "Príklad: môj servopohon má číslo 381.",
        "placeholder_need_prefix": "Príklad: môj servopohon má číslo 381.",
        "placeholder_need_error": "Príklad: chyba E17.",
        "placeholder_followup": "Príklad: motor hučí a neotáča sa.",
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
        "prompt_need_prefix": "Ďakujeme za popis. Pošlite prosím číselný prefix zo štítku servopohonu (napr. 280), aby sme vedeli identifikovať zariadenie.",
        "prompt_need_prefix_error": "Rozumiem, že ste poslali chybový kód, ale najskôr potrebujeme trojmiestny prefix zo štítku pohonu (napr. 381), aby sme ho vedeli správne priradiť.",
        "prompt_need_error": "Výborne. Teraz nám pošlite chybový kód alebo vzor blikania LED, ktorý pohon zobrazuje.",
        "manual_error_mismatch": "Ďakujeme za informáciu. Tento typ servopohonu používa len mechanické ukazovatele, takže nezobrazuje digitálne chyby ako E17. Popíšte prosím vzor blikania LED alebo mechanické príznaky, prípadne pozrite manuál v sekcii diagnostiky LED.",
        "prompt_continue_button": "Poslať doplňujúcu otázku",
        "actuator_summary_title": "Identifikácia servopohonu",
        "error_summary_title": "Záznam chyby",
        "prefix_label": "Prefix",
        "model_label": "Typ",
        "type_label": "Druh",
        "control_label": "Ovládanie",
        "document_label": "Podklad",
        "manual_primary_label": "Manuál",
        "fallback_manuals_label": "Alternatívne manuály",
        "manual_availability_label": "Dostupnosť manuálov",
        "error_number_label": "Číslo chyby",
        "error_name_label": "Názov chyby",
        "error_cause_label": "Príčina",
        "error_action_label": "Odstránenie",
        "escalation_title": "Eskalácia na servis",
        "escalation_history_label": "História rozhovoru",
        "escalation_instruction": "Môžete skopírovať históriu a poslať e-mail na servis@regada.sk. Uveďte číslo servopohonu, chybový kód a kontakt.",
        "history_user_label": "Používateľ",
        "history_assistant_label": "Asistent",
        "contact_title": "Kontakt",
        "contact_greeting": "Dobrý deň, volám sa Marko a som tu pre vás.",
        "contact_button": "Viac o servise",
    },
    "ru": {
        "lang_label": "Русский",
        "landing_title": "Regada — технический ассистент",
        "landing_intro": "Опишите проблему с приводом, и RegAdam подскажет дальнейшие шаги.",
        "textarea_placeholder": "Пример: номер моего привода 381.",
        "placeholder_need_prefix": "Пример: номер моего привода 381.",
        "placeholder_need_error": "Пример: ошибка E17.",
        "placeholder_followup": "Пример: двигатель шумит и не вращается.",
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
        "prompt_need_prefix": "Спасибо за описание. Укажите числовой префикс с таблички привода (например 280), чтобы я определил модель.",
        "prompt_need_prefix_error": "Я вижу, что вы прислали код ошибки, но сначала нужен трёхзначный номер привода (например 381), чтобы корректно его расшифровать.",
        "prompt_need_error": "Хорошо. Теперь поделитесь кодом ошибки или шаблоном миганий, который отображает привод.",
        "manual_error_mismatch": "Спасибо за сообщение. Этот привод использует механические индикаторы и не показывает цифровые коды вроде E17. Опишите, пожалуйста, мигание LED или механические симптомы либо откройте раздел диагностики LED в руководстве.",
        "prompt_continue_button": "Отправить уточнение",
        "actuator_summary_title": "Идентификация привода",
        "error_summary_title": "Справка по ошибке",
        "prefix_label": "Префикс",
        "model_label": "Модель",
        "type_label": "Тип",
        "control_label": "Управление",
        "document_label": "Раздел инструкции",
        "manual_primary_label": "Руководство",
        "fallback_manuals_label": "Другие версии",
        "manual_availability_label": "Наличие руководств",
        "error_number_label": "Номер ошибки",
        "error_name_label": "Название ошибки",
        "error_cause_label": "Причина",
        "error_action_label": "Рекомендация",
        "escalation_title": "Эскалация в сервис",
        "escalation_history_label": "История диалога",
        "escalation_instruction": "Скопируйте историю и отправьте письмо на servis@regada.sk. Укажите номер привода, код ошибки и ваши контактные данные.",
        "history_user_label": "Пользователь",
        "history_assistant_label": "Ассистент",
        "contact_title": "Контакт",
        "contact_greeting": "Здравствуйте, меня зовут Марко, я помогу вам.",
        "contact_button": "Подробнее о сервисе",
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
You are a deterministic diagnostic parser for an industrial actuator support system.
Your ONLY task is to emit a single JSON object with every required key listed below.
If a field is unknown, set its value to null. Never omit keys and never return an empty object.
Extract:
- actuator_number_prefix
- actuator_model
- error_code
- led_pattern
- symptoms
- user_question
- language
Rules:
• actuator_number_prefix = digits from the actuator nameplate; strip spaces and non-digits.
• error_code = numeric portion of error identifiers (remove E/e and leading zeros).
• If data is not supplied, output null for that key.
• Do not invent or rephrase user text; user_question must echo the user request verbatim (trimmed).
• If multiple values exist, pick the most explicit.
Output strictly in JSON with those keys.
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




def _merge_parsed_values(
    parsed: ParsedDiagnostics,
    existing_prefix: Optional[str],
    existing_error_code: Optional[str],
    existing_symptoms: Optional[str],
) -> ParsedDiagnostics:
    merged_prefix = parsed.actuator_number_prefix or normalize_prefix(existing_prefix)
    merged_error = parsed.error_code or normalize_error_code(existing_error_code)
    merged_symptoms = parsed.symptoms or clean_text(existing_symptoms)
    return ParsedDiagnostics(
        actuator_number_prefix=merged_prefix,
        actuator_model=parsed.actuator_model,
        error_code=merged_error,
        led_pattern=parsed.led_pattern,
        symptoms=merged_symptoms,
        user_question=parsed.user_question,
        language=parsed.language,
    )


def _actuator_row_is_intelligent(row: Optional[Dict[str, Any]]) -> bool:
    if not row:
        return False
    if row.get("is_intelligent"):
        return True
    text_parts = []
    for key in ("model",):
        text_parts.append(str(row.get(key, "")))
    for subdict_key in ("motion", "control"):
        subdict = row.get(subdict_key, {})
        if isinstance(subdict, dict):
            text_parts.extend(subdict.values())
    text = " ".join(text_parts).lower()
    keywords = ("pa", "inteligent", "intelligent", "smart")
    return any(keyword in text for keyword in keywords)


def build_diagnostic_context(
    question: str,
    *,
    language: str,
    existing_prefix: Optional[str] = None,
    existing_error_code: Optional[str] = None,
    existing_symptoms: Optional[str] = None,
) -> DiagnosticContext:
    raw = parse_diagnostics(question, client, PARSER_MODEL)
    normalized_prefix = normalize_prefix(raw.get("actuator_number_prefix"))
    text_candidates = extract_prefix_candidates(question)
    if normalized_prefix and text_candidates and normalized_prefix not in text_candidates:
        normalized_prefix = None
    elif normalized_prefix and not text_candidates:
        normalized_prefix = None
    parsed_raw = ParsedDiagnostics(
        actuator_number_prefix=normalized_prefix,
        actuator_model=clean_text(raw.get("actuator_model")),
        error_code=normalize_error_code(raw.get("error_code")),
        led_pattern=clean_text(raw.get("led_pattern")),
        symptoms=clean_text(raw.get("symptoms")),
        user_question=clean_text(raw.get("user_question")) or question,
        language=resolve_language(raw.get("language")),
    )
    parsed = _merge_parsed_values(parsed_raw, existing_prefix, existing_error_code, existing_symptoms)
    actuator = lookup_actuator(parsed.actuator_number_prefix, language=language)
    error = None
    if parsed.actuator_number_prefix and parsed.error_code and _actuator_row_is_intelligent(actuator):
        error = lookup_error(parsed.error_code)
    return DiagnosticContext(parsed=parsed, actuator=actuator, error=error)


def actuator_is_intelligent(context: DiagnosticContext) -> bool:
    return _actuator_row_is_intelligent(context.actuator)


def needs_error_code(context: DiagnosticContext) -> bool:
    return actuator_is_intelligent(context)


def determine_next_action(context: DiagnosticContext) -> str:
    if not context.parsed.actuator_number_prefix:
        return "need_prefix"
    if needs_error_code(context) and not context.parsed.error_code:
        return "need_error"
    return "ready"


def _build_user_message(question: str, context: DiagnosticContext) -> List[Dict[str, str]]:
    payload = json.dumps(context.to_payload(), ensure_ascii=False)
    return [
        {"type": "text", "text": question},
        {"type": "text", "text": f"Structured diagnostics JSON:\n{payload}"},
    ]


RECAPTCHA_SITE_KEY = os.getenv("RECAPTCHA_SITE_KEY")
RECAPTCHA_SECRET_KEY = os.getenv("RECAPTCHA_SECRET_KEY")
ASK_RATE_LIMIT_MAX = int(os.getenv("ASK_RATE_LIMIT_MAX", "5"))
ASK_RATE_LIMIT_WINDOW = int(os.getenv("ASK_RATE_LIMIT_WINDOW", "10"))
FEEDBACK_RATE_LIMIT_MAX = int(os.getenv("FEEDBACK_RATE_LIMIT_MAX", "5"))
FEEDBACK_RATE_LIMIT_WINDOW = int(os.getenv("FEEDBACK_RATE_LIMIT_WINDOW", "60"))
LOG_FILE = "chat_metrics.csv"
FEEDBACK_LOG_FILE = "feedback_metrics.csv"

CSV_LOCK = threading.Lock()
CSRF_LOCK = threading.Lock()
CSRF_TOKENS: Dict[str, float] = {}
CSRF_TOKEN_TTL = 60 * 60  # 1 hour
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


def _generate_csrf_token() -> str:
    token = secrets.token_urlsafe(32)
    expiry = time.time() + CSRF_TOKEN_TTL
    with CSRF_LOCK:
        CSRF_TOKENS[token] = expiry
    return token


def _validate_csrf_token(token: Optional[str]) -> bool:
    if not token:
        return False
    now = time.time()
    with CSRF_LOCK:
        expired = [key for key, expiry in CSRF_TOKENS.items() if expiry <= now]
        for key in expired:
            CSRF_TOKENS.pop(key, None)
        expires_at = CSRF_TOKENS.get(token)
        if expires_at and expires_at > now:
            return True
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


def _render_chat_html(entries: List[Dict[str, str]], user_label: str, assistant_label: str) -> str:
    fragments: List[str] = []
    for entry in entries:
        question = entry.get("question") or ""
        answer = entry.get("answer") or ""
        if question:
            fragments.append(f"<b>{html.escape(user_label)}:</b> {html.escape(question)}<br>")
        if answer:
            fragments.append(f"<b>{html.escape(assistant_label)}:</b> {html.escape(answer)}<br>")
    return "".join(fragments)


def _contact_card_html(translations: Dict[str, str]) -> str:
    return f"""
    <div class="contact-card">
        <h3>{html.escape(translations["contact_title"])}</h3>
        <p class="contact-greeting">{html.escape(translations["contact_greeting"])}</p>
        <div class="contact-name">Ing. Marko Štofan</div>
        <div class="contact-meta">+421 51 7480 462</div>
        <div class="contact-meta">servis@regada.sk</div>
        <a class="contact-button" target="_blank" rel="noopener" href="https://www.regada.sk/servis/sluzby-zakaznikom#kontakt">{html.escape(translations["contact_button"])}</a>
    </div>
    """


def _format_insight_rows(items: List[Tuple[str, str]]) -> str:
    fragments = []
    for label, value in items:
        value = value.strip()
        if not value:
            continue
        fragments.append(
            f'<div class="insight-row"><span class="insight-label">{html.escape(label)}:</span> {html.escape(value)}</div>'
        )
    return "".join(fragments)


def _pick_localized(mapping: Dict[str, str], lang: str) -> str:
    if not isinstance(mapping, dict):
        return str(mapping or "")
    return str(mapping.get(lang) or mapping.get(DEFAULT_LANGUAGE) or next(iter(mapping.values()), "")).strip()


def _actuator_summary_html(context: DiagnosticContext, translations: Dict[str, str], lang: str) -> str:
    if not context.actuator:
        return ""
    data = context.actuator
    primary_manual = data.get("primary_manual") or ""
    primary_manual_lang = data.get("primary_manual_language", "").upper()
    manual_label = ""
    if primary_manual:
        manual_label = f"{primary_manual} ({primary_manual_lang})" if primary_manual_lang else primary_manual
    fallbacks = data.get("manual_fallbacks", [])
    fallback_text = ", ".join(
        f"{entry['filename']} ({entry['language'].upper()})"
        for entry in fallbacks
        if entry.get("filename")
    )
    availability = data.get("availability", {})
    availability_text = " / ".join(
        f"{code.upper()}: {'✓' if availability.get(code) else '✗'}" for code in ("en", "sk", "ru")
    )
    rows = _format_insight_rows(
        [
            (translations["prefix_label"], data.get("prefix", "")),
            (translations["model_label"], data.get("model", "")),
            (translations["type_label"], _pick_localized(data.get("motion", {}), lang)),
            (translations["control_label"], _pick_localized(data.get("control", {}), lang)),
            (translations["manual_primary_label"], manual_label),
        ]
    )
    if fallback_text:
        rows += _format_insight_rows([(translations["fallback_manuals_label"], fallback_text)])
    rows += _format_insight_rows([(translations["manual_availability_label"], availability_text)])
    if not rows:
        return ""
    title = html.escape(translations["actuator_summary_title"])
    return f'<div class="insight-card"><h4>{title}</h4>{rows}</div>'


def _error_summary_html(context: DiagnosticContext, translations: Dict[str, str], lang: str) -> str:
    if not context.error:
        return ""
    data = context.error
    localized = data.get(lang) or data.get(DEFAULT_LANGUAGE) or data.get("en") or {}
    rows = _format_insight_rows(
        [
            (translations["error_number_label"], data.get("error_number", "")),
            (translations["error_name_label"], localized.get("name", "")),
            (translations["error_cause_label"], localized.get("cause", "")),
            (translations["error_action_label"], localized.get("remedy", "")),
        ]
    )
    if not rows:
        return ""
    title = html.escape(translations["error_summary_title"])
    return f'<div class="insight-card"><h4>{title}</h4>{rows}</div>'

@app.get("/", response_class=HTMLResponse)
async def html_form(lang: str = DEFAULT_LANGUAGE):
    lang_input = (lang or "").strip()
    selected_lang = resolve_language(lang_input or DEFAULT_LANGUAGE)
    translations = get_translations(selected_lang)
    captcha_block = ""
    captcha_script = ""
    if RECAPTCHA_SITE_KEY:
        captcha_block = f'<div class=\"g-recaptcha\" data-sitekey=\"{RECAPTCHA_SITE_KEY}\"></div>'
        captcha_script = '<script src=\"https://www.google.com/recaptcha/api.js\" async defer></script>'
    contact_html = _contact_card_html(translations)
    lang_options = language_options_html(selected_lang)
    t = {key: html.escape(value) for key, value in translations.items()}
    csrf_token = _generate_csrf_token()
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
                    <input type=\"hidden\" name=\"known_prefix\" value=\"\">
                    <input type=\"hidden\" name=\"known_error_code\" value=\"\">
                    <input type=\"hidden\" name=\"known_symptoms\" value=\"\">
                    <input type=\"hidden\" name=\"csrf_token\" value=\"{csrf_token}\">
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
    known_prefix: Optional[str] = Form(None),
    known_error_code: Optional[str] = Form(None),
    known_symptoms: Optional[str] = Form(None),
    csrf_token: str = Form(...),
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

    lang_input = (lang or "").strip()
    selected_lang = resolve_language(lang_input or DEFAULT_LANGUAGE)

    if not _validate_csrf_token(csrf_token):
        return HTMLResponse(
            content="""
        <html><body style='padding:20px;font-family:sans-serif;'>
            <h3>Security Check Failed</h3>
            <p>Your session token expired or is invalid. Please reload the page and try again.</p>
            <a href='/'>← Return Home</a>
        </body></html>
        """,
            status_code=403,
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
    if len(cleaned_question) > 2000:
        logger.warning("Question too long submitted")
        return HTMLResponse(
            content=(
                "<html><body><h3>Error</h3><p>Please limit the question to "
                "2000 characters.</p><a href='/'>Return</a></body></html>"
            ),
            status_code=400,
        )

    incoming_state = ConversationState.from_form(known_prefix, known_error_code, known_symptoms)
    has_state_context = incoming_state.actuator_prefix or incoming_state.error_code
    if len(cleaned_question) < 3 and not thread_id and not has_state_context:
        logger.warning("Initial question too short submitted")
        return HTMLResponse(
            content=(
                "<html><body><h3>Error</h3><p>Please provide at least three "
                "characters for the first question.</p><a href='/'>Return</a></body></html>"
            ),
            status_code=400,
        )

    try:
        needs_parser = True
        actuator_info = None
        if incoming_state.actuator_prefix:
            actuator_info = lookup_actuator(incoming_state.actuator_prefix, language=selected_lang)
            is_intelligent = _actuator_row_is_intelligent(actuator_info)
            if is_intelligent and incoming_state.error_code:
                needs_parser = False
        if needs_parser:
            diagnostic_context = build_diagnostic_context(
                cleaned_question,
                language=selected_lang,
                existing_prefix=incoming_state.actuator_prefix,
                existing_error_code=incoming_state.error_code,
                existing_symptoms=incoming_state.symptoms,
            )
        else:
            actuator_info = actuator_info or lookup_actuator(incoming_state.actuator_prefix, language=selected_lang)
            dummy_parsed = ParsedDiagnostics(
                actuator_number_prefix=incoming_state.actuator_prefix,
                actuator_model=None,
                error_code=incoming_state.error_code,
                led_pattern=None,
                symptoms=incoming_state.symptoms,
                user_question=cleaned_question,
                language=selected_lang,
            )
            diagnostic_context = DiagnosticContext(
                parsed=dummy_parsed,
                actuator=actuator_info,
                error=lookup_error(incoming_state.error_code),
            )
    except ParserDataError as exc:
        logger.warning("Parser data error: %s", exc)
        return HTMLResponse(
            content="""
        <html><body style='padding:20px;font-family:sans-serif;'>
            <h3>Need more detail</h3>
            <p>I could not extract enough information from that message. Please restate the actuator number and error or symptom.</p>
            <a href='/'>← Return Home</a>
        </body></html>
        """,
            status_code=400,
        )
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

    if lang_input:
        response_language = selected_lang
    else:
        response_language = resolve_language(diagnostic_context.parsed.language or selected_lang)
    thread_id_value = (thread_id or "").strip()
    history_entries = _load_conversation_history(thread_id_value)
    translations = get_translations(response_language)
    page_csrf_token = _generate_csrf_token()

    parsed = diagnostic_context.parsed
    state = incoming_state.merge(parsed.actuator_number_prefix, parsed.error_code, parsed.symptoms)
    action = determine_next_action(diagnostic_context)
    awaiting_prefix_error = bool(diagnostic_context.parsed.error_code and not diagnostic_context.parsed.actuator_number_prefix)
    citations_html = ""
    manual_error_response = False
    if action == "need_prefix":
        if awaiting_prefix_error:
            answer_text = translations.get("prompt_need_prefix_error", translations["prompt_need_prefix"])
        else:
            answer_text = translations["prompt_need_prefix"]
    elif action == "need_error":
        answer_text = translations["prompt_need_error"]
    else:
        if diagnostic_context.parsed.error_code and not actuator_is_intelligent(diagnostic_context):
            answer_text = translations.get("manual_error_mismatch", translations["prompt_need_error"])
            manual_error_response = True
        else:
            try:
                lang_cfg = get_language_config(response_language)
                user_content = _build_user_message(cleaned_question, diagnostic_context)
                thread_id_value, answer_text, citations_html = await run_assistant_request(
                    client,
                    lang_cfg["assistant_id"],
                    user_content,
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

    updated_state = state
    state_prefix_value = updated_state.actuator_prefix or ""
    state_error_value = updated_state.error_code or ""
    state_symptom_value = updated_state.symptoms or ""
    diagnostic_cards_html = _actuator_summary_html(diagnostic_context, translations, response_language) + _error_summary_html(
        diagnostic_context, translations, response_language
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
    chat_html = _render_chat_html(
        history_with_current,
        translations["history_user_label"],
        translations["history_assistant_label"],
    )

    safe_question = html.escape(cleaned_question)
    safe_answer = html.escape(answer_text)
    safe_thread_id = html.escape(thread_id_value)
    safe_citations = citations_html
    hidden_prefix_value, hidden_error_value, hidden_symptom_value = (
        html.escape(value) for value in state.hidden()
    )
    diagnostic_cards_safe = diagnostic_cards_html
    feedback_disabled_attr = "" if thread_id_value else "disabled"
    history_blob = b64encode(json.dumps(history_with_current).encode("utf-8")).decode("ascii")
    captcha_block = ""
    captcha_script = ""
    if RECAPTCHA_SITE_KEY:
        captcha_block = f'<div class="g-recaptcha" data-sitekey="{RECAPTCHA_SITE_KEY}"></div>'
        captcha_script = '<script src="https://www.google.com/recaptcha/api.js" async defer></script>'

    lang_badge = html.escape(TRANSLATIONS.get(response_language, {}).get("lang_label", response_language.upper()))
    lang_param = html.escape(response_language)
    contact_html = _contact_card_html(translations)
    t_safe = {key: html.escape(value) for key, value in translations.items()}
    continue_button_label = t_safe.get("prompt_continue_button", t_safe["continue_conversation"])
    placeholder_key = "textarea_placeholder"
    if action == "need_prefix":
        placeholder_key = "placeholder_need_prefix"
    elif action == "need_error":
        placeholder_key = "placeholder_need_error"
    else:
        placeholder_key = "placeholder_followup"
    followup_placeholder = t_safe.get(placeholder_key, t_safe["textarea_placeholder"])

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
            .insight-card {{
                background:#fff7e6;
                border-radius:10px;
                padding:16px;
                border:1px solid #f4d7a6;
                margin-bottom:16px;
            }}
            .insight-card h4 {{
                margin-top:0;
                margin-bottom:12px;
                font-size:16px;
            }}
            .insight-row {{
                margin-bottom:6px;
                font-size:14px;
                line-height:1.4;
            }}
            .insight-label {{
                font-weight:600;
                color:#734d00;
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
                    <input type="hidden" id="csrf-token" value="{page_csrf_token}">
                    <div class="lang-chip">{lang_badge}</div>
                    <h1>{t_safe["landing_title"]}</h1>
                    <h3>{t_safe["conversation_history"]}</h3>
                    <div class="history-block">{chat_html}</div>
                </div>
                <div class="card">
                    <h3>{t_safe["your_question"]}</h3>
                    <p><strong>{safe_question}</strong></p>
                    {diagnostic_cards_safe}
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
                        <textarea name="question" placeholder="{followup_placeholder}" required></textarea>
                        <input type="hidden" name="thread_id" value="{safe_thread_id}">
                        <input type="hidden" name="lang" value="{lang_param}">
                        <input type="hidden" name="known_prefix" value="{hidden_prefix_value}">
                        <input type="hidden" name="known_error_code" value="{hidden_error_value}">
                        <input type="hidden" name="known_symptoms" value="{hidden_symptom_value}">
                        <input type="hidden" name="csrf_token" value="{page_csrf_token}">
                        {captcha_block}
                        <button type="submit" class="btn btn-solid" style="margin-top:12px;">{continue_button_label}</button>
                    </form>
                    <div class="feedback-actions" style="margin-top:20px;">
                        <form action="/escalate" method="post">
                            <input type="hidden" name="thread_id" value="{safe_thread_id}">
                            <input type="hidden" name="history_blob" value="{history_blob}">
                            <input type="hidden" name="lang" value="{lang_param}">
                            <input type="hidden" name="csrf_token" value="{page_csrf_token}">
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
                const csrfToken = document.getElementById('csrf-token').value;
                formData.append('csrf_token', csrfToken);
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
async def feedback(request: Request, thread_id: str = Form(...), rating: int = Form(...), comment: str = Form(None), csrf_token: str = Form(...)):
    client_host = request.client.host if request.client else "unknown"
    if not _check_rate_limit(f"feedback:{client_host}", FEEDBACK_RATE_LIMIT_MAX, FEEDBACK_RATE_LIMIT_WINDOW):
        return JSONResponse({"status": "error", "detail": "Too many feedback submissions"}, status_code=429)
    if not _validate_csrf_token(csrf_token):
        return JSONResponse({"status": "error", "detail": "Invalid CSRF token"}, status_code=403)
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
async def escalate(
    thread_id: str = Form(...),
    history_blob: str = Form(None),
    lang: str = Form(DEFAULT_LANGUAGE),
    csrf_token: str = Form(...),
):
    if not _validate_csrf_token(csrf_token):
        return HTMLResponse(
            content="""
        <html><body style='padding:20px;font-family:sans-serif;'>
            <h3>Security Check Failed</h3>
            <p>Your session token expired or is invalid. Please reload the page and try again.</p>
            <a href='/'>← Return Home</a>
        </body></html>
        """,
            status_code=403,
        )
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

    selected_lang = resolve_language(lang)
    translations = get_translations(selected_lang)
    user_label = translations["history_user_label"]
    assistant_label = translations["history_assistant_label"]
    chat_history_lines = []
    for entry in history_entries:
        question_text = entry.get("question")
        answer_text = entry.get("answer")
        if question_text:
            chat_history_lines.append(f"{html.escape(user_label)}: {html.escape(question_text)}")
        if answer_text:
            chat_history_lines.append(f"{html.escape(assistant_label)}: {html.escape(answer_text)}")
    thread_text = "\n".join(chat_history_lines)

    lang_param = html.escape(selected_lang)
    mailto_body = html.escape(thread_text)
    email_link = f'<a href="mailto:servis@regada.sk?subject=Eskalacia%20RegAdam&body={mailto_body}" target="_blank" rel="noopener">servis@regada.sk</a>'
    instruction_html = html.escape(translations["escalation_instruction"]).replace("servis@regada.sk", email_link)
    return HTMLResponse(content=f"""
    <html><body style="font-family:sans-serif;padding:20px;">
    <h2>{html.escape(translations["escalation_title"])}</h2>
    <h4>{html.escape(translations["escalation_history_label"])}:</h4>
    <pre style="background:#f1f1f1;padding:10px">{thread_text}</pre>
    <p>{instruction_html}</p>
    <a href='/?lang={lang_param}'>{html.escape(translations["new_convo"])}</a>
    </body></html>
    """)

@app.get("/stats")
async def stats(request: Request):
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
    record = lookup_actuator(prefix, language=DEFAULT_LANGUAGE)
    if not record:
        raise HTTPException(status_code=404, detail="Actuator prefix not found")
    return record

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
