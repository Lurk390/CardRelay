import hashlib
import json
import re
import unicodedata

FINGERPRINT_VERSION = "v1"


def normalize_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = unicodedata.normalize("NFKC", value).strip().casefold()
    return re.sub(r"\s+", " ", normalized) or None


def normalize_collector_number(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).strip().upper().replace(" ", "")
    if "/" in value:
        value = value.split("/", 1)[0]
    match = re.fullmatch(r"0*(\d+)([A-Z]*)", value)
    return f"{int(match.group(1))}{match.group(2)}" if match else value


def stable_fingerprint(fields: dict[str, object]) -> str:
    payload = json.dumps(fields, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return f"{FINGERPRINT_VERSION}:{hashlib.sha256(payload.encode()).hexdigest()}"
