import pytest

from conversation_state import ConversationState


def test_state_from_form_normalizes_values():
    state = ConversationState.from_form("94", "E017", " symptom ")
    assert state.actuator_prefix == "094"
    assert state.error_code == "17"
    assert state.symptoms == "symptom"


def test_state_merge_retains_previous_error_when_missing():
    state = ConversationState(actuator_prefix=None, error_code="19", symptoms=None)
    merged = state.merge("381", None, None)
    assert merged.actuator_prefix == "381"
    assert merged.error_code == "19"


def test_hidden_values_include_all_fields():
    state = ConversationState(actuator_prefix="280", error_code="19", symptoms="buzz")
    hidden = state.hidden()
    assert hidden == ("280", "19", "buzz")
