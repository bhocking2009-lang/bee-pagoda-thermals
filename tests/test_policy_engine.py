from __future__ import annotations

from bee_pagoda_thermals.conflict_probe import ConflictProbe
from bee_pagoda_thermals.contracts import CapabilityReport, WriteResult
from bee_pagoda_thermals.helper_client import CommandEnvelope, HelperClient
from bee_pagoda_thermals.policy_engine import PolicyEngine
from bee_pagoda_thermals.states import SafetyState


def _capability_report() -> CapabilityReport:
    return CapabilityReport(
        backend_id="sim",
        channels={"cpu_fan": {"restore_auto_supported": True, "write_supported": True}},
        confidence=1.0,
    )


def test_startup_remains_read_only_until_validated() -> None:
    engine = PolicyEngine(helper_client=HelperClient(), conflict_probe=ConflictProbe())
    engine.startup()

    assert engine.state is SafetyState.READ_ONLY
    denied = engine.request_write("cpu_fan", 40)
    assert denied.action == "deny"

    validated = engine.validate_startup(_capability_report(), engine.conflict_probe.detect([]))
    assert validated is True
    assert engine.state is SafetyState.SAFE_CONTROLLABLE


def test_denied_write_on_unknown_capability() -> None:
    engine = PolicyEngine(helper_client=HelperClient(), conflict_probe=ConflictProbe())
    engine.startup()
    engine.validate_startup(_capability_report(), engine.conflict_probe.detect([]))

    denied = engine.request_write("gpu_9", 60)

    assert denied.action == "deny"
    assert denied.reason == "WRITE_REJECTED_POLICY"


def test_fallback_ladder_invoked_on_validation_failure() -> None:
    calls: list[str] = []

    def executor(envelope: CommandEnvelope) -> WriteResult:
        calls.append(envelope.command)
        if envelope.command == "restore_auto":
            return WriteResult(command="restore_auto", success=False, error_code="RESTORE_AUTO_FAILED")
        return WriteResult(command=envelope.command, success=True)

    engine = PolicyEngine(
        helper_client=HelperClient(executor=executor),
        conflict_probe=ConflictProbe(),
        validation_hook=lambda _result: False,
    )
    engine.startup()
    engine.validate_startup(_capability_report(), engine.conflict_probe.detect([]))

    decision = engine.apply_balanced_profile("cpu_fan", target=50)

    assert decision.action == "force_fallback"
    assert decision.fallback_executed is True
    assert "restore_auto" in calls
    assert "set_emergency_cooling" in calls
    assert engine.state is SafetyState.UNSAFE_UNKNOWN
