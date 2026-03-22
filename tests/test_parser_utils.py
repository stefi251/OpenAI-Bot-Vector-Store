import types

import pytest

import parser_utils


def test_parse_json_blob_handles_fenced_json():
    blob = "```json\n{\"foo\": \"bar\"}\n```"
    result = parser_utils._parse_json_blob(blob)  # noqa: SLF001
    assert result == {"foo": "bar"}


def test_parse_diagnostics_retries_and_raises(monkeypatch):
    calls = {"count": 0}

    def fake_request(question, client, model):  # noqa: ANN001
        calls["count"] += 1
        raise parser_utils.ParserDataError("bad payload")

    monkeypatch.setattr(parser_utils, "_request_parser_payload", fake_request)
    with pytest.raises(parser_utils.ParserDataError):
        parser_utils.parse_diagnostics("q", object(), "model", attempts=2)
    assert calls["count"] == 2
