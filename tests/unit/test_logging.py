import json
import logging

from app.logging_config import JsonFormatter, TextFormatter


def _record(**extra: object) -> logging.LogRecord:
    record = logging.makeLogRecord({"name": "radar", "levelname": "INFO", "msg": "coleta %s"})
    record.args = ("ok",)
    record.__dict__.update(extra)
    return record


def test_json_formatter_inclui_campos_extras() -> None:
    payload = json.loads(JsonFormatter().format(_record(pages=3)))

    assert payload["message"] == "coleta ok"
    assert payload["level"] == "INFO"
    assert payload["pages"] == 3
    assert payload["timestamp"].endswith("+00:00")


def test_text_formatter_inclui_campos_extras() -> None:
    line = TextFormatter().format(_record(pages=3))

    assert "coleta ok" in line
    assert "pages=3" in line
