"""Constant-time HMAC verification of `X-Hub-Signature-256` (AD-17).

A pure function over the raw request bytes: the caller passes the body
before parsing, so a forged payload is rejected without ever being
interpreted. It accepts a tuple of secrets, so webhook-secret rotation
(AD-25) needs no change here.
"""

import hashlib
import hmac

__all__ = ["SIGNATURE_HEADER", "verify_signature"]

SIGNATURE_HEADER = "X-Hub-Signature-256"
_PREFIX = "sha256="
_HEX_DIGEST_LENGTH = 64


def verify_signature(
    raw_body: bytes, signature_header: str | None, secrets: tuple[str, ...]
) -> bool:
    """True when `signature_header` is a valid sha256 HMAC of `raw_body`.

    Missing, malformed or wrong-algorithm headers are False without ever
    touching the body's meaning. Every configured secret is tried in full
    so a rotation overlap accepts either (AD-25).
    """
    if signature_header is None or not signature_header.startswith(_PREFIX):
        return False
    provided = signature_header[len(_PREFIX) :]
    if len(provided) != _HEX_DIGEST_LENGTH or not _is_hex(provided):
        return False
    matched = False
    for secret in secrets:
        expected = hmac.new(
            secret.encode("utf-8"), raw_body, hashlib.sha256
        ).hexdigest()
        matched = hmac.compare_digest(expected, provided) | matched
    return matched


def _is_hex(value: str) -> bool:
    try:
        bytes.fromhex(value)
    except ValueError:
        return False
    return True
