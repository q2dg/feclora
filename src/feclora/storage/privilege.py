"""Privilege boundary for block-device imaging subprocesses."""
from __future__ import annotations
import os
import shutil
from collections.abc import Callable, Sequence


class PrivilegeError(RuntimeError):
    """Required non-interactive root privileges are unavailable."""


def privileged_argv(
    argv: Sequence[str],
    *,
    effective_uid: Callable[[], int] | None = None,
    which: Callable[[str], str | None] | None = None,
) -> list[str]:
    """Return argv that runs as root without a shell or interactive prompt."""
    if not argv or not all(isinstance(item, str) and item for item in argv):
        raise PrivilegeError("a non-empty executable argument vector is required")
    uid = (effective_uid or os.geteuid)()
    if uid == 0:
        return list(argv)
    sudo = (which or shutil.which)("sudo")
    if not sudo:
        raise PrivilegeError("sudo is required for block-device access")
    return [sudo, "-n", "--", *argv]
