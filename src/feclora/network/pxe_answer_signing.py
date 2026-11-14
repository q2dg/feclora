"""Minisign helpers for authenticating unattended PXE answer files."""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path


class PXEAnswerSignatureError(RuntimeError):
    """A PXE answer signature could not be created or verified."""


PRIVATE_KEY = Path("/etc/feclora/pki/pxe-answer.key")
PUBLIC_KEY = Path("/etc/feclora/pxe-answer.pub")


def _checked_key(path: str | os.PathLike[str], *, private: bool) -> Path:
    key = Path(path)
    try:
        info = os.lstat(key)
    except OSError as exc:
        label = "signing" if private else "verification"
        raise PXEAnswerSignatureError(f"PXE answer {label} key is unavailable: {exc}") from exc
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise PXEAnswerSignatureError("PXE answer key must be a regular, non-symlink file")
    if info.st_uid != os.geteuid():
        raise PXEAnswerSignatureError("PXE answer key must be owned by the Feclora service account")
    if private and info.st_mode & 0o077:
        raise PXEAnswerSignatureError("PXE answer private key must not be accessible by group or other users")
    if not private and info.st_mode & 0o022:
        raise PXEAnswerSignatureError("PXE answer public key must not be writable by group or other users")
    if info.st_size == 0 or info.st_size > 4096:
        raise PXEAnswerSignatureError("PXE answer key file must be non-empty and at most 4 KiB")
    return key


def _minisign() -> str:
    executable = shutil.which("minisign")
    if not executable:
        raise PXEAnswerSignatureError("minisign is required for authenticated PXE answers")
    return executable


def sign_answer_file(message: str | os.PathLike[str], signature: str | os.PathLike[str], *,
                     private_key: str | os.PathLike[str] = PRIVATE_KEY) -> Path:
    """Sign an answer using a root-protected, unencrypted minisign private key."""
    key = _checked_key(private_key, private=True)
    message_path, signature_path = Path(message), Path(signature)
    try:
        result = subprocess.run(
            [_minisign(), "-S", "-s", str(key), "-m", str(message_path),
             "-x", str(signature_path), "-t", "Feclora PXE unattended answer"],
            check=False, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise PXEAnswerSignatureError(f"minisign could not sign the PXE answer: {exc}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise PXEAnswerSignatureError(f"minisign rejected the PXE signing key: {detail or result.returncode}")
    try:
        info = os.lstat(signature_path)
    except OSError as exc:
        raise PXEAnswerSignatureError("minisign did not create the detached signature") from exc
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_uid != os.geteuid():
        raise PXEAnswerSignatureError("minisign created an unsafe signature file")
    os.chmod(signature_path, 0o600)
    return signature_path


def verify_answer_file(message: str | os.PathLike[str], signature: str | os.PathLike[str], *,
                       public_key: str | os.PathLike[str] = PUBLIC_KEY) -> None:
    """Verify a detached signature against the public key trusted by this Live image."""
    key = _checked_key(public_key, private=False)
    message_path, signature_path = Path(message), Path(signature)
    try:
        result = subprocess.run(
            [_minisign(), "-V", "-m", str(message_path), "-x", str(signature_path), "-p", str(key)],
            check=False, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise PXEAnswerSignatureError(f"minisign could not verify the PXE answer: {exc}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise PXEAnswerSignatureError(f"PXE answer signature verification failed: {detail or result.returncode}")
