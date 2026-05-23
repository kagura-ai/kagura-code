from __future__ import annotations

import logging

from kagura_code.logging import RedactingFormatter, setup_logging


def test_redacting_formatter_strips_sk_keys():
    f = RedactingFormatter("%(message)s")
    rec = logging.LogRecord(
        name="x", level=logging.INFO, pathname="", lineno=0,
        msg="API key sk-abc123def456 was sent", args=(), exc_info=None,
    )
    out = f.format(rec)
    assert "sk-abc123def456" not in out
    assert "***REDACTED***" in out


def test_setup_logging_returns_logger_with_level(tmp_path):
    log = setup_logging(level="info", log_file=tmp_path / "launcher.log")
    assert log.level == logging.INFO
    log.info("hello")
    contents = (tmp_path / "launcher.log").read_text()
    assert "hello" in contents


def test_setup_logging_redacts_in_file_output(tmp_path):
    log = setup_logging(level="info", log_file=tmp_path / "launcher.log")
    log.info("token = sk-secret123abc456")
    contents = (tmp_path / "launcher.log").read_text()
    assert "sk-secret123abc456" not in contents
    assert "***REDACTED***" in contents
