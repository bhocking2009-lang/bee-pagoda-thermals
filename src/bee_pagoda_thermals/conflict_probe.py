from __future__ import annotations

import subprocess
from dataclasses import dataclass


DEFAULT_SIGNATURES = [
    "fancontrol",
    "thermald",
    "asus_fan",
    "liquidctl",
    "coolercontrol",
    "nvidia-settings",
]


@dataclass(slots=True)
class ConflictReport:
    active: bool
    matches: list[str]


class ConflictProbe:
    def __init__(self, signatures: list[str] | None = None) -> None:
        self.signatures = signatures or DEFAULT_SIGNATURES

    def detect(self, process_lines: list[str] | None = None) -> ConflictReport:
        lines = process_lines if process_lines is not None else self._read_process_lines()
        lowered = [line.lower() for line in lines]
        matches = sorted({sig for sig in self.signatures if any(sig in line for line in lowered)})
        return ConflictReport(active=bool(matches), matches=matches)

    @staticmethod
    def _read_process_lines() -> list[str]:
        try:
            output = subprocess.check_output(["ps", "-eo", "comm,args"], text=True)
        except Exception:
            return []
        return [line.strip() for line in output.splitlines() if line.strip()]
