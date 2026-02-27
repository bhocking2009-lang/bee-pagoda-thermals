# Fan Control Slice V1 — Test Evidence

Date: 2026-02-27
Repo: `bhocking2009-lang/bee-pagoda-thermals`
Scope: Dry-run simulator validation for initial vertical slice.

## Executed Scenarios

### 1) Success Path
Command:
```bash
python3 scripts/fan_control_sim.py --scenario success
```
Observed outcomes:
- `scenario`: `success`
- `final_state`: `SAFE_CONTROLLABLE`
- decision action: `allow`
- reason: `write validated`
- fallback executed: `false`
- audit event: `write_success`

### 2) Validation Failure / Lockout Path
Command:
```bash
python3 scripts/fan_control_sim.py --scenario validation-fail-lockout
```
Observed outcomes:
- `scenario`: `validation-fail-lockout`
- `final_state`: `UNSAFE_UNKNOWN`
- decision action: `force_fallback`
- reason: `VALIDATION_FAILED`
- fallback executed: `true`
- state transitions included:
  - `SAFE_CONTROLLABLE -> DEGRADED_SAFE` (fallback start)
  - `DEGRADED_SAFE -> UNSAFE_UNKNOWN` (`EMERGENCY_APPLIED`)
- audit event: `lockout` (severity `critical`)

## CLI Validation
Command:
```bash
python3 scripts/fan_control_sim.py --help
```
Confirmed supported scenarios:
- `success`
- `validation-fail-lockout`

## Signoff Summary
- Nominal path: PASS
- Fail-safe/lockout path: PASS
- Slice V1 behavior aligns with the planned safety model for controllable vs. lockout states.
