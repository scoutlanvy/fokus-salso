"""Immutable timer checkpoints shared by the service and persistence."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ActiveTimer:
    session_id: str
    mode: str
    subject: str
    phase: str
    total_seconds: int
    remaining_seconds: int
    return_to_choice: bool = False
    suspended_focus: "ActiveTimer | None" = None
