from __future__ import annotations

import errno
from dataclasses import dataclass
from typing import Any, Callable

from .contracts import WriteResult


ALLOWED_COMMANDS = {"set_channel_target", "restore_auto", "set_emergency_cooling"}


@dataclass(slots=True)
class CommandEnvelope:
    command: str
    payload: dict[str, Any]


class HelperClient:
    """Narrow helper surface with allowlisted commands and structured errors."""

    def __init__(self, executor: Callable[[CommandEnvelope], WriteResult] | None = None) -> None:
        self._executor = executor or self._simulate_executor

    def execute(self, envelope: CommandEnvelope) -> WriteResult:
        if envelope.command not in ALLOWED_COMMANDS:
            return WriteResult(
                command=envelope.command,
                success=False,
                error_code="WRITE_REJECTED_POLICY",
                detail="command is not allowlisted",
            )

        try:
            return self._executor(envelope)
        except PermissionError as exc:
            return WriteResult(
                command=envelope.command,
                success=False,
                error_code="WRITE_FAILED_BACKEND",
                detail=f"permission error: {exc}",
            )
        except OSError as exc:
            error_code = self._map_os_error(exc.errno)
            return WriteResult(
                command=envelope.command,
                success=False,
                error_code=error_code,
                detail=f"os error: {exc}",
            )
        except Exception as exc:  # pragma: no cover - defensive mapping
            return WriteResult(
                command=envelope.command,
                success=False,
                error_code="WRITE_FAILED_BACKEND",
                detail=f"unexpected helper error: {exc}",
            )

    @staticmethod
    def _map_os_error(err: int | None) -> str:
        if err in (errno.EACCES, errno.EPERM):
            return "WRITE_FAILED_BACKEND"
        if err in (errno.ENODEV, errno.ENOENT):
            return "VALIDATION_FAILED"
        return "WRITE_FAILED_BACKEND"

    @staticmethod
    def _simulate_executor(envelope: CommandEnvelope) -> WriteResult:
        return WriteResult(
            command=envelope.command,
            success=True,
            detail="simulated helper execution",
            readback={"payload": envelope.payload},
        )
