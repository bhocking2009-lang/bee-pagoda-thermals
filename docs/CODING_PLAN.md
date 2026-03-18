# Bee Pagoda Thermals — Coding Plan

## Overview

This document is the authoritative coding plan for the project. It maps every
backlog phase to concrete modules, files, interfaces, test targets, and
acceptance criteria. Cross-reference with:

- `docs/IMPLEMENTATION_BACKLOG.md` — phase-level feature list
- `docs/FAN_CONTROL_ARCHITECTURE_V1.md` — module boundary and contract specs
- `docs/FAN_CONTROL_VALIDATION_PLAN_V1.md` — fault-injection and signoff matrix
- `docs/SAFETY_CONTRACT.md` — immutable safety invariants

---

## Status Snapshot

| Phase | Name | Status |
|---|---|---|
| 0 | Foundations | ✅ Done |
| 0.5 | Fan-Control Slice v1 | ✅ Done |
| 1 | Observer-Only MVP | 🔲 Next |
| 2 | Safety Plumbing (remaining) | 🔲 Planned |
| 3 | Minimal Write Path — Pilot | 🔲 Planned |
| 4 | Control UX v1 | 🔲 Planned |
| 5 | Validator Automation | 🔲 Planned |
| 6 | Backend Expansion | 🔲 Planned |

---

## Phase 0 — Foundations (Done)

All deliverables exist in `src/bee_pagoda_thermals/`.

| File | Purpose |
|---|---|
| `contracts.py` | Shared data contracts: `CapabilityReport`, `ControlDecision`, `WriteResult`, `SafetyTransition`, `AuditEvent` |
| `states.py` | `SafetyState` enum and `AUTHORITY_BY_STATE` mapping |
| `policy_engine.py` | Safety state machine, write gate, fallback ladder |
| `helper_client.py` | Allowlisted command dispatcher with structured error mapping |
| `conflict_probe.py` | Process-table conflict detector for competing daemons |

**Tests:** `tests/test_policy_engine.py` (3 scenarios, all green)

**Simulation:** `scripts/fan_control_sim.py` (success + validation-fail-lockout)

---

## Phase 1 — Observer-Only MVP

**Goal:** Read-only telemetry pipeline visible through a text HUD. No write
path involved.

### 1.1 Telemetry Service

**New file:** `src/bee_pagoda_thermals/telemetry.py`

Responsibilities (all read-only, unprivileged):
- Poll hwmon/sysfs paths for temperature, fan RPM, and PWM duty
- Emit normalized `TelemetrySnapshot` structs with timestamps
- Attach quality flags (`stale`, `missing`, `ok`) per sensor
- Never call any write path

Contracts to add to `contracts.py`:

```python
@dataclass(slots=True)
class SensorReading:
    name: str
    value: float
    unit: str               # "°C" | "RPM" | "%" | "raw"
    quality: str            # "ok" | "stale" | "missing"
    path: str               # sysfs path that was read

@dataclass(slots=True)
class TelemetrySnapshot:
    timestamp: datetime
    readings: list[SensorReading]
    backend_id: str
    health: str             # "healthy" | "degraded" | "unavailable"
```

Key methods on `TelemetryService`:

```python
class TelemetryService:
    def __init__(self, hwmon_root: Path = Path("/sys/class/hwmon")) -> None: ...
    def snapshot(self) -> TelemetrySnapshot: ...
    def list_channels(self) -> list[str]: ...
```

Failure mode: missing or unreadable sysfs paths set quality to `"missing"`;
snapshot health drops to `"degraded"` or `"unavailable"` accordingly. Never
raises.

**Tests:** `tests/test_telemetry.py`
- Snapshot with mock sysfs dir returns correct readings and timestamps
- Missing file results in `quality="missing"`, health `"degraded"`
- All readings at once returns health `"healthy"`

### 1.2 Capability Detector

**New file:** `src/bee_pagoda_thermals/capability_detector.py`

Responsibilities:
- Walk `hwmon_root` and probe controllability of each channel
- Determine `write_supported`, `restore_auto_supported` per channel
- Return a `CapabilityReport` (already in `contracts.py`)
- Never perform writes during detection

Key method:

```python
class CapabilityDetector:
    def __init__(self, hwmon_root: Path = Path("/sys/class/hwmon")) -> None: ...
    def detect(self) -> CapabilityReport: ...
```

Channel controllability rules:
- `write_supported = True` only if corresponding PWM file is writable
- `restore_auto_supported = True` only if `pwmN_enable` can be set to `2`
  (auto mode) without error
- Uncertainty defaults to read-only (never assume writable)

**Tests:** `tests/test_capability_detector.py`
- Mock writable hwmon dir → channels marked writable
- Mock read-only hwmon dir → channels marked read-only
- Empty/missing hwmon root → empty `CapabilityReport`

### 1.3 Observer HUD

**New file:** `src/bee_pagoda_thermals/hud.py`

Responsibilities:
- Print a formatted terminal snapshot of current readings, authority state,
  and capability summary
- Show `AUTO` / `MANUAL` / `LOCKED` / `FALLBACK` badge consistently
- No interactive input in this slice (observer-only)

Uses `TelemetryService` and `CapabilityDetector`; receives `SafetyState` from
caller.

```python
class ObserverHUD:
    def render(
        self,
        snapshot: TelemetrySnapshot,
        capability: CapabilityReport,
        state: SafetyState,
    ) -> str: ...
```

Output format: plain text; no external UI library required in this phase.

**Tests:** `tests/test_hud.py`
- `render()` with known inputs produces expected authority badge string
- Render in each `SafetyState` contains the correct authority label

### 1.4 Observer CLI entry point

**New file:** `scripts/observe.py`

A simple non-root CLI:
```
./scripts/observe.py [--interval N]
```
- Prints one HUD snapshot per interval (default 2 s)
- Exits cleanly on Ctrl-C

---

## Phase 2 — Safety Plumbing (Remaining)

Phase 2 completes the runtime safety infrastructure that the policy engine
depends on but that is currently simulated.

### 2.1 Write Rate-Limiter + Hysteresis Gate

**New file:** `src/bee_pagoda_thermals/rate_limiter.py`

Responsibilities:
- Track last-accepted write timestamp per channel
- Reject writes that arrive faster than `min_interval_ms`
- Reject writes whose requested change is smaller than `hysteresis_pct` of
  the current setpoint (prevent oscillatory writes)

```python
@dataclass
class RateLimiterConfig:
    min_interval_ms: int = 500
    hysteresis_pct: float = 2.0

class RateLimiter:
    def __init__(self, config: RateLimiterConfig | None = None) -> None: ...
    def check(self, channel: str, target: int, current: int | None) -> bool: ...
    def record(self, channel: str, target: int) -> None: ...
```

Integration: `PolicyEngine.request_write()` calls `rate_limiter.check()`
before dispatching to the helper. Denied writes emit an `AuditEvent` with
`event_type="write_rate_limited"`.

**Tests:** `tests/test_rate_limiter.py`
- First write always allowed
- Second write within `min_interval_ms` denied
- Change below hysteresis threshold denied
- Change above threshold after interval is allowed

### 2.2 Watchdog

**New file:** `src/bee_pagoda_thermals/watchdog.py`

Responsibilities:
- Time-bound write validation: policy engine arms watchdog before each write;
  watchdog fires if validation callback doesn't complete within
  `verification_window_ms`
- On watchdog fire, invoke a caller-supplied `on_timeout` callback (which
  triggers the fallback ladder)
- Disarm on successful validation

```python
class WriteWatchdog:
    def __init__(self, window_ms: int, on_timeout: Callable[[], None]) -> None: ...
    def arm(self) -> None: ...
    def disarm(self) -> None: ...
```

Uses `threading.Timer` internally. Thread-safe.

**Tests:** `tests/test_watchdog.py`
- Armed watchdog fires `on_timeout` after `window_ms`
- Disarmed watchdog does not fire
- Re-arm after disarm works correctly

### 2.3 Resume / Suspend Guard

**New file:** `src/bee_pagoda_thermals/resume_handler.py`

Responsibilities:
- Hook into `systemd-inhibit` or `DBus` suspend/resume signals (or a
  file-based sentinel for testing)
- On resume signal: force `SafetyState.READ_ONLY` and clear `validated` flag
  in the policy engine
- Emit `AuditEvent(event_type="resume_guard", severity="info")`

```python
class ResumeHandler:
    def __init__(self, engine: PolicyEngine) -> None: ...
    def on_resume(self) -> None: ...
    def start_listener(self) -> None: ...   # non-blocking; uses threading
    def stop_listener(self) -> None: ...
```

For testing, expose `on_resume()` as a callable directly without DBus.

**Tests:** `tests/test_resume_handler.py`
- `on_resume()` forces engine to `READ_ONLY`
- `on_resume()` clears `validated`
- `on_resume()` appends resume audit event

---

## Phase 3 — Minimal Write Path (Pilot)

**Prerequisite:** Phase 1 + 2 complete on certified lab target.

### 3.1 hwmon PWM Backend Adapter

**New file:** `src/bee_pagoda_thermals/backends/__init__.py` (empty)

**New file:** `src/bee_pagoda_thermals/backends/hwmon_pwm.py`

Implements the adapter contract from architecture doc:

```python
class HwmonPwmAdapter:
    backend_id = "hwmon_pwm"

    def __init__(self, hwmon_root: Path = Path("/sys/class/hwmon")) -> None: ...
    def detect_capabilities(self) -> CapabilityReport: ...
    def read_telemetry(self) -> TelemetrySnapshot: ...
    def set_channel_target(self, channel: str, target: int) -> WriteResult: ...
    def restore_auto(self, scope: str = "all") -> WriteResult: ...
    def set_emergency_cooling(self, scope: str = "all") -> WriteResult: ...
    def validate_response(
        self, channel: str, expected: int, window_ms: int
    ) -> bool: ...
```

Hard limits enforced by adapter (not just policy):
- PWM floor: 15% (prevent motor stall)
- Emergency cooling: set PWM to 100%
- Restore auto: write `2` to `pwmN_enable`

**Tests:** `tests/backends/test_hwmon_pwm.py`
- `detect_capabilities()` with mock fs returns correct read/write flags
- `set_channel_target()` writes correct value to mock pwm file
- `restore_auto()` writes `2` to mock `pwmN_enable`
- `set_emergency_cooling()` writes `255` (100%) to mock pwm file
- `validate_response()` returns `True` when readback matches within window

### 3.2 Privileged Helper Service

**New file:** `src/bee_pagoda_thermals/privileged_helper_server.py`

A minimal privileged process (run as root via `systemd` unit or SUID wrapper):
- Listens on a Unix domain socket under `/run/bee-pagoda-thermals/`
- Accepts `CommandEnvelope` JSON over the socket
- Validates command against `ALLOWED_COMMANDS` allowlist before executing
- Calls `HwmonPwmAdapter` methods
- Returns `WriteResult` JSON
- Logs every operation to `/var/log/bee-pagoda-thermals/helper.jsonl`

**New file:** `src/bee_pagoda_thermals/helper_client.py` (extend existing)

Add socket-based transport alongside the existing simulation executor:

```python
class SocketHelperClient(HelperClient):
    def __init__(self, socket_path: str = "/run/bee-pagoda-thermals/helper.sock") -> None: ...
```

**Security requirements:**
- Socket permissions: `0o600`, owned by root
- Calling process must present a Unix credential (UID check)
- No shell execution; adapter calls only

**Tests:** `tests/test_privileged_helper_server.py`
- Allowlisted command returns success result
- Non-allowlisted command returns `WRITE_REJECTED_POLICY`
- Unknown channel returns `WRITE_REJECTED_POLICY`
- UID mismatch returns error (mock credential check)

### 3.3 Panic Action

**New file:** `src/bee_pagoda_thermals/panic_action.py`

Responsibilities:
- Expose a single `return_all_to_auto(engine)` function
- Works from any authority state (including `SAFE_CONTROLLABLE`)
- Calls `restore_auto(scope="all")` through the helper
- Emits `AuditEvent(event_type="panic_action", severity="info")`
- Forces `SafetyState.READ_ONLY` on success, `UNSAFE_UNKNOWN` on failure
- Always callable — must not raise

```python
def return_all_to_auto(engine: PolicyEngine) -> ControlDecision: ...
```

**Tests:** `tests/test_panic_action.py`
- Panic from `SAFE_CONTROLLABLE` → `READ_ONLY`, emits audit event
- Panic from `DEGRADED_SAFE` → `READ_ONLY` on restore success
- Panic where restore fails → `UNSAFE_UNKNOWN`, emits critical audit event
- Panic is auditable in all paths (no silent exit)

---

## Phase 4 — Control UX v1

### 4.1 Profile Manager

**New file:** `src/bee_pagoda_thermals/profiles.py`

Implements three built-in profiles:

| Profile | CPU Fan Target | GPU Fan Target | Notes |
|---|---|---|---|
| Quiet | 30% | 25% | Below ambient comfort level |
| Balanced | 50% | 45% | Default |
| Performance | 80% | 75% | Max allowed non-emergency |

```python
@dataclass(slots=True)
class FanProfile:
    name: str               # "quiet" | "balanced" | "performance"
    targets: dict[str, int] # channel -> PWM target %

BUILTIN_PROFILES: dict[str, FanProfile] = { ... }

def apply_profile(engine: PolicyEngine, profile_name: str) -> list[ControlDecision]: ...
```

**Tests:** `tests/test_profiles.py`
- Applying each profile calls `request_write` with correct targets
- Unknown profile name raises `ValueError`
- Targets are clamped to `PolicyConfig` hard limits

### 4.2 Curve Editor (Guardrailed)

**New file:** `src/bee_pagoda_thermals/curve_editor.py`

Responsibilities:
- Accept a temperature → fan-speed mapping as a list of `(temp_c, pwm_pct)`
  breakpoints
- Validate that curve is monotonically non-decreasing
- Validate that no point falls below the channel's `min_floor`
- Validate that curve covers at least 30°C–80°C range
- Compile curve to a callable `curve_fn(temp: float) -> int`

```python
@dataclass(slots=True)
class CurvePoint:
    temp_c: float
    pwm_pct: int

class FanCurve:
    def __init__(self, points: list[CurvePoint], channel: str) -> None: ...
    def evaluate(self, temp_c: float) -> int: ...

def validate_curve(points: list[CurvePoint], min_floor: int = 15) -> list[str]:
    """Return list of validation errors; empty list means curve is valid."""
    ...
```

**Tests:** `tests/test_curve_editor.py`
- Valid monotonic curve evaluates correctly (linear interpolation)
- Non-monotonic curve fails validation
- Points below floor fail validation
- Gap in required temperature range fails validation

### 4.3 Interactive Terminal UI

**New file:** `src/bee_pagoda_thermals/ui/terminal.py`

Uses Python's built-in `curses` (no external dependency) to render:
- Authority badge: `[AUTO]` / `[MANUAL]` / `[LOCKED]` / `[FALLBACK]`
- Confidence percentage and state name
- Temperature and fan RPM table (one row per sensor)
- Active profile name
- Panic button prompt: `P = Return All to Auto`
- Profile keys: `Q = Quiet`, `B = Balanced`, `F = Performance`

Controls disabled (greyed out) when state is `READ_ONLY` or `UNSAFE_UNKNOWN`.

```python
class TerminalUI:
    def __init__(self, engine: PolicyEngine, telemetry: TelemetryService) -> None: ...
    def run(self) -> None: ...    # blocks; Ctrl-C to exit
```

**Tests:** `tests/ui/test_terminal.py`
- Authority badge renders correct label per `SafetyState`
- Panic key invokes `return_all_to_auto`
- Profile key invokes `apply_profile`

---

## Phase 5 — Validator Automation

### 5.1 Fault Injection Harness

**New file:** `scripts/fault_injection.py`

Runs all FI-01..FI-10 scenarios from the validation plan programmatically:
- Each scenario accepts a `--scenario FI-XX` argument
- Injects the specified fault through helper/adapter mocking
- Outputs structured JSON: `{scenario, transitions, audit_events, final_state, pass}`
- Saves output to `artifacts/validation/<run-id>/fault_injection_report.jsonl`

```python
SCENARIOS: dict[str, Callable[[PolicyEngine], dict]] = {
    "FI-01": run_fi_01_backend_write_rejected,
    "FI-02": run_fi_02_readback_mismatch,
    ...
    "FI-10": run_fi_10_thermal_panic,
}
```

### 5.2 Resume Regression Tests

**New file:** `tests/test_integration_resume.py`

Integration tests for suspend/resume safety:
- Engine in `SAFE_CONTROLLABLE` → `on_resume()` → must be `READ_ONLY`
- Engine in `DEGRADED_SAFE` → `on_resume()` → must be `READ_ONLY`
- Engine in `UNSAFE_UNKNOWN` → `on_resume()` → still `UNSAFE_UNKNOWN`
  (must not auto-recover)

### 5.3 Release Gate CLI

**New file:** `scripts/validate_release.py`

Runs all fault scenarios, checks pass criteria, generates:
- `artifacts/validation/<run-id>/run_manifest.json`
- `artifacts/validation/<run-id>/authority_timeline.jsonl`
- `artifacts/validation/<run-id>/fault_injection_report.md`
- `artifacts/validation/<run-id>/validation_summary.md`

Exits 0 on full pass, 1 on any gate failure.

```
./scripts/validate_release.py --profile saory-b550-5900x-rtx3080
```

---

## Phase 6 — Backend Expansion

### 6.1 NVIDIA GPU Backend

**New file:** `src/bee_pagoda_thermals/backends/nvml.py`

Uses `pynvml` (optional import; graceful fallback if unavailable):
- `detect_capabilities()` queries NVML for fan count and control support
- `set_channel_target()` calls `nvmlDeviceSetFanSpeed_v2()`
- `restore_auto()` calls `nvmlDeviceResetFanSpeed()`

**Tests:** `tests/backends/test_nvml.py` (mock `pynvml`)

### 6.2 AMD GPU Backend

**New file:** `src/bee_pagoda_thermals/backends/amdgpu.py`

Uses `amdgpu` sysfs interface:
- Fan control via `/sys/class/drm/card0/device/hwmon/hwmon*/pwm1`
- Same adapter interface as `HwmonPwmAdapter`

**Tests:** `tests/backends/test_amdgpu.py` (mock sysfs)

### 6.3 Certified Profile Packs

**New files:** `profiles/<machine-id>.json`

JSON profile packs for each certified machine. Fields:
```json
{
  "machine_id": "saory-b550-5900x-rtx3080",
  "channels": {
    "cpu_fan": {"min_floor": 20, "max_limit": 100, "restore_auto_supported": true},
    "chassis_1": {"min_floor": 15, "max_limit": 100, "restore_auto_supported": true},
    "gpu_0": {"min_floor": 25, "max_limit": 100, "restore_auto_supported": true}
  },
  "builtin_profiles": {
    "quiet":       {"cpu_fan": 30, "chassis_1": 25, "gpu_0": 25},
    "balanced":    {"cpu_fan": 50, "chassis_1": 45, "gpu_0": 45},
    "performance": {"cpu_fan": 80, "chassis_1": 75, "gpu_0": 75}
  }
}
```

---

## Cross-Cutting Implementation Rules

These rules apply to every phase and every new file:

1. **Safety invariant**: `SafetyState` can only _decrease_ authority on
   confidence drops. No code path may escalate state without a validated
   startup checklist or explicit re-validation.

2. **No silent failures**: every write attempt, fallback, and state transition
   must produce an `AuditEvent` before returning. Callers must always see a
   structured result, never a bare exception from a helper call.

3. **Read-only by default**: any code that cannot determine controllability
   with certainty must treat the channel as read-only.

4. **Unprivileged surface**: `TelemetryService`, `CapabilityDetector`,
   `PolicyEngine`, and all UI code must be executable without root. Root
   access is confined to `privileged_helper_server.py` only.

5. **Module boundaries**: UI code must never call adapter/backend code
   directly. The only permitted write path is:
   `UI → PolicyEngine → HelperClient → PrivilegedHelperServer → Adapter`.

6. **Test coverage targets**:
   - Unit test every public method on every new class.
   - Integration test every fallback ladder path.
   - All tests must be runnable without hardware (`python -m pytest`).

7. **Dependency budget**: avoid adding external dependencies in Phases 1–3.
   Standard library only. `pynvml` may be added as an optional dep in Phase 6.

---

## File Layout After All Phases

```
src/bee_pagoda_thermals/
    __init__.py
    contracts.py            # Phase 0 + Phase 1 extensions
    states.py               # Phase 0
    policy_engine.py        # Phase 0 + Phase 2 (rate-limiter integration)
    helper_client.py        # Phase 0 + Phase 3 (socket transport)
    conflict_probe.py       # Phase 0
    telemetry.py            # Phase 1
    capability_detector.py  # Phase 1
    hud.py                  # Phase 1
    rate_limiter.py         # Phase 2
    watchdog.py             # Phase 2
    resume_handler.py       # Phase 2
    panic_action.py         # Phase 3
    privileged_helper_server.py  # Phase 3
    profiles.py             # Phase 4
    curve_editor.py         # Phase 4
    backends/
        __init__.py
        hwmon_pwm.py        # Phase 3
        nvml.py             # Phase 6
        amdgpu.py           # Phase 6
    ui/
        __init__.py
        terminal.py         # Phase 4

scripts/
    capture_capabilities.sh # Phase 0
    fan_control_sim.py      # Phase 0
    observe.py              # Phase 1
    fault_injection.py      # Phase 5
    validate_release.py     # Phase 5

tests/
    conftest.py
    test_policy_engine.py   # Phase 0
    test_telemetry.py       # Phase 1
    test_capability_detector.py  # Phase 1
    test_hud.py             # Phase 1
    test_rate_limiter.py    # Phase 2
    test_watchdog.py        # Phase 2
    test_resume_handler.py  # Phase 2
    test_panic_action.py    # Phase 3
    test_privileged_helper_server.py  # Phase 3
    test_integration_resume.py  # Phase 5
    test_profiles.py        # Phase 4
    test_curve_editor.py    # Phase 4
    backends/
        test_hwmon_pwm.py   # Phase 3
        test_nvml.py        # Phase 6
        test_amdgpu.py      # Phase 6
    ui/
        test_terminal.py    # Phase 4

profiles/
    saory-b550-5900x-rtx3080.json  # Phase 6
```

---

## Milestone Summary

| Milestone | Phases | Deliverable |
|---|---|---|
| M1 — Observer Release | 0, 1 | Read-only HUD, telemetry, capability scan |
| M2 — Safety Plumbing | 2 | Watchdog, rate-limiter, resume guard |
| M3 — Pilot Write Release | 3 | One certified writable backend + panic action |
| M4 — Control UX | 4 | Profile switcher, curve editor, terminal UI |
| M5 — Validator | 5 | Automated fault injection + release gate |
| M6 — Multi-Backend | 6 | NVIDIA + AMD GPU backends + profile packs |
