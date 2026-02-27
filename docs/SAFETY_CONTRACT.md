# Bee Pagoda Fan Control — Safety Contract v1

## Core Principle
If confidence drops, control authority is reduced, never increased.

## Safety States
- SAFE_CONTROLLABLE
- READ_ONLY
- DEGRADED_SAFE
- UNSAFE_UNKNOWN

## Error Fallback Ladder
1. Restore firmware/BIOS auto mode (backend-specific)
2. Verify response window
3. If restore fails, apply conservative emergency cooling
4. Lock UI writes + emit critical alert
5. Retry restore with backoff
6. Mark UNSAFE_UNKNOWN after repeated failure

## Hard Limits
- Per-channel min PWM/RPM floors
- Thermal panic thresholds
- Write rate limiting + hysteresis
- No silent write failures

## Startup/Resume
- Start in READ_ONLY
- Re-detect + re-validate
- Only then allow SAFE_CONTROLLABLE

## UX Requirements
- Always show authority: AUTO / MANUAL / LOCKED / FALLBACK
- Expose confidence state
- One-click panic: Return All to Auto
