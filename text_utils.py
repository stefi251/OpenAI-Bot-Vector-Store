from __future__ import annotations

import re
from typing import List, Optional


def clean_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def normalize_error_code(value: Optional[str]) -> Optional[str]:
    text = clean_text(value)
    if not text:
        return None
    text = text.lstrip("Ee")
    text = text.lstrip("0")
    return text or "0"


def normalize_prefix(value: Optional[str]) -> Optional[str]:
    text = clean_text(value)
    if not text:
        return None
    digits = "".join(ch for ch in text if ch.isdigit())
    if digits:
        if len(digits) == 2:
            digits = digits.zfill(3)
        return digits
    return text.upper()


def extract_numeric_token(text: str) -> Optional[str]:
    if not text:
        return None
    for token in text.split():
        cleaned = "".join(ch for ch in token if ch.isdigit())
        if len(cleaned) >= 2:
            return cleaned
    return None


def extract_prefix_candidates(question_text: str) -> List[str]:
    candidates: List[str] = []
    if not question_text:
        return candidates
    for match in re.finditer(r"\d{2,4}", question_text):
        start = match.start()
        lookback = start - 1
        while lookback >= 0 and question_text[lookback].isspace():
            lookback -= 1
        if lookback >= 0 and question_text[lookback].lower() == "e":
            continue
        normalized = normalize_prefix(match.group(0))
        if normalized:
            candidates.append(normalized)
    return candidates
