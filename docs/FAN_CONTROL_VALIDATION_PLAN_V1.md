# Fan Control Validation Plan v1 (Pre-Implementation)

## Purpose
Define validation gates for the first fan-control implementation slice on Linux with safety-first behavior, capability-awareness, and firmware-auto fallback as the default safe outcome.

## Scope
- In scope: first certified writable backend in Pilot phase (single certified machine/profile), fallback ladder behavior, write verification, watchdog interactions, startup/resume safety, panic action, and auditability.
- Out of scope: multi-backend parity, advanced curve UX polish, and automated release tooling beyond manual signoff artifacts.

## Assumptions
- Initial lab target is the currently certified machine profile (ASUS B550 + Ryzen 5900X + RTX 3080).
- System starts in `READ_ONLY` and elevates authority only after capability and safety validation.
- Unknown or ambiguous hardware capability must default to no writes.

## Definition Of Done (First Fan-Control Slice)
All items below must be true to declare first-slice completion.

1. Safety state correctness
- Boot and resume always begin in `READ_ONLY`.
- Transition to `SAFE_CONTROLLABLE` occurs only after successful capability detection and backend validation.
- Any confidence drop transitions to `DEGRADED_SAFE` or `UNSAFE_UNKNOWN`; authority is reduced, never increased.

2. Safe write path behavior
- Writes are accepted only for certified channels and bounded by configured hard limits.
- Rate limiting and hysteresis prevent oscillatory or burst writes.
- Every write is followed by readback and tach response validation within a defined response window.
- Any write/readback mismatch is surfaced (no silent failures).

3. Fallback ladder execution
- On write-path fault, system attempts firmware/BIOS auto restore first.
- Restore attempt and verification are logged with timestamps and result.
- If restore fails, conservative emergency cooling is applied, UI writes are locked, critical alert emitted, and bounded retries occur.
- Repeated restore failure marks `UNSAFE_UNKNOWN`.

4. Operator safety controls
- One-click panic action (`Return All to Auto`) works from all authority states where writes are available.
- UI and logs consistently display authority (`AUTO` / `MANUAL` / `LOCKED` / `FALLBACK`) and confidence state.

5. Evidence and repeatability
- Required logs/artifacts (defined below) are produced for all nominal and fault scenarios.
- Validation runbook can be repeated on the certified target and yields same pass/fail result.

## Fault-Injection Matrix
Minimum matrix for signoff. Each scenario must capture pre-state, trigger, observed transitions, and final safe state.

| ID | Scenario | Injection Method | Expected Safety State/Authority | Expected System Action | Pass Criteria | Fail Criteria |
|---|---|---|---|---|---|---|
| FI-01 | Backend write rejected (permissions/driver) | Deny helper/backend write call | `DEGRADED_SAFE` then `LOCKED` if persistent | Attempt auto restore; lock writes on unresolved error | Restore succeeds or lock+alert emitted within timeout | Any continued manual authority without verified control |
| FI-02 | Readback mismatch after accepted write | Return stale/incorrect readback value | `DEGRADED_SAFE` | Treat as unsafe write, execute fallback ladder | Mismatch detected and surfaced; auto restore attempted | Silent acceptance of mismatched write |
| FI-03 | Tach no-response | Simulate tach unchanged beyond response window | `DEGRADED_SAFE` -> `UNSAFE_UNKNOWN` on repeated failure | Auto restore first; emergency cooling if restore fails | Detection within response window; authority reduced | Write authority retained after no-response |
| FI-04 | Capability detector uncertainty | Remove/alter channel capability signal | `READ_ONLY` or `UNSAFE_UNKNOWN` | Block writes to unknown channel(s) | No writes issued to uncertain channels | Any write attempted on uncertain hardware |
| FI-05 | Startup race/dependency missing | Delay backend initialization on boot | Remains `READ_ONLY` until validated | No early write, explicit status shown | Zero writes before validation complete | Any write before validation completion |
| FI-06 | Resume from suspend with stale state | Force cached state invalidation after resume | Re-enter `READ_ONLY` then re-validate | Re-detect capabilities before control enable | No manual control until re-validation complete | Immediate return to manual without checks |
| FI-07 | Firmware auto restore failure | Force restore command failure | `DEGRADED_SAFE` -> `UNSAFE_UNKNOWN` if repeated | Apply emergency cooling, lock UI writes, retry backoff | Critical alert + locked state + retries recorded | Restore failure not escalated, or writes remain open |
| FI-08 | Panic action under fault | Trigger panic during degraded state | `AUTO` or `FALLBACK` as applicable | Force return-to-auto sequence | Panic succeeds or explicit lock+critical alert on restore fail | Panic reports success without actual authority change |
| FI-09 | Rate-limit violation attempt | Burst sequence of manual write requests | No unsafe state change; bounded processing | Drop/defer excess writes per policy | Effective write rate remains within configured bound | Unbounded writes accepted |
| FI-10 | Thermal panic threshold breach | Inject high-temp signal past panic threshold | `FALLBACK`/locked manual authority | Override profile, apply emergency cooling path | Protective action within threshold latency | Continues normal/manual policy despite panic condition |

## Required Logs And Artifacts For Signoff
All evidence must be timestamped, immutable per run (append-only or checksum-protected), and stored under `artifacts/validation/<run-id>/`.

1. Run metadata
- `run_manifest.json`: run-id, host/profile, kernel version, backend version/hash, operator, start/end time.
- `policy_snapshot.json`: hard limits, response window, retry/backoff parameters, panic thresholds.

2. Capability and authority evidence
- `capability_scan.txt` or structured equivalent showing controllable vs read-only channels.
- `authority_timeline.jsonl`: state transitions (`SAFE_CONTROLLABLE`, `READ_ONLY`, `DEGRADED_SAFE`, `UNSAFE_UNKNOWN`) and authority labels (`AUTO`, `MANUAL`, `LOCKED`, `FALLBACK`).

3. Write-path verification evidence
- `write_attempts.jsonl`: requested write, bounded value, backend result, readback value, tach delta, response-window verdict.
- `fallback_events.jsonl`: restore attempts, verification result, emergency cooling activation, retry counters.

4. Fault injection evidence
- `fault_injection_report.md`: FI scenario IDs run, trigger method, observed result, pass/fail.
- Per-scenario raw traces/log slices referenced by timestamp.

5. Operator-visible evidence
- Screenshots or terminal captures of authority/confidence indicators for: nominal control, degraded path, locked path, and panic action.

6. Summary and attestation
- `validation_summary.md`: gate results, residual risks, explicit signoff decision.
- Signed reviewer checklist (Validator + Implementer roles minimum).

## Pass/Fail Gates
A release candidate for the first slice passes only if all gates pass.

1. Gate A: Safety state integrity
- Pass: all required transitions conform to contract; no authority escalation during reduced confidence.
- Fail: any transition violates “reduce authority on confidence drop”.

2. Gate B: Unknown-hardware safety
- Pass: unknown/uncertain capability channels remain non-writable in all scenarios.
- Fail: any attempted or successful write on unknown channels.

3. Gate C: Write verification correctness
- Pass: 100% of accepted writes have readback+tach validation and explicit verdict.
- Fail: any silent write failure, missing validation, or unreported mismatch.

4. Gate D: Fallback ladder correctness
- Pass: restore-first sequence executed on all injected write faults; unresolved faults end in lock/critical path with retries.
- Fail: missing restore attempt, missing verification, or missing lock on unresolved faults.

5. Gate E: Startup/resume containment
- Pass: startup/resume remain `READ_ONLY` until re-validation completes.
- Fail: any write-capable state before validation completion.

6. Gate F: Panic control reliability
- Pass: panic action consistently drives return-to-auto behavior or explicit locked critical fallback if restore fails.
- Fail: panic indicates success without verified authority change.

7. Gate G: Artifact completeness
- Pass: all required artifacts exist and cross-reference by run-id/timestamp.
- Fail: missing mandatory artifact or untraceable evidence.

## Rollback Criteria
Immediate rollback to observer-only/read-only release posture is required if any condition is met:

- Any Gate A-D failure in validation.
- Any reproduced case where unknown hardware receives writes.
- Any unresolved restore failure path lacking lockout or alerting.
- Inability to produce complete signoff artifacts for a run.
- Post-validation regression in startup/resume safety behavior.

Rollback actions:
1. Disable write authority by default (force `READ_ONLY` runtime policy).
2. Remove/disable pilot writable backend from release candidate.
3. Publish incident note in validation summary with failed gate IDs and reproduction steps.
4. Re-run full matrix from clean baseline before reconsidering write-path enablement.

## Signoff Decision Template
Use this final checklist per run:

- [ ] All FI-01..FI-10 executed and recorded.
- [ ] Gates A..G all pass.
- [ ] No unknown-hardware writes observed.
- [ ] Panic action verified under nominal and degraded conditions.
- [ ] Validator signoff recorded.
- [ ] Implementer signoff recorded.

Decision:
- `PASS` if all checklist items are checked.
- `FAIL` otherwise, with mandatory rollback.
