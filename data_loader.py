"""Utilities for loading structured RegAdam data sources.

The FastAPI app uses these helpers to access deterministic lookups instead of
letting the LLM parse semi-structured PDFs. The actual file paths are provided
via environment variables so deployments can mount secure storage.
"""

from __future__ import annotations

import os
import json
from functools import lru_cache
from pathlib import Path
from typing import Dict, Optional

import pandas as pd


DATA_ROOT = Path(os.getenv("DATA_ROOT", Path(__file__).resolve().parent / "data")).resolve()


class DataSourceError(RuntimeError):
    """Raised when a required CSV source is missing or unreadable."""


def _normalize_error_code(value: str) -> str:
    """Strip prefixes like 'E'/'e' and leading zeros."""
    text = str(value or "").strip()
    if not text:
        return ""
    text = text.lstrip("Ee")
    text = text.lstrip("0")
    return text or "0"


def _normalize_prefix(value: str) -> str:
    """Keep only digits from actuator prefix identifiers."""
    text = str(value or "").strip()
    digits = "".join(ch for ch in text if ch.isdigit())
    if digits and len(digits) == 2:
        digits = digits.zfill(3)
    return digits or text.upper()


def _ensure_data_path(path_value: str, env_name: str) -> Path:
    file_path = Path(path_value).expanduser().resolve()
    try:
        file_path.relative_to(DATA_ROOT)
    except ValueError as exc:
        raise DataSourceError(
            f"{env_name} must point inside {DATA_ROOT} (override via DATA_ROOT env if needed)"
        ) from exc
    if not file_path.exists():
        raise DataSourceError(f"{env_name} points to missing file: {file_path}")
    return file_path


def _read_csv_from_env(env_name: str, *, sep: str) -> pd.DataFrame:
    path = os.getenv(env_name)
    if not path:
        raise DataSourceError(f"{env_name} is not set")
    file_path = _ensure_data_path(path, env_name)
    try:
        return pd.read_csv(file_path, sep=sep, encoding="utf-8", engine="python")
    except Exception as exc:  # noqa: BLE001
        raise DataSourceError(f"Unable to read {file_path}: {exc}") from exc


@lru_cache(maxsize=1)
def load_error_table() -> pd.DataFrame:
    """Return the normalized, multilingual error definition dataframe."""
    df = _read_csv_from_env("ERROR_DB_PATH", sep=";")
    df.columns = [col.strip().lower() for col in df.columns]
    rename_map = {
        "error_number": "error_number",
        "číslo chyby": "error_number",
        "cislo chyby": "error_number",
        "name_SK": "name_sk",
        "cause_SK": "cause_sk",
        "remedy_SK": "remedy_sk",
        "name_EN": "name_en",
        "cause_EN": "cause_en",
        "remedy_EN": "remedy_en",
        "name_RU": "name_ru",
        "cause_RU": "cause_ru",
        "remedy_RU": "remedy_ru",
    }
    df = df.rename(columns={k.lower(): v for k, v in rename_map.items() if isinstance(k, str)})
    if "error_number" not in df.columns:
        raise DataSourceError("Error table missing 'error_number' column")
    df["error_code_normalized"] = df["error_number"].apply(_normalize_error_code)
    return df


@lru_cache(maxsize=1)
def load_actuator_table() -> Dict[str, Dict[str, str]]:
    """Return the actuator master data keyed by normalized prefix."""
    master_path = os.getenv("MASTER_ACTUATOR_TREE_PATH")
    fallback_path = os.getenv("ACTUATOR_TREE_PATH")
    path_value = master_path or fallback_path
    if not path_value:
        raise DataSourceError("MASTER_ACTUATOR_TREE_PATH is not set")
    env_used = "MASTER_ACTUATOR_TREE_PATH" if master_path else "ACTUATOR_TREE_PATH"
    file_path = _ensure_data_path(path_value, env_used)
    try:
        entries = json.loads(file_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise DataSourceError(f"Unable to parse actuator JSON: {exc}") from exc

    result: Dict[str, Dict[str, str]] = {}
    for row in entries:
        prefix = _normalize_prefix(row.get("type_code", ""))
        if not prefix:
            continue
        def _cap(value: Optional[str]) -> str:
            return str(value or "").strip()

        raw_pdfs = {
            "en": _cap(row.get("pdf_EN")),
            "sk": _cap(row.get("pdf_SK")),
            "ru": _cap(row.get("pdf_RU")),
        }
        availability = {
            "en": _cap(row.get("avail_EN")),
            "sk": _cap(row.get("avail_SK")),
            "ru": _cap(row.get("avail_RU")),
        }
        def _valid_filename(name: str) -> Optional[str]:
            if not name or name.upper() == "MISSING":
                return None
            return name

        pdfs = {lang: _valid_filename(name) for lang, name in raw_pdfs.items()}
        result[prefix] = {
            "prefix": prefix,
            "model": _cap(row.get("model")),
            "category": {"en": _cap(row.get("category_EN"))},
            "motion": {"en": _cap(row.get("motion_EN"))},
            "control": {"en": _cap(row.get("control_EN"))},
            "pdfs": pdfs,
            "availability": {lang: availability[lang].upper() == "YES" for lang in pdfs},
            "dms3_required": _cap(row.get("dms3_required")).upper() == "YES",
            "notes": _cap(row.get("notes")),
        }
    if not result:
        raise DataSourceError("Actuator master file contained no entries")
    return result


def lookup_error(code: Optional[str]) -> Optional[Dict[str, Dict[str, str]]]:
    """Return the multilingual error definition row for a normalized code."""
    if not code:
        return None
    normalized = _normalize_error_code(code)
    if not normalized:
        return None
    df = load_error_table()
    match = df[df["error_code_normalized"].astype(str).str.casefold() == normalized.casefold()]
    if match.empty:
        return None
    row = match.iloc[0].fillna("")
    return {
        "error_number": str(row.get("error_number", "")).strip(),
        "sk": {
            "name": str(row.get("name_sk", "")).strip(),
            "cause": str(row.get("cause_sk", "")).strip(),
            "remedy": str(row.get("remedy_sk", "")).strip(),
        },
        "en": {
            "name": str(row.get("name_en", "")).strip(),
            "cause": str(row.get("cause_en", "")).strip(),
            "remedy": str(row.get("remedy_en", "")).strip(),
        },
        "ru": {
            "name": str(row.get("name_ru", "")).strip(),
            "cause": str(row.get("cause_ru", "")).strip(),
            "remedy": str(row.get("remedy_ru", "")).strip(),
        },
    }


def lookup_actuator(prefix: Optional[str], language: str = "en") -> Optional[Dict[str, object]]:
    """Lookup actuator metadata based on the numeric prefix."""
    if not prefix:
        return None
    normalized = _normalize_prefix(prefix)
    if not normalized:
        return None
    table = load_actuator_table()
    row = table.get(normalized)
    if not row and normalized.isdigit() and len(normalized) == 2:
        padded = normalized.zfill(3)
        row = table.get(padded)
        if row:
            normalized = padded
    if not row:
        return None
    lang = language.lower()
    pdf_primary = row["pdfs"].get(lang) or next(
        (fname for fname in row["pdfs"].values() if fname),
        "",
    )
    availability = row["availability"]
    primary_lang = lang if row["pdfs"].get(lang) else next(
        (code for code, avail in availability.items() if avail and row["pdfs"].get(code)),
        lang,
    )
    fallbacks = [
        {"language": code, "filename": fname, "available": availability.get(code, False)}
        for code, fname in row["pdfs"].items()
        if code != primary_lang and fname
    ]
    control_text = " ".join(value.lower() for value in row.get("control", {}).values())
    is_intelligent = "intelligent" in control_text or "pa" in control_text or row.get("dms3_required", False)
    return {
        **row,
        "primary_manual": pdf_primary,
        "primary_manual_language": primary_lang,
        "manual_fallbacks": fallbacks,
        "availability": availability,
        "is_intelligent": is_intelligent,
    }
