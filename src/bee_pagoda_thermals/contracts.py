from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class CapabilityReport:
    backend_id: str
    channels: dict[str, dict[str, Any]]
    verification_window_ms: int = 1000
    certification_level: str = "uncertified"
    confidence: float = 0.0
    reasons: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ControlDecision:
    action: str
    reason: str
    state: str
    channel: str | None = None
    target: int | None = None
    fallback_executed: bool = False


@dataclass(slots=True)
class WriteResult:
    command: str
    success: bool
    error_code: str | None = None
    detail: str = ""
    readback: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SafetyTransition:
    from_state: str
    to_state: str
    reason: str
    timestamp: datetime = field(default_factory=_utc_now)


@dataclass(slots=True)
class AuditEvent:
    event_type: str
    message: str
    severity: str
    state: str
    timestamp: datetime = field(default_factory=_utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)
