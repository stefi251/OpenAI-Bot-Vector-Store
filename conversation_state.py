from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from text_utils import clean_text, normalize_error_code, normalize_prefix


@dataclass
class ConversationState:
    actuator_prefix: Optional[str] = None
    error_code: Optional[str] = None
    symptoms: Optional[str] = None

    @classmethod
    def from_form(
        cls,
        prefix: Optional[str],
        error_code: Optional[str],
        symptoms: Optional[str],
    ) -> "ConversationState":
        return cls(
            actuator_prefix=normalize_prefix(prefix) or None,
            error_code=normalize_error_code(error_code),
            symptoms=clean_text(symptoms),
        )

    def merge(self, parsed_prefix: Optional[str], parsed_error: Optional[str], parsed_symptoms: Optional[str]) -> "ConversationState":
        return ConversationState(
            actuator_prefix=parsed_prefix or self.actuator_prefix,
            error_code=parsed_error or self.error_code,
            symptoms=parsed_symptoms or self.symptoms,
        )

    def hidden(self) -> Tuple[str, str, str]:
        return (
            self.actuator_prefix or "",
            self.error_code or "",
            self.symptoms or "",
        )

    def requires_error_code(self, intelligent: bool) -> bool:
        return intelligent and not self.error_code
