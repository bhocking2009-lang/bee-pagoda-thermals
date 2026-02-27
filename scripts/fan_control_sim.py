#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from bee_pagoda_thermals.conflict_probe import ConflictProbe
from bee_pagoda_thermals.contracts import CapabilityReport, WriteResult
from bee_pagoda_thermals.helper_client import CommandEnvelope, HelperClient
from bee_pagoda_thermals.policy_engine import PolicyEngine


def build_engine(scenario: str) -> PolicyEngine:
    def executor(envelope: CommandEnvelope) -> WriteResult:
        if envelope.command == "set_channel_target":
            return WriteResult(command=envelope.command, success=True, detail="set accepted")
        if envelope.command == "restore_auto":
            if scenario == "validation-fail-lockout":
                return WriteResult(command=envelope.command, success=False, error_code="RESTORE_AUTO_FAILED")
            return WriteResult(command=envelope.command, success=True, detail="restore ok")
        if envelope.command == "set_emergency_cooling":
            return WriteResult(command=envelope.command, success=True, detail="emergency cooling engaged")
        return WriteResult(command=envelope.command, success=False, error_code="WRITE_REJECTED_POLICY")

    validation_hook = (lambda _result: scenario != "validation-fail-lockout")
    return PolicyEngine(
        helper_client=HelperClient(executor=executor),
        conflict_probe=ConflictProbe(),
        validation_hook=validation_hook,
    )


def run(scenario: str) -> None:
    engine = build_engine(scenario)
    engine.startup()

    cap = CapabilityReport(
        backend_id="sim",
        channels={"cpu_fan": {"restore_auto_supported": True, "write_supported": True}},
        confidence=1.0,
        reasons=["dry-run"],
    )
    engine.validate_startup(capability_report=cap, conflict_report=engine.conflict_probe.detect([]))
    decision = engine.apply_balanced_profile("cpu_fan", target=45)

    print(json.dumps({
        "scenario": scenario,
        "final_state": engine.state.value,
        "decision": asdict(decision),
        "transitions": [asdict(t) for t in engine.transitions],
        "audit_events": [
            {
                "event_type": e.event_type,
                "message": e.message,
                "severity": e.severity,
                "state": e.state,
                "metadata": e.metadata,
            }
            for e in engine.audit_log
        ],
    }, default=str, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Fan-control slice v1 dry-run simulation")
    parser.add_argument(
        "--scenario",
        choices=["success", "validation-fail-lockout"],
        default="success",
        help="Dry-run flow to execute",
    )
    args = parser.parse_args()
    run(args.scenario)


if __name__ == "__main__":
    main()
