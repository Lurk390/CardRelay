import logging
import re
from typing import Any

SENSITIVE_KEYS = re.compile(
    r"authorization|cookie|password|token|storage.?state|certification", re.I
)


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if SENSITIVE_KEYS.search(str(key)) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(level=level, format="%(levelname)s %(name)s %(message)s")
