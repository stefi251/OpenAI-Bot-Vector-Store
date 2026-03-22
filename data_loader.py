"""Utilities for loading structured RegAdam data sources.

The FastAPI app uses these helpers to access deterministic lookups instead of
letting the LLM parse semi-structured PDFs. The actual file paths are provided
via environment variables so deployments can mount secure storage.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Dict, Optional

import pandas as pd


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
    return digits or text.upper()


def _read_csv_from_env(env_name: str, *, sep: str) -> pd.DataFrame:
    path = os.getenv(env_name)
    if not path:
        raise DataSourceError(f"{env_name} is not set")
    file_path = Path(path)
    if not file_path.exists():
        raise DataSourceError(f"{env_name} points to missing file: {file_path}")
    try:
        return pd.read_csv(file_path, sep=sep, encoding="utf-8", engine="python")
    except Exception as exc:  # noqa: BLE001
        raise DataSourceError(f"Unable to read {file_path}: {exc}") from exc


@lru_cache(maxsize=1)
def load_error_table() -> pd.DataFrame:
    """Return the normalized error definition dataframe."""
    df = _read_csv_from_env("ERROR_DB_PATH", sep=";")
    rename_map = {
        "číslo chyby": "error_number",
        "cislo chyby": "error_number",
        "názov chyby": "error_name",
        "nazov chyby": "error_name",
        "príčina": "cause",
        "pricina": "cause",
        "odstránenie chyby": "corrective_action",
        "odstranenie chyby": "corrective_action",
    }
    df.columns = [col.strip().lower() for col in df.columns]
    df = df.rename(columns=rename_map)
    missing = {"error_number", "error_name", "cause", "corrective_action"} - set(df.columns)
    if missing:
        raise DataSourceError(f"Error table missing columns: {', '.join(sorted(missing))}")
    df["error_code_normalized"] = df["error_number"].apply(_normalize_error_code)
    return df


@lru_cache(maxsize=1)
def load_actuator_table() -> pd.DataFrame:
    """Return the normalized actuator tree dataframe."""
    # First row is a textual label, skip it.
    path = os.getenv("ACTUATOR_TREE_PATH")
    if not path:
        raise DataSourceError("ACTUATOR_TREE_PATH is not set")
    file_path = Path(path)
    if not file_path.exists():
        raise DataSourceError(f"ACTUATOR_TREE_PATH points to missing file: {file_path}")
    raw_df = pd.read_csv(
        file_path,
        sep=";",
        encoding="utf-8",
        engine="python",
        skiprows=1,  # skip 'Table 1'
    )
    if raw_df.empty:
        raise DataSourceError("Actuator tree CSV is empty")
    # Remove empty rows and normalize header names.
    raw_df = raw_df.dropna(how="all")
    raw_df.columns = [str(col).strip(" :").lower() for col in raw_df.columns]
    raw_df = raw_df.dropna(how="all")
    rename_map = {
        "typové číslo servopohonov": "prefix",
        "typove cislo servopohonov": "prefix",
        "typ servopohonu.": "actuator_model",
        "typ servopohonu": "actuator_model",
        "druh servopohonu": "actuator_type",
        "ovládanie servopohonu": "control_type",
        "ovladanie servopohonu": "control_type",
        "dokument": "document",
        "page v pdf": "document_page",
    }
    raw_df = raw_df.rename(columns=rename_map)
    if "prefix" not in raw_df.columns:
        raise DataSourceError("Actuator tree missing 'prefix' column")
    raw_df["prefix_normalized"] = raw_df["prefix"].apply(_normalize_prefix)
    return raw_df


def lookup_error(code: Optional[str]) -> Optional[Dict[str, str]]:
    """Return the error definition row for a normalized code."""
    if not code:
        return None
    normalized = _normalize_error_code(code)
    if not normalized:
        return None
    df = load_error_table()
    match = df[df["error_code_normalized"].str.casefold() == normalized.casefold()]
    if match.empty:
        return None
    row = match.iloc[0]
    return {
        "error_number": str(row["error_number"]).strip(),
        "error_name": str(row["error_name"]).strip(),
        "cause": str(row["cause"]).strip(),
        "corrective_action": str(row["corrective_action"]).strip(),
    }


def lookup_actuator(prefix: Optional[str]) -> Optional[Dict[str, str]]:
    """Lookup actuator metadata based on the numeric prefix."""
    if not prefix:
        return None
    normalized = _normalize_prefix(prefix)
    if not normalized:
        return None
    df = load_actuator_table()
    match = df[df["prefix_normalized"].astype(str) == normalized]
    if match.empty:
        return None
    row = match.iloc[0].fillna("")
    return {
        "prefix": str(row.get("prefix", "")).strip(),
        "actuator_model": str(row.get("actuator_model", "")).strip(),
        "actuator_type": str(row.get("actuator_type", "")).strip(),
        "control_type": str(row.get("control_type", "")).strip(),
        "document": str(row.get("document", "")).strip(),
        "document_page": str(row.get("document_page", "")).strip(),
    }
