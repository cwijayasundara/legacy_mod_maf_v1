from __future__ import annotations

from enum import Enum


class DDBStatus(str, Enum):
    CREATED = "CREATED"
    EXCEPTION = "EXCEPTION"


class EventType(str, Enum):
    UPSTREAM = "UPSTREAM"
    MERGE_EVIDENCE = "MERGE_EVIDENCE"
    ORDER_RESUBMIT = "ORDER_RESUBMIT"
