from __future__ import annotations

from pathlib import Path

from teams_assistant.logging_setup import get_logger, redact, setup_logging

SECRETS = [
    "Authorization: Bearer abcDEF123.token-value",
    "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N",
    "api_key=sk-ant-0123456789abcdefghij",
    '{"refresh_token": "0.ARoAv4j5cvGGr0GRqy180BHbR"}',
    "password=Sup3rSecret!",
]


def test_redact_masks_known_secret_formats() -> None:
    for secret in SECRETS:
        masked = redact(secret)
        assert "***" in masked, secret
    assert "Sup3rSecret" not in redact("password=Sup3rSecret!")
    assert "0.ARoAv4j5" not in redact(SECRETS[3])


def test_log_file_contains_no_secret(tmp_path: Path) -> None:
    setup_logging(tmp_path, "DEBUG")
    log = get_logger("test")
    for secret in SECRETS:
        log.info("valeur reçue : %s", secret)
    for handler in log.parent.handlers if log.parent else []:
        handler.flush()
    content = (tmp_path / "app.log").read_text(encoding="utf-8")
    for fragment in ["abcDEF123", "dozjgNryP4J3", "sk-ant-0123", "ARoAv4j5", "Sup3rSecret"]:
        assert fragment not in content
