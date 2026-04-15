from __future__ import annotations

from enum import Enum


class DDBStatus(str, Enum):
    CREATED = "CREATED"
    TRANSFORMED = "TRANSFORMED"
    VALIDATED = "VALIDATED"
    QUEUED = "QUEUED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    EXCEPTION = "EXCEPTION"
    RETRY = "RETRY"
