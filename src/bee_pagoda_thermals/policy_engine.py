from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .conflict_probe import ConflictProbe, ConflictReport
from .contracts import AuditEvent, CapabilityReport, ControlDecision, SafetyTransition, WriteResult
from .helper_client import CommandEnvelope, HelperClient
from .states import SafetyState


@dataclass(slots=True)
class PolicyConfig:
    max_target: int = 100
    min_target: int = 0


class PolicyEngine:
    def __init__(
        self,
        helper_client: HelperClient,
        conflict_probe: ConflictProbe,
        config: PolicyConfig | None = None,
        validation_hook: Callable[[WriteResult], bool] | None = None,
    ) -> None:
        self.helper_client = helper_client
        self.conflict_probe = conflict_probe
        self.config = config or PolicyConfig()
        self.validation_hook = validation_hook or (lambda result: result.success)

        self.state = SafetyState.READ_ONLY
        self.capability_report: CapabilityReport | None = None
        self.transitions: list[SafetyTransition] = []
        self.audit_log: list[AuditEvent] = []
        self.validated = False

    def startup(self) -> None:
        self.validated = False
        self._transition(SafetyState.READ_ONLY, "startup guard")

    def validate_startup(self, capability_report: CapabilityReport, conflict_report: ConflictReport) -> bool:
        self.capability_report = capability_report

        has_channels = bool(capability_report.channels)
        has_restore = all(
            bool(details.get("restore_auto_supported", False))
            for details in capability_report.channels.values()
        )

        self.validated = has_channels and has_restore and not conflict_report.active
        if self.validated:
            self._transition(SafetyState.SAFE_CONTROLLABLE, "startup validation passed")
        else:
            self._transition(SafetyState.READ_ONLY, "startup validation failed")
        return self.validated

    def apply_balanced_profile(self, channel: str, target: int = 50) -> ControlDecision:
        return self.request_write(channel=channel, target=target, source="profile:balanced")

    def request_write(self, channel: str, target: int, source: str = "user") -> ControlDecision:
        if self.state is SafetyState.UNSAFE_UNKNOWN:
            return self._deny(channel, target, "LOCKOUT_ASSERTED")

        if not self.validated or self.state is SafetyState.READ_ONLY:
            return self._deny(channel, target, "WRITE_REJECTED_POLICY")

        if not self.capability_report or channel not in self.capability_report.channels:
            return self._deny(channel, target, "WRITE_REJECTED_POLICY")

        bounded_target = max(self.config.min_target, min(self.config.max_target, target))
        write_result = self.helper_client.execute(
            CommandEnvelope(
                command="set_channel_target",
                payload={"channel": channel, "target": bounded_target, "source": source},
            )
        )
        if not write_result.success:
            return self._run_fallback_ladder(channel, bounded_target, write_result.error_code or "WRITE_FAILED_BACKEND")

        if not self.validation_hook(write_result):
            return self._run_fallback_ladder(channel, bounded_target, "VALIDATION_FAILED")

        self.audit_log.append(
            AuditEvent(
                event_type="write_success",
                message="write accepted and validated",
                severity="info",
                state=self.state.value,
                metadata={"channel": channel, "target": bounded_target},
            )
        )
        return ControlDecision(
            action="allow",
            reason="write validated",
            state=self.state.value,
            channel=channel,
            target=bounded_target,
        )

    def _run_fallback_ladder(self, channel: str, target: int, reason: str) -> ControlDecision:
        self._transition(SafetyState.DEGRADED_SAFE, f"fallback start: {reason}")

        restore_result = self.helper_client.execute(CommandEnvelope(command="restore_auto", payload={"scope": "all"}))
        if restore_result.success and self.validation_hook(restore_result):
            self._transition(SafetyState.READ_ONLY, "restore_auto recovered")
            self.validated = False
            return ControlDecision(
                action="force_fallback",
                reason="RESTORE_AUTO_RECOVERED",
                state=self.state.value,
                channel=channel,
                target=target,
                fallback_executed=True,
            )

        emergency_result = self.helper_client.execute(
            CommandEnvelope(command="set_emergency_cooling", payload={"scope": "all"})
        )
        emergency_reason = emergency_result.error_code or "EMERGENCY_APPLIED"
        self._transition(SafetyState.UNSAFE_UNKNOWN, emergency_reason)
        self.validated = False
        self.audit_log.append(
            AuditEvent(
                event_type="lockout",
                message="fallback ladder ended in lockout",
                severity="critical",
                state=self.state.value,
                metadata={"channel": channel, "target": target, "reason": reason},
            )
        )
        return ControlDecision(
            action="force_fallback",
            reason=reason,
            state=self.state.value,
            channel=channel,
            target=target,
            fallback_executed=True,
        )

    def _deny(self, channel: str, target: int, reason: str) -> ControlDecision:
        self.audit_log.append(
            AuditEvent(
                event_type="write_denied",
                message=reason,
                severity="warning",
                state=self.state.value,
                metadata={"channel": channel, "target": target},
            )
        )
        return ControlDecision(
            action="deny",
            reason=reason,
            state=self.state.value,
            channel=channel,
            target=target,
        )

    def _transition(self, to_state: SafetyState, reason: str) -> None:
        from_state = self.state
        self.state = to_state
        self.transitions.append(
            SafetyTransition(from_state=from_state.value, to_state=to_state.value, reason=reason)
        )
