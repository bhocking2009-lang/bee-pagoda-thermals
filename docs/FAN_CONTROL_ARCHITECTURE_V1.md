# Fan Control Architecture v1

## Purpose
Define a safety-first fan-control architecture for Linux that keeps risky behavior behind policy gates, preserves firmware fallback behavior, and presents clear authority/confidence states in a premium UX.

This version operationalizes:
- Safety contract fallback ladder: auto restore -> emergency cooling -> lockout
- Safety states: SAFE_CONTROLLABLE, READ_ONLY, DEGRADED_SAFE, UNSAFE_UNKNOWN
- Startup/resume default to READ_ONLY
- Conflict detection with `fancontrol`, `thermald`, and vendor daemons/tools

## Module Boundaries

### 1) Telemetry Service (Unprivileged, Read-Only)
Responsibilities:
- Poll temperatures, fan tach/RPM, PWM duty (if exposed), and backend health
- Detect process/service conflicts (`fancontrol`, `thermald`, vendor tools)
- Emit normalized snapshots with timestamps and quality flags
- Never perform control writes

Inputs:
- Sysfs/hwmon/nvml/vendor read APIs
- Process/service table for conflict probes

Outputs:
- `TelemetrySnapshot`
- `ConflictReport`
- `SensorHealthReport`

Failure mode:
- Missing/invalid sensors lower confidence and can force state drop (never increase authority)

### 2) Policy Engine / Safety State Machine (Unprivileged Coordinator)
Responsibilities:
- Own runtime authority state
- Decide whether a requested write may proceed
- Execute fallback ladder when write confidence or verification fails
- Rate-limit and hysteresis-gate all requested setpoint changes
- Persist audit trail for each control attempt and transition

Inputs:
- Telemetry snapshots
- Capability model from backend adapter
- User intent (profile/curve/panic/return-to-auto)
- Startup/resume events

Outputs:
- `ControlDecision` (`allow`, `deny`, `defer`, `force_fallback`)
- `SafetyTransition`
- `AuditEvent`

Failure mode:
- On policy uncertainty, move toward READ_ONLY/DEGRADED_SAFE, then UNSAFE_UNKNOWN if recovery fails

### 3) Privileged Helper (Minimal Root Surface)
Responsibilities:
- Execute a narrow allowlist of backend control operations
- Perform restore-to-auto and emergency cooling operations
- Return structured result codes (no silent failure)
- Enforce per-channel floors/caps from certified profile

Inputs:
- Signed/validated command envelope from policy engine

Outputs:
- `WriteResult` with errno-like category + backend detail
- Readback samples gathered immediately post-write

Failure mode:
- Any helper/backend error bubbles to policy engine for fallback ladder execution

### 4) UI Integration Layer (Premium UX, Safety-Transparent)
Responsibilities:
- Render authority: `AUTO`, `MANUAL`, `LOCKED`, `FALLBACK`
- Render confidence/safety state explicitly
- Gate interactive controls based on state/capability
- Offer one-click panic: Return All to Auto

Inputs:
- State machine state + audit summary + capability exposure

Outputs:
- Intent events only (no direct backend calls)

Failure mode:
- UI cannot bypass policy/helper; a stale UI must fail closed

## Backend Adapter Contract and Capability Model

### Adapter Interface (Conceptual)
Each backend implementation (e.g., hwmon PWM, GPU vendor path) must provide:
- `detect_capabilities() -> CapabilityReport`
- `read_telemetry() -> AdapterTelemetry`
- `set_channel_target(channel, target) -> AdapterWriteResult`
- `restore_auto(channel|all) -> AdapterWriteResult`
- `set_emergency_cooling(channel|all) -> AdapterWriteResult`
- `validate_response(channel, expected, window_ms) -> ValidationResult`

### Capability Model
`CapabilityReport` minimum fields:
- `backend_id`: stable adapter identifier
- `channels[]`: controllable units (cpu_fan, chassis_1, gpu_0, etc.)
- `channel.mode_support`: `auto`, `manual_pwm`, `manual_rpm` (subset)
- `channel.min_floor`: minimum safe PWM/RPM floor
- `channel.max_limit`: upper limit (if constrained)
- `channel.readback_supported`: bool
- `channel.restore_auto_supported`: bool
- `channel.emergency_supported`: bool
- `verification_window_ms`: recommended response window
- `certification_level`: `uncertified`, `lab_certified`, `production_certified`
- `confidence`: adapter confidence score + reasons

Rules:
- Policy engine only exposes writable controls for channels with explicit write support
- Missing `restore_auto_supported` downgrades authority (cannot claim SAFE_CONTROLLABLE)
- Missing readback/validation support permits at most DEGRADED_SAFE writes (if explicitly allowed by policy), otherwise READ_ONLY

## Write Safety Pipeline (Textual Sequence)
Requested operation: user applies profile/curve/manual change.

1. UI emits intent to policy engine (`desired target`, `channel scope`, `source=user/profile`).
2. Policy engine checks current state and capability gates.
3. Policy engine checks conflict report; active conflict forces deny or fallback path.
4. Policy engine applies rate-limit/hysteresis and hard-limit clamps.
5. Policy engine sends signed `set_channel_target` command to privileged helper.
6. Helper executes adapter write.
7. Helper immediately performs readback/validation window sampling.
8. Helper returns structured result + validation verdict.
9. Policy engine evaluates outcome:
   - Success path: emit audit event, remain/enter SAFE_CONTROLLABLE.
   - Failure path: execute fallback ladder:
     1) `restore_auto`
     2) verify response window
     3) if restore failed, apply emergency cooling
     4) lock writes, raise critical alert
     5) retry restore with backoff
     6) mark UNSAFE_UNKNOWN after repeated failure
10. UI updates authority/confidence badges and disables controls if locked/read-only.

## State Transitions and Error Handling

### Canonical State Meanings
- `READ_ONLY`: telemetry allowed, all writes blocked
- `SAFE_CONTROLLABLE`: writes allowed under policy + validation
- `DEGRADED_SAFE`: limited writes/forced conservative mode while attempting recovery
- `UNSAFE_UNKNOWN`: lockout, critical alert, recovery-only operations

### Required Transitions
- Startup -> `READ_ONLY`
- Resume from suspend/hibernate -> `READ_ONLY`
- `READ_ONLY` -> `SAFE_CONTROLLABLE` only after:
  - capabilities detected
  - no active conflict
  - restore-auto path proven available
  - telemetry health and validation checks pass
- Any state -> `READ_ONLY` on transient uncertainty (sensor dropout, adapter restart)
- `SAFE_CONTROLLABLE` -> `DEGRADED_SAFE` on failed write validation or partial backend failure
- `DEGRADED_SAFE` -> `SAFE_CONTROLLABLE` after successful recovery verification window
- `DEGRADED_SAFE` -> `UNSAFE_UNKNOWN` after repeated fallback failure
- `UNSAFE_UNKNOWN` -> `READ_ONLY` only after explicit recovery checks succeed

### Error Classes
- `CONFLICT_ACTIVE`: competing daemon/tool detected
- `WRITE_REJECTED_POLICY`: violates floor/rate/hysteresis/capability
- `WRITE_FAILED_BACKEND`: adapter/helper execution failure
- `VALIDATION_FAILED`: readback/tach did not respond in window
- `RESTORE_AUTO_FAILED`: cannot restore firmware behavior
- `EMERGENCY_APPLIED`: emergency cooling engaged
- `LOCKOUT_ASSERTED`: writes disabled pending recovery

Handling invariant:
- No error path may silently preserve manual authority; every failure must emit audit + visible UI state change.

## First Implementation Slice (Small but Real)

Scope: implement a vertical slice that is shippable as a pilot on one certified backend.

### Slice Goal
Support one writable channel group with end-to-end safety plumbing:
- startup in READ_ONLY
- capability detection
- conflict detection
- one controlled write action (`Apply Balanced Profile`)
- readback validation
- panic `Return All to Auto`
- fallback ladder to lockout if needed

### In-Scope Components
- Policy engine state machine with four states
- Minimal privileged helper allowlist:
  - `set_channel_target`
  - `restore_auto(all)`
  - `set_emergency_cooling(all)`
- Single backend adapter (first certified lab target)
- Audit event schema + log sink
- UI badges and disabled-state behavior

### Explicitly Out of Scope (for this slice)
- Full custom curve editor
- Multi-backend arbitration
- Advanced retry tuning/fault injection harness
- Additional GPU/platform adapters

### Coordinator/Coder Task Breakdown
1. Define data contracts (`CapabilityReport`, `ControlDecision`, `WriteResult`, `SafetyTransition`, `AuditEvent`).
2. Implement startup/resume guard: force READ_ONLY until validation checklist passes.
3. Implement conflict probe module for `fancontrol`, `thermald`, vendor process signatures.
4. Implement policy checks: floor clamps, write rate-limit, hysteresis gate.
5. Implement helper command allowlist and structured error codes.
6. Wire write->readback validation->fallback ladder.
7. Expose UI authority/confidence + panic action.
8. Add integration tests for:
   - successful write path
   - restore-auto recovery
   - emergency cooling path
   - lockout transition to UNSAFE_UNKNOWN

### Definition of Done (Slice)
- Demonstrated SAFE_CONTROLLABLE only after startup checklist passes
- At least one forced validation failure shows full ladder execution and UI lockout
- No silent write failures in logs or UI
- Panic action always callable and auditable
