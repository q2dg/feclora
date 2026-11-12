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



def encrypt_artifact_with_passphrase(
    artifact_path: str | os.PathLike[str],
    artifact: ImageArtifact,
    passphrase: str,
    *,
    age_executable: str | None = None,
) -> ImageArtifact:
    """Encrypt one compressed artifact using age's interactive passphrase mode.

    The passphrase is supplied only through age's controlling terminal. It is
    never included in argv, environment variables, temporary files or logs.
    """
    import errno
    import pty
    import select
    import signal
    import time
    import tty

    source = _regular_file(artifact_path, "artifact")
    if (not isinstance(passphrase, str) or not passphrase
            or len(passphrase.encode("utf-8")) > 1024
            or any(char in passphrase for char in "\r\n\x00")):
        raise ImageSecurityError("age passphrase must be 1-1024 UTF-8 bytes without line breaks")
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
    os.fchmod(fd, 0o600)
    os.close(fd)
    master = None
    child_pid = None
    wait_status = None
    sent = 0
    transcript = bytearray()
    committed = False
    try:
        child_pid, master = pty.fork()
        if child_pid == 0:
            try:
                tty.setraw(0)
                os.umask(0o077)
                os.execv(age, [age, "--passphrase", "--output", temporary, source])
            except BaseException as exc:
                try:
                    os.write(2, f"age exec failed: {exc}\n".encode("utf-8", errors="replace"))
                finally:
                    os._exit(127)
        deadline = time.monotonic() + 180.0
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ImageSecurityError("age encryption timed out while waiting for terminal input")
            readable, _, _ = select.select([master], [], [], min(0.25, remaining))
            if readable:
                try:
                    chunk = os.read(master, 4096)
                except OSError as exc:
                    if exc.errno == errno.EIO:
                        chunk = b""
                    else:
                        raise
                if chunk:
                    transcript.extend(chunk)
                    if len(transcript) > 8192:
                        del transcript[:-8192]
                    # age's encryption prompt includes explanatory text
                    # between "passphrase" and the trailing colon.
                    prompt = re.search(
                        rb"(?:enter|confirm)[^\r\n]{0,160}passphrase[^\r\n]{0,160}:\s*$",
                        bytes(transcript), re.IGNORECASE,
                    )
                    if prompt and sent < 2:
                        os.write(master, passphrase.encode("utf-8") + b"\n")
                        sent += 1
                        transcript.clear()
                elif wait_status is not None:
                    break
            waited, status = os.waitpid(child_pid, os.WNOHANG)
            if waited == child_pid:
                wait_status = status
                try:
                    tail = os.read(master, 4096)
                except OSError as exc:
                    if exc.errno == errno.EIO:
                        tail = b""
                    else:
                        raise
                if tail:
                    transcript.extend(tail)
                    continue
                break
        if wait_status is None:
            _, wait_status = os.waitpid(child_pid, 0)
        if sent < 2:
            detail = bytes(transcript).decode("utf-8", errors="replace")[-500:]
            raise ImageSecurityError("age did not complete its passphrase confirmation" +
                                     (f": {detail}" if detail else ""))
        if not os.WIFEXITED(wait_status) or os.WEXITSTATUS(wait_status) != 0:
            detail = bytes(transcript).decode("utf-8", errors="replace").strip()[-500:]
            raise ImageSecurityError("age passphrase encryption failed" +
                                     (f": {detail}" if detail else ""))
        info = os.lstat(temporary)
        if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_size <= 0:
            raise ImageSecurityError("age did not produce a non-empty regular encrypted artifact")
        os.chmod(temporary, 0o600)
        with open(temporary, "rb") as stream:
            os.fsync(stream.fileno())
        size, digest = _digest_file(temporary)
        os.link(temporary, encrypted_path, follow_symlinks=False)
        os.unlink(temporary)
        committed = True
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
        raise ImageSecurityError(f"could not encrypt artifact with age passphrase: {exc}") from exc
    finally:
        if child_pid is not None and wait_status is None:
            try:
                os.kill(child_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                os.waitpid(child_pid, 0)
            except ChildProcessError:
                pass
        if master is not None:
            os.close(master)
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        if not committed and os.path.lexists(encrypted_path):
            # The destination is only linked after age has completed successfully.
            try:
                os.unlink(encrypted_path)
            except OSError:
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
    """Decrypt a passphrase-encrypted age stream through a controlling PTY.

    The passphrase is sent only after age displays its terminal prompt. It is
    never passed in argv, environment variables, or a pipe separate from the
    controlling terminal.
    """
    import errno
    import pty
    import select
    import signal
    import time
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

    # Keep the output in a private directory below the selected temp directory.
    # age can safely create/overwrite the file without a symlink race from
    # another local user, even when the parent temp directory is shared.
    private_dir = tempfile.mkdtemp(prefix=".feclora-age-", dir=target_dir)
    os.chmod(private_dir, 0o700)
    output_fd, temporary = tempfile.mkstemp(prefix="plaintext-", dir=private_dir)
    os.fchmod(output_fd, 0o600)
    os.close(output_fd)

    input_fd = encrypted_stream.fileno()
    was_inheritable = os.get_inheritable(input_fd)
    master = None
    child_pid = None
    sent = False
    transcript = bytearray()
    wait_status = None
    keep_output = False
    try:
        os.set_inheritable(input_fd, True)
        child_pid, master = pty.fork()
        if child_pid == 0:
            try:
                tty.setraw(0)
                os.umask(0o077)
                os.execv(age, [age, "--decrypt", "--output", temporary,
                               f"/proc/self/fd/{input_fd}"])
            except BaseException as exc:
                try:
                    os.write(2, f"age exec failed: {exc}\n".encode("utf-8", errors="replace"))
                finally:
                    os._exit(127)

        deadline = time.monotonic() + 180.0
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ImageSecurityError("age decryption timed out while waiting for terminal input")
            readable, _, _ = select.select([master], [], [], min(0.25, remaining))
            if readable:
                try:
                    chunk = os.read(master, 4096)
                except OSError as exc:
                    if exc.errno == errno.EIO:
                        chunk = b""
                    else:
                        raise
                if chunk:
                    transcript.extend(chunk)
                    if len(transcript) > 8192:
                        del transcript[:-8192]
                    if not sent and b"passphrase:" in bytes(transcript).lower():
                        os.write(master, passphrase.encode("utf-8") + b"\n")
                        sent = True
                elif wait_status is not None:
                    break
            waited, status = os.waitpid(child_pid, os.WNOHANG)
            if waited == child_pid:
                wait_status = status
                # Drain any final diagnostic text from the PTY.
                try:
                    tail = os.read(master, 4096)
                except OSError as exc:
                    if exc.errno == errno.EIO:
                        tail = b""
                    else:
                        raise
                if tail:
                    transcript.extend(tail)
                    continue
                break

        if wait_status is None:
            _, wait_status = os.waitpid(child_pid, 0)
        if not sent:
            detail = bytes(transcript).decode("utf-8", errors="replace")[-500:]
            raise ImageSecurityError("age did not request a passphrase on its controlling terminal" +
                                     (f": {detail}" if detail else ""))
        if not os.WIFEXITED(wait_status) or os.WEXITSTATUS(wait_status) != 0:
            detail = bytes(transcript).decode("utf-8", errors="replace").strip()[-500:]
            raise ImageSecurityError("age passphrase decryption/authentication failed" +
                                     (f": {detail}" if detail else ""))
        info = os.lstat(temporary)
        if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_size <= 0:
            raise ImageSecurityError("age produced no non-empty plaintext artifact")
        os.chmod(temporary, 0o600)
        with open(temporary, "rb") as output:
            os.fsync(output.fileno())
        keep_output = True
        return temporary
    except ImageSecurityError:
        raise
    except (OSError, subprocess.SubprocessError) as exc:
        raise ImageSecurityError(f"could not decrypt passphrase-encrypted age artifact: {exc}") from exc
    finally:
        os.set_inheritable(input_fd, was_inheritable)
        if child_pid is not None and wait_status is None:
            try:
                os.kill(child_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                os.waitpid(child_pid, 0)
            except ChildProcessError:
                pass
        if master is not None:
            os.close(master)
        # On success, the caller owns the plaintext file and removes it.
        if not keep_output:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            try:
                os.rmdir(private_dir)
            except OSError:
                pass
