# Bee Pagoda Thermals

Safe, capability-aware Linux thermal observability and fan control with a premium HUD UX.

## Problem
Linux thermal/fan control is fragmented across firmware, kernel drivers, hardware vendors, and distro defaults. Existing tools are often either low-level/risky or visually unpolished.

## Goal
Deliver a product former Windows users can trust:
- premium UI/UX
- truthful capabilities (controllable vs read-only)
- safety-first controls that fail back to firmware behavior

## Current Scope (v0)
- observer-first telemetry
- machine certification workflow
- safety contract enforcement
- per-system capability profiles

## Initial Certified Lab Targets
1. ASUS B550 + Ryzen 5900X + RTX 3080 (this machine)
2. AMD + RX 6700 (planned)
3. AMD + RX 7900 (planned)

## Quick Start
```bash
./scripts/capture_capabilities.sh
```

Artifacts are written under `artifacts/`.
