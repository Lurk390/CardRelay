from card_relay.logging import redact


def test_sensitive_values_are_redacted_recursively() -> None:
    assert redact({"cookie": "secret", "nested": {"token": "secret", "count": 2}}) == {
        "cookie": "[REDACTED]",
        "nested": {"token": "[REDACTED]", "count": 2},
    }
