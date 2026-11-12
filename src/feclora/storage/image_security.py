"""Adapters for standard age encryption and minisign manifest signatures.

This module delegates cryptographic operations to the upstream command-line
programs. It does not implement cryptographic primitives or key derivation.
"""
from __future__ import annotations

from dataclasses import replace
import hashlib
import os
import re
import shutil
import stat
import subprocess
import tempfile

from .image_manifest import ImageArtifact


class ImageSecurityError(RuntimeError):
    """Encryption, decryption, signing, or verification failed."""


def _regular_file(path: str | os.PathLike[str], label: str) -> str:
    value = os.path.abspath(os.fspath(path))
    try:
        info = os.lstat(value)
    except OSError as exc:
        raise ImageSecurityError(f"{label} is unavailable") from exc
    if not stat.S_ISREG(info.st_mode):
        raise ImageSecurityError(f"{label} must be a regular file, not a symlink")
    return value


def _digest_file(path: str) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()



def preflight_image_security(
    *,
    age_recipients_file: str | os.PathLike[str] | None = None,
    minisign_secret_key: str | os.PathLike[str] | None = None,
    age_executable: str | None = None,
    minisign_executable: str | None = None,
) -> None:
    """Validate selected optional image-security inputs before a long capture."""
    if age_recipients_file is not None:
        recipients_path = _regular_file(age_recipients_file, "age recipients file")
        try:
            if os.path.getsize(recipients_path) > 64 * 1024:
                raise ImageSecurityError("age recipients file exceeds the 64 KiB limit")
            with open(recipients_path, encoding="ascii") as stream:
                recipients = [line.strip() for line in stream if line.strip()]
        except (OSError, UnicodeError) as exc:
            raise ImageSecurityError(f"cannot read age recipients file: {exc}") from exc
        if (not recipients or len(recipients) != len(set(recipients))
                or any(not re.fullmatch(r"age1[0-9a-z]{20,}", item) for item in recipients)):
            raise ImageSecurityError("age recipients file is empty, duplicated or contains malformed recipients")
        executable = age_executable or shutil.which("age")
        if not executable:
            raise ImageSecurityError("age executable is required for image encryption")
        if not os.path.isfile(executable) or not os.access(executable, os.X_OK):
            raise ImageSecurityError("configured age executable is unavailable or not executable")
    if minisign_secret_key is not None:
        secret_path = _regular_file(minisign_secret_key, "minisign secret key")
        secret_info = os.stat(secret_path)
        if secret_info.st_mode & 0o077:
            raise ImageSecurityError("minisign secret key must not be accessible by group or other users")
        if secret_info.st_size == 0 or secret_info.st_size > 64 * 1024:
            raise ImageSecurityError("minisign secret key size is outside the permitted range")
        executable = minisign_executable or shutil.which("minisign")
        if not executable:
            raise ImageSecurityError("minisign executable is required for manifest signing")
        if not os.path.isfile(executable) or not os.access(executable, os.X_OK):
            raise ImageSecurityError("configured minisign executable is unavailable or not executable")


def encrypt_artifact(
    artifact_path: str | os.PathLike[str],
    artifact: ImageArtifact,
    recipients_file: str | os.PathLike[str],
    *,
    age_executable: str | None = None,
) -> ImageArtifact:
    """Encrypt one already-compressed artifact to all recipients in a file.

    The recipients file contains public age recipients, one per line. The
    plaintext staging artifact is removed only after successful encryption.
    """
    source = _regular_file(artifact_path, "artifact")
    recipients = _regular_file(recipients_file, "age recipients file")
    age = age_executable or shutil.which("age")
    if not age:
        raise ImageSecurityError("age executable is required for image encryption")
    if artifact.encryption != "none":
        raise ImageSecurityError("artifact is already marked as encrypted")
    encrypted_name = artifact.filename + ".age"
    encrypted_path = os.path.join(os.path.dirname(source), encrypted_name)
    if os.path.lexists(encrypted_path):
        raise ImageSecurityError("encrypted artifact destination already exists")
    fd, temporary = tempfile.mkstemp(prefix=".feclora-age-", dir=os.path.dirname(source))
    os.close(fd)
    os.unlink(temporary)
    try:
        result = subprocess.run(
            [age, "--encrypt", "--recipients-file", recipients, "--output", temporary, source],
            check=False, capture_output=True, text=True, timeout=None,
        )
        if result.returncode != 0:
            detail = (result.stderr or "").strip()[:1000]
            raise ImageSecurityError("age encryption failed" + (f": {detail}" if detail else ""))
        info = os.lstat(temporary)
        if not stat.S_ISREG(info.st_mode) or info.st_size <= 0:
            raise ImageSecurityError("age did not produce a non-empty regular file")
        os.chmod(temporary, 0o600)
        with open(temporary, "rb") as stream:
            os.fsync(stream.fileno())
        size, digest = _digest_file(temporary)
        os.link(temporary, encrypted_path, follow_symlinks=False)
        os.unlink(temporary)
        os.unlink(source)
        directory_fd = os.open(os.path.dirname(source), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        return replace(artifact, filename=encrypted_name, size_bytes=size, sha256=digest, encryption="age")
    except ImageSecurityError:
        raise
    except (OSError, subprocess.SubprocessError) as exc:
        raise ImageSecurityError(f"could not encrypt artifact: {exc}") from exc
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def decrypt_artifact_stream_to_temp(
    encrypted_stream,
    identity_file: str | os.PathLike[str],
    directory: str | os.PathLike[str],
    *,
    age_executable: str | None = None,
) -> str:
    """Decrypt from an already-open verified stream, avoiding path replacement races."""
    identity = _regular_file(identity_file, "age identity file")
    target_dir = os.path.abspath(os.fspath(directory))
    if not stat.S_ISDIR(os.lstat(target_dir).st_mode):
        raise ImageSecurityError("decryption staging path must be a real directory")
    age = age_executable or shutil.which("age")
    if not age:
        raise ImageSecurityError("age executable is required for image decryption")
    fd, temporary = tempfile.mkstemp(prefix=".feclora-decrypted-", dir=target_dir)
    try:
        with os.fdopen(fd, "wb") as output:
            result = subprocess.run(
                [age, "--decrypt", "--identity", identity],
                stdin=encrypted_stream, stdout=output, stderr=subprocess.PIPE,
                check=False, text=False, timeout=None,
            )
            output.flush()
            os.fsync(output.fileno())
        if result.returncode != 0:
            detail = (result.stderr or b"").decode("utf-8", errors="replace").strip()[:1000]
            raise ImageSecurityError("age decryption/authentication failed" + (f": {detail}" if detail else ""))
        info = os.lstat(temporary)
        if not stat.S_ISREG(info.st_mode) or info.st_size <= 0:
            raise ImageSecurityError("age produced no non-empty plaintext artifact")
        os.chmod(temporary, 0o600)
        return temporary
    except ImageSecurityError:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
    except (OSError, subprocess.SubprocessError) as exc:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise ImageSecurityError(f"could not decrypt artifact stream: {exc}") from exc


def decrypt_artifact_to_temp(
    encrypted_path: str | os.PathLike[str],
    identity_file: str | os.PathLike[str],
    directory: str | os.PathLike[str],
    *,
    age_executable: str | None = None,
) -> str:
    """Authenticate and decrypt an age artifact into a private temporary file."""
    source = _regular_file(encrypted_path, "encrypted artifact")
    identity = _regular_file(identity_file, "age identity file")
    target_dir = os.path.abspath(os.fspath(directory))
    if not stat.S_ISDIR(os.lstat(target_dir).st_mode):
        raise ImageSecurityError("decryption staging path must be a real directory")
    age = age_executable or shutil.which("age")
    if not age:
        raise ImageSecurityError("age executable is required for image decryption")
    fd, temporary = tempfile.mkstemp(prefix=".feclora-decrypted-", dir=target_dir)
    os.close(fd)
    os.unlink(temporary)
    try:
        result = subprocess.run(
            [age, "--decrypt", "--identity", identity, "--output", temporary, source],
            check=False, capture_output=True, text=True, timeout=None,
        )
        if result.returncode != 0:
            detail = (result.stderr or "").strip()[:1000]
            raise ImageSecurityError("age decryption/authentication failed" + (f": {detail}" if detail else ""))
        info = os.lstat(temporary)
        if not stat.S_ISREG(info.st_mode) or info.st_size <= 0:
            raise ImageSecurityError("age produced no non-empty plaintext artifact")
        os.chmod(temporary, 0o600)
        with open(temporary, "rb") as stream:
            os.fsync(stream.fileno())
        return temporary
    except ImageSecurityError:
        raise
    except (OSError, subprocess.SubprocessError) as exc:
        raise ImageSecurityError(f"could not decrypt artifact: {exc}") from exc
    finally:
        if os.path.lexists(temporary):
            # On success ownership transfers to the caller.
            import sys
            if sys.exc_info()[0] is not None:
                try:
                    os.unlink(temporary)
                except FileNotFoundError:
                    pass


def sign_manifest(
    manifest_path: str | os.PathLike[str],
    secret_key: str | os.PathLike[str],
    *,
    minisign_executable: str | None = None,
) -> str:
    """Create a detached minisign signature; never overwrite an existing one."""
    manifest = _regular_file(manifest_path, "manifest")
    key = _regular_file(secret_key, "minisign secret key")
    minisign = minisign_executable or shutil.which("minisign")
    if not minisign:
        raise ImageSecurityError("minisign executable is required for manifest signing")
    signature = manifest + ".minisig"
    if os.path.lexists(signature):
        raise ImageSecurityError("manifest signature already exists")
    try:
        result = subprocess.run(
            [minisign, "-S", "-s", key, "-x", signature, "-m", manifest],
            check=False, capture_output=True, text=True,
        )
        if result.returncode != 0:
            detail = (result.stderr or "").strip()[:1000]
            raise ImageSecurityError("minisign signing failed" + (f": {detail}" if detail else ""))
        _regular_file(signature, "minisign signature")
        return signature
    except (OSError, subprocess.SubprocessError) as exc:
        raise ImageSecurityError(f"could not sign manifest: {exc}") from exc


def verify_manifest_signature(
    manifest_path: str | os.PathLike[str],
    public_key: str | os.PathLike[str],
    *,
    signature_path: str | os.PathLike[str] | None = None,
    minisign_executable: str | None = None,
) -> None:
    """Verify a detached signature against an independently trusted public key."""
    manifest = _regular_file(manifest_path, "manifest")
    key = _regular_file(public_key, "minisign public key")
    signature = _regular_file(signature_path or (manifest + ".minisig"), "manifest signature")
    minisign = minisign_executable or shutil.which("minisign")
    if not minisign:
        raise ImageSecurityError("minisign executable is required for signature verification")
    try:
        result = subprocess.run(
            [minisign, "-V", "-m", manifest, "-p", key, "-x", signature],
            check=False, capture_output=True, text=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ImageSecurityError(f"could not verify manifest signature: {exc}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()[:1000]
        raise ImageSecurityError("manifest signature is invalid" + (f": {detail}" if detail else ""))



def decrypt_artifact_stream_with_passphrase_to_temp(
    encrypted_stream,
    passphrase: str,
    directory: str | os.PathLike[str],
    *,
    age_executable: str | None = None,
) -> str:
    """Decrypt a passphrase-encrypted age stream using a private pseudo-terminal.

    The passphrase is sent through the PTY, never argv or environment. The
    encrypted input is exposed to age through the already-open file descriptor.
    """
    import pty
    import tty

    if (not isinstance(passphrase, str) or not passphrase
            or len(passphrase.encode("utf-8")) > 1024
            or any(char in passphrase for char in "\r\n\x00")):
        raise ImageSecurityError("age passphrase must be 1-1024 UTF-8 bytes without line breaks")
    if not hasattr(encrypted_stream, "fileno"):
        raise ImageSecurityError("age encrypted input must be an open file stream")
    target_dir = os.path.abspath(os.fspath(directory))
    if not stat.S_ISDIR(os.lstat(target_dir).st_mode):
        raise ImageSecurityError("decryption staging path must be a real directory")
    age = age_executable or shutil.which("age")
    if not age:
        raise ImageSecurityError("age executable is required for image decryption")
    fd, temporary = tempfile.mkstemp(prefix=".feclora-decrypted-", dir=target_dir)
    master = slave = None
    try:
        master, slave = pty.openpty()
        tty.setraw(slave)
        input_fd = encrypted_stream.fileno()
        command = [age, "--decrypt", "--output", temporary, f"/proc/self/fd/{input_fd}"]
        process = subprocess.Popen(
            command, stdin=slave, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            pass_fds=(input_fd,), close_fds=True,
        )
        os.close(slave)
        slave = None
        os.write(master, passphrase.encode("utf-8") + b"\n")
        _, stderr = process.communicate()
        if process.returncode != 0:
            detail = (stderr or b"").decode("utf-8", errors="replace").strip()[:500]
            raise ImageSecurityError("age passphrase decryption/authentication failed" + (f": {detail}" if detail else ""))
        info = os.lstat(temporary)
        if not stat.S_ISREG(info.st_mode) or info.st_size <= 0:
            raise ImageSecurityError("age produced no non-empty plaintext artifact")
        os.chmod(temporary, 0o600)
        with open(temporary, "rb") as output:
            os.fsync(output.fileno())
        return temporary
    except ImageSecurityError:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
    except (OSError, subprocess.SubprocessError) as exc:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise ImageSecurityError(f"could not decrypt passphrase-encrypted age artifact: {exc}") from exc
    finally:
        if master is not None:
            os.close(master)
        if slave is not None:
            os.close(slave)
