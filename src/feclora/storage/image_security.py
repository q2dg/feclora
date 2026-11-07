"""Adapters for standard age encryption and minisign manifest signatures.

This module delegates cryptographic operations to the upstream command-line
programs. It does not implement cryptographic primitives or key derivation.
"""
from __future__ import annotations

from dataclasses import replace
import hashlib
import os
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
