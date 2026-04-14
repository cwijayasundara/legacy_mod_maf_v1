"""Shared helpers used by orders and payments."""
import uuid


def normalize(d: dict) -> dict:
    out = dict(d)
    out.setdefault("id", uuid.uuid4().hex)
    return out
