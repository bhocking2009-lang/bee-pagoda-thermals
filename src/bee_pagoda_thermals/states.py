from __future__ import annotations

from enum import Enum


class SafetyState(str, Enum):
    SAFE_CONTROLLABLE = "SAFE_CONTROLLABLE"
    READ_ONLY = "READ_ONLY"
    DEGRADED_SAFE = "DEGRADED_SAFE"
    UNSAFE_UNKNOWN = "UNSAFE_UNKNOWN"


AUTHORITY_BY_STATE: dict[SafetyState, str] = {
    SafetyState.SAFE_CONTROLLABLE: "MANUAL",
    SafetyState.READ_ONLY: "AUTO",
    SafetyState.DEGRADED_SAFE: "FALLBACK",
    SafetyState.UNSAFE_UNKNOWN: "LOCKED",
}
