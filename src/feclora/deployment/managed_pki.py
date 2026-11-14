"""Feclora-managed TLS Server certificate lifecycle."""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


class PKIError(RuntimeError):
    """Managed Server PKI operation failed."""



def _run(argv: list[str], runner: Callable[..., Any] | None = None) -> Any:
    execute = runner or subprocess.run
    try:
        result = execute(
            argv, stdin=subprocess.DEVNULL, capture_output=True, text=True,
            check=False, timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise PKIError(f"could not execute {argv[0]}: {exc}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()[:512]
        raise PKIError(f"{Path(argv[0]).name} failed" + (f": {detail}" if detail else ""))
    return result


def _root_only_directory(path: str | os.PathLike[str]) -> str:
    directory = os.path.abspath(os.fspath(path))
    if os.geteuid() != 0:
        raise PKIError("managed certificate operations require root")
    os.makedirs(directory, mode=0o700, exist_ok=True)
    info = os.lstat(directory)
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_uid != 0:
        raise PKIError("PKI directory must be a real root-owned directory")
    os.chmod(directory, 0o700)
    return directory


def _regular_file(path: str, label: str, *, root_owned: bool = False) -> None:
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise PKIError(f"{label} is unavailable: {exc}") from exc
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise PKIError(f"{label} must be a regular file, not a symlink")
    if root_owned and info.st_uid != 0:
        raise PKIError(f"{label} must be root-owned")


def _atomic_copy(source: str, destination: str, mode: int = 0o644) -> None:
    _regular_file(source, "imported certificate")
    parent = os.path.dirname(destination)
    fd, temporary = tempfile.mkstemp(prefix=".feclora-pki-", dir=parent)
    try:
        with open(source, "rb") as src, os.fdopen(fd, "wb") as dst:
            shutil.copyfileobj(src, dst)
            dst.flush()
            os.fsync(dst.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, destination)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def initialize_server_pki(
    directory: str | os.PathLike[str] = "/etc/feclora/pki",
    *,
    runner: Callable[..., Any] | None = None,
    openssl: str = "/usr/bin/openssl",
) -> dict[str, str]:
    """Create a local CA and TLS Server identity exactly once."""
    root = _root_only_directory(directory)
    paths = {
        "ca_key": os.path.join(root, "ca.key"),
        "ca_file": os.path.join(root, "ca.crt"),
        "server_key": os.path.join(root, "server.key"),
        "server_certificate": os.path.join(root, "server.crt"),
    }
    present = [os.path.exists(path) for path in paths.values()]
    if any(present):
        if not all(present):
            raise PKIError("partial PKI exists; refusing to overwrite or silently regenerate trust material")
        for key, path in paths.items():
            _regular_file(path, key, root_owned=True)
        if os.stat(paths["ca_key"]).st_mode & 0o077 or os.stat(paths["server_key"]).st_mode & 0o077:
            raise PKIError("TLS private keys must have mode 0600 or stricter")
        _run([openssl, "verify", "-no_check_time", "-CAfile", paths["ca_file"], paths["server_certificate"]], runner)
        return paths

    ca_tmp = os.path.join(root, "ca.key.tmp")
    cert_tmp = os.path.join(root, "ca.crt.tmp")
    server_key_tmp = os.path.join(root, "server.key.tmp")
    csr_tmp = os.path.join(root, "server.csr.tmp")
    server_cert_tmp = os.path.join(root, "server.crt.tmp")
    ext_tmp = os.path.join(root, "server.ext.tmp")
    try:
        _run([
            openssl, "req", "-x509", "-newkey", "rsa:3072", "-nodes",
            "-keyout", ca_tmp, "-out", cert_tmp, "-days", "3650", "-sha256",
            "-subj", "/CN=Feclora Deployment CA",
            "-addext", "basicConstraints=critical,CA:TRUE,pathlen:0",
            "-addext", "keyUsage=critical,keyCertSign,cRLSign",
            "-addext", "subjectKeyIdentifier=hash",
        ], runner)
        os.chmod(ca_tmp, 0o600)
        _run([
            openssl, "req", "-new", "-newkey", "rsa:3072", "-nodes",
            "-keyout", server_key_tmp, "-out", csr_tmp,
            "-subj", "/CN=feclora-server",
            "-addext", "subjectAltName=URI:feclora-server",
        ], runner)
        os.chmod(server_key_tmp, 0o600)
        Path(ext_tmp).write_text(
            "subjectAltName=URI:feclora-server\n"
            "keyUsage=critical,digitalSignature,keyEncipherment\n"
            "extendedKeyUsage=serverAuth\n",
            encoding="ascii",
        )
        os.chmod(ext_tmp, 0o600)
        _run([
            openssl, "x509", "-req", "-in", csr_tmp, "-CA", cert_tmp,
            "-CAkey", ca_tmp, "-set_serial", "0x01", "-out", server_cert_tmp,
            "-days", "825", "-sha256", "-extfile", ext_tmp,
        ], runner)
        _run([openssl, "verify", "-CAfile", cert_tmp, server_cert_tmp], runner)
        os.replace(ca_tmp, paths["ca_key"])
        os.replace(cert_tmp, paths["ca_file"])
        os.replace(server_key_tmp, paths["server_key"])
        os.replace(server_cert_tmp, paths["server_certificate"])
        for path in (csr_tmp, ext_tmp):
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass
        return paths
    except Exception:
        for path in (ca_tmp, cert_tmp, server_key_tmp, csr_tmp, server_cert_tmp, ext_tmp):
            try:
                os.unlink(path)
            except OSError:
                pass
        raise


def renew_server_certificate(
    pki_directory: str | os.PathLike[str] = "/etc/feclora/pki",
    *,
    runner: Callable[..., Any] | None = None,
    openssl: str = "/usr/bin/openssl",
    validity_days: int = 825,
) -> dict[str, Any]:
    """Renew the Server TLS certificate using the existing CA and private key."""
    if isinstance(validity_days, bool) or not isinstance(validity_days, int) or not 1 <= validity_days <= 825:
        raise PKIError("Server certificate validity must be between 1 and 825 days")
    root = _root_only_directory(pki_directory)
    paths = {
        "ca_key": os.path.join(root, "ca.key"),
        "ca_file": os.path.join(root, "ca.crt"),
        "server_key": os.path.join(root, "server.key"),
        "server_certificate": os.path.join(root, "server.crt"),
    }
    for label, path in paths.items():
        _regular_file(path, label, root_owned=True)
    if any(os.stat(paths[key]).st_mode & 0o077 for key in ("ca_key", "server_key")):
        raise PKIError("CA and Server private keys must not be accessible by group or other users")
    ca_expiry_days = certificate_expiry_days(paths["ca_file"], runner=runner, openssl=openssl)
    if ca_expiry_days <= 0:
        raise PKIError("deployment CA has expired; CA rotation and Client trust migration are required")
    effective_validity_days = min(validity_days, ca_expiry_days)
    _run([openssl, "verify", "-no_check_time", "-CAfile", paths["ca_file"], paths["server_certificate"]], runner)
    current_san = _run(
        [openssl, "x509", "-in", paths["server_certificate"], "-noout", "-ext", "subjectAltName"],
        runner,
    ).stdout
    if re.findall(r"URI:(feclora-server)", current_san) != ["feclora-server"] or re.search(r"\b(?:DNS|IP Address|email):", current_san):
        raise PKIError("existing Server certificate identity is not exactly URI:feclora-server")
    temporary_directory = tempfile.mkdtemp(prefix=".feclora-server-renewal-", dir=root)
    os.chmod(temporary_directory, 0o700)
    csr = os.path.join(temporary_directory, "server.csr")
    extensions = os.path.join(temporary_directory, "server.ext")
    renewed = os.path.join(temporary_directory, "server.crt")
    try:
        _run([
            openssl, "req", "-new", "-key", paths["server_key"], "-out", csr,
            "-subj", "/CN=feclora-server",
            "-addext", "subjectAltName=URI:feclora-server",
        ], runner)
        Path(extensions).write_text(
            "subjectAltName=URI:feclora-server\n"
            "keyUsage=critical,digitalSignature,keyEncipherment\n"
            "extendedKeyUsage=serverAuth\n",
            encoding="ascii",
        )
        os.chmod(extensions, 0o600)
        serial = "0x" + os.urandom(16).hex()
        _run([
            openssl, "x509", "-req", "-in", csr, "-CA", paths["ca_file"],
            "-CAkey", paths["ca_key"], "-set_serial", serial, "-out", renewed,
            "-days", str(effective_validity_days), "-sha256", "-extfile", extensions,
        ], runner)
        _run([openssl, "verify", "-CAfile", paths["ca_file"], renewed], runner)
        renewed_san = _run(
            [openssl, "x509", "-in", renewed, "-noout", "-ext", "subjectAltName"],
            runner,
        ).stdout
        if re.findall(r"URI:(feclora-server)", renewed_san) != ["feclora-server"] or re.search(r"\b(?:DNS|IP Address|email):", renewed_san):
            raise PKIError("renewed Server certificate SAN does not match the managed Server identity")
        certificate_public = _run(
            [openssl, "x509", "-in", renewed, "-pubkey", "-noout"], runner,
        ).stdout.strip()
        key_public = _run(
            [openssl, "pkey", "-in", paths["server_key"], "-pubout"], runner,
        ).stdout.strip()
        if not certificate_public or certificate_public != key_public:
            raise PKIError("renewed Server certificate does not match the existing private key")
        os.chmod(renewed, 0o644)
        os.replace(renewed, paths["server_certificate"])
        directory_fd = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        return {
            "certificate_file": paths["server_certificate"],
            "ca_fingerprint": ca_fingerprint(paths["ca_file"], runner=runner, openssl=openssl),
            "ca_expiry_days": ca_expiry_days,
        }
    finally:
        import shutil
        shutil.rmtree(temporary_directory, ignore_errors=True)



def rotate_server_keypair(
    pki_directory: str | os.PathLike[str] = "/etc/feclora/pki",
    *,
    runner: Callable[..., Any] | None = None,
    openssl: str = "/usr/bin/openssl",
    validity_days: int = 825,
) -> dict[str, Any]:
    """Rotate the Server TLS key and leaf certificate under the existing CA.

    The CA and its private key are never changed. Both replacement files are
    fully generated and validated before either active file is touched. If an
    installation step fails, the original key and certificate are restored.
    """
    if isinstance(validity_days, bool) or not isinstance(validity_days, int) or not 1 <= validity_days <= 825:
        raise PKIError("Server certificate validity must be between 1 and 825 days")
    root = _root_only_directory(pki_directory)
    paths = {
        "ca_key": os.path.join(root, "ca.key"),
        "ca_file": os.path.join(root, "ca.crt"),
        "server_key": os.path.join(root, "server.key"),
        "server_certificate": os.path.join(root, "server.crt"),
    }
    for label, path in paths.items():
        _regular_file(path, label, root_owned=True)
    if any(os.stat(paths[key]).st_mode & 0o077 for key in ("ca_key", "server_key")):
        raise PKIError("CA and Server private keys must not be accessible by group or other users")
    ca_expiry_days = certificate_expiry_days(paths["ca_file"], runner=runner, openssl=openssl)
    if ca_expiry_days <= 0:
        raise PKIError("deployment CA has expired; CA rotation and Client trust migration are required")
    effective_validity_days = min(validity_days, ca_expiry_days)
    _run([openssl, "verify", "-no_check_time", "-CAfile", paths["ca_file"], paths["server_certificate"]], runner)
    temporary_directory = tempfile.mkdtemp(prefix=".feclora-server-key-rotation-", dir=root)
    os.chmod(temporary_directory, 0o700)
    new_key = os.path.join(temporary_directory, "server.key")
    csr = os.path.join(temporary_directory, "server.csr")
    extensions = os.path.join(temporary_directory, "server.ext")
    new_certificate = os.path.join(temporary_directory, "server.crt")
    try:
        _run([
            openssl, "genpkey", "-algorithm", "RSA",
            "-pkeyopt", "rsa_keygen_bits:3072", "-out", new_key,
        ], runner)
        os.chmod(new_key, 0o600)
        _run([
            openssl, "req", "-new", "-key", new_key, "-out", csr,
            "-subj", "/CN=feclora-server",
            "-addext", "subjectAltName=URI:feclora-server",
        ], runner)
        Path(extensions).write_text(
            "subjectAltName=URI:feclora-server\n"
            "keyUsage=critical,digitalSignature,keyEncipherment\n"
            "extendedKeyUsage=serverAuth\n",
            encoding="ascii",
        )
        os.chmod(extensions, 0o600)
        serial = "0x" + os.urandom(16).hex()
        _run([
            openssl, "x509", "-req", "-in", csr, "-CA", paths["ca_file"],
            "-CAkey", paths["ca_key"], "-set_serial", serial,
            "-out", new_certificate, "-days", str(effective_validity_days),
            "-sha256", "-extfile", extensions,
        ], runner)
        _run([openssl, "verify", "-CAfile", paths["ca_file"], new_certificate], runner)
        san = _run(
            [openssl, "x509", "-in", new_certificate, "-noout", "-ext", "subjectAltName"],
            runner,
        ).stdout
        if re.findall(r"URI:(feclora-server)", san) != ["feclora-server"] or re.search(r"\b(?:DNS|IP Address|email):", san):
            raise PKIError("new Server certificate SAN does not match the managed Server identity")
        certificate_public = _run(
            [openssl, "x509", "-in", new_certificate, "-pubkey", "-noout"], runner,
        ).stdout.strip()
        key_public = _run([openssl, "pkey", "-in", new_key, "-pubout"], runner).stdout.strip()
        if not certificate_public or certificate_public != key_public:
            raise PKIError("new Server certificate does not match the rotated private key")
        os.chmod(new_certificate, 0o644)

        originals: dict[str, tuple[bytes, int]] = {}
        for active in (paths["server_key"], paths["server_certificate"]):
            info = os.stat(active)
            originals[active] = (Path(active).read_bytes(), stat.S_IMODE(info.st_mode))
        replaced: list[str] = []
        try:
            os.replace(new_certificate, paths["server_certificate"])
            replaced.append(paths["server_certificate"])
            os.replace(new_key, paths["server_key"])
            replaced.append(paths["server_key"])
            directory_fd = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except Exception:
            for active in reversed(replaced):
                content, mode = originals[active]
                fd, backup = tempfile.mkstemp(prefix=".feclora-server-rollback-", dir=root)
                try:
                    with os.fdopen(fd, "wb") as stream:
                        stream.write(content)
                        stream.flush()
                        os.fsync(stream.fileno())
                    os.chmod(backup, mode)
                    os.replace(backup, active)
                except Exception:
                    try:
                        os.unlink(backup)
                    except OSError:
                        pass
                    raise
            raise
        return {
            "certificate_file": paths["server_certificate"],
            "private_key_file": paths["server_key"],
            "ca_fingerprint": ca_fingerprint(paths["ca_file"], runner=runner, openssl=openssl),
            "ca_expiry_days": ca_expiry_days,
            "key_rotated": True,
        }
    finally:
        shutil.rmtree(temporary_directory, ignore_errors=True)

def ca_fingerprint(ca_file: str, *, runner: Callable[..., Any] | None = None,
                   openssl: str = "/usr/bin/openssl") -> str:
    _regular_file(ca_file, "CA certificate")
    result = _run([openssl, "x509", "-in", ca_file, "-noout", "-fingerprint", "-sha256"], runner)
    value = result.stdout.strip()
    prefix = "sha256 Fingerprint="
    if not value.lower().startswith(prefix.lower()):
        raise PKIError("OpenSSL returned an unexpected CA fingerprint")
    return value[len(prefix):].replace(":", "").lower()




def ca_bundle_fingerprints(
    ca_file: str,
    *,
    runner: Callable[..., Any] | None = None,
    openssl: str = "/usr/bin/openssl",
) -> list[str]:
    """Return the validated SHA-256 fingerprints of every CA in a PEM bundle."""
    try:
        fd = os.open(ca_file, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size > 8 * 1024 * 1024:
                raise PKIError("CA trust bundle must be a regular file no larger than 8 MiB")
            raw = bytearray()
            while len(raw) <= 8 * 1024 * 1024:
                chunk = os.read(fd, min(65536, 8 * 1024 * 1024 + 1 - len(raw)))
                if not chunk:
                    break
                raw.extend(chunk)
            if len(raw) > 8 * 1024 * 1024:
                raise PKIError("CA trust bundle exceeds 8 MiB")
        finally:
            os.close(fd)
    except OSError as exc:
        raise PKIError(f"cannot safely read CA trust bundle: {exc}") from exc

    pattern = rb"-----BEGIN CERTIFICATE-----\s*[A-Za-z0-9+/=\r\n]+\s*-----END CERTIFICATE-----"
    blocks = re.findall(pattern, bytes(raw))
    remainder = re.sub(pattern, b"", bytes(raw))
    if not 1 <= len(blocks) <= 8 or remainder.strip():
        raise PKIError("CA trust bundle must contain one to eight PEM certificates and no other data")

    fingerprints: list[str] = []
    with tempfile.TemporaryDirectory(prefix="feclora-ca-inspect-") as temporary_directory:
        for index, block in enumerate(blocks):
            certificate = os.path.join(temporary_directory, f"ca-{index}.pem")
            Path(certificate).write_bytes(block + b"\n")
            _run([openssl, "x509", "-in", certificate, "-noout"], runner)
            constraints = _run(
                [openssl, "x509", "-in", certificate, "-noout", "-ext", "basicConstraints"], runner
            ).stdout
            usage = _run(
                [openssl, "x509", "-in", certificate, "-noout", "-ext", "keyUsage"], runner
            ).stdout
            if not re.search(r"CA\s*:\s*TRUE", constraints, re.IGNORECASE):
                raise PKIError("trust bundle contains a certificate that is not a CA")
            if not re.search(r"Certificate Sign", usage, re.IGNORECASE):
                raise PKIError("trust bundle contains a CA without certificate-signing usage")
            fingerprint = ca_fingerprint(certificate, runner=runner, openssl=openssl)
            if fingerprint in fingerprints:
                raise PKIError("CA trust bundle contains a duplicate certificate")
            fingerprints.append(fingerprint)
    return fingerprints


def build_ca_trust_bundle(
    ca_files: list[str | os.PathLike[str]],
    destination: str | os.PathLike[str],
    *,
    pki_directory: str | os.PathLike[str] = "/etc/feclora/pki",
    runner: Callable[..., Any] | None = None,
    openssl: str = "/usr/bin/openssl",
) -> dict[str, Any]:
    """Atomically build a public PEM trust bundle from validated CA certificates.

    The output must be a direct child of the protected PKI directory. Inputs
    are public certificates only; private keys are never read or copied.
    """
    root = _root_only_directory(pki_directory)
    target = os.path.abspath(os.fspath(destination))
    if os.path.dirname(target) != root or os.path.basename(target) in {"", ".", ".."}:
        raise PKIError("CA trust bundle destination must be a direct child of the PKI directory")
    if not isinstance(ca_files, list) or not 1 <= len(ca_files) <= 8:
        raise PKIError("CA trust bundle requires between one and eight CA certificates")

    certificates: list[bytes] = []
    fingerprints: list[str] = []
    seen: set[str] = set()
    for item in ca_files:
        source = os.path.abspath(os.fspath(item))
        try:
            source_fd = os.open(source, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            try:
                info = os.fstat(source_fd)
                if not stat.S_ISREG(info.st_mode):
                    raise PKIError("CA trust certificate must be a regular file, not a symlink")
                if info.st_size > 1024 * 1024:
                    raise PKIError("CA trust certificate exceeds the 1 MiB limit")
                chunks = bytearray()
                while len(chunks) <= 1024 * 1024:
                    chunk = os.read(source_fd, min(65536, 1024 * 1024 + 1 - len(chunks)))
                    if not chunk:
                        break
                    chunks.extend(chunk)
                if len(chunks) > 1024 * 1024:
                    raise PKIError("CA trust certificate exceeds the 1 MiB limit")
                raw = bytes(chunks)
            finally:
                os.close(source_fd)
        except OSError as exc:
            raise PKIError(f"cannot safely read CA trust certificate: {exc}") from exc
        if not re.fullmatch(
            rb"\s*-----BEGIN CERTIFICATE-----\s*[A-Za-z0-9+/=\r\n]+"
            rb"\s*-----END CERTIFICATE-----\s*",
            raw,
        ):
            raise PKIError("each CA trust input must contain exactly one clean PEM certificate")
        _run([openssl, "x509", "-in", source, "-noout"], runner)
        constraints = _run([openssl, "x509", "-in", source, "-noout", "-ext", "basicConstraints"], runner).stdout
        usage = _run([openssl, "x509", "-in", source, "-noout", "-ext", "keyUsage"], runner).stdout
        if not re.search(r"CA\s*:\s*TRUE", constraints, re.IGNORECASE):
            raise PKIError("trust bundle input is not a CA certificate")
        if not re.search(r"Certificate Sign", usage, re.IGNORECASE):
            raise PKIError("CA trust certificate does not permit certificate signing")
        fingerprint = ca_fingerprint(source, runner=runner, openssl=openssl)
        if not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
            raise PKIError("OpenSSL returned a malformed CA fingerprint")
        if fingerprint in seen:
            raise PKIError("CA trust bundle contains a duplicate certificate")
        seen.add(fingerprint)
        certificates.append(raw.rstrip() + b"\n")
        fingerprints.append(fingerprint)

    if os.path.lexists(target):
        _regular_file(target, "existing CA trust bundle", root_owned=True)
    fd, temporary = tempfile.mkstemp(prefix=".feclora-trust-bundle-", dir=root)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(b"".join(certificates))
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, target)
        directory_fd = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return {
        "trust_bundle": target,
        "ca_fingerprints": fingerprints,
        "certificate_count": len(fingerprints),
        "message": "Validated public CA certificates were installed atomically; no private key material was accessed.",
    }


def certificate_expiry_days(
    certificate_path: str,
    *,
    now: datetime | None = None,
    runner: Callable[..., Any] | None = None,
    openssl: str = "/usr/bin/openssl",
) -> int:
    """Return whole days until certificate expiry; negative values are expired."""
    _regular_file(certificate_path, "TLS certificate")
    result = _run([openssl, "x509", "-in", certificate_path, "-noout", "-enddate"], runner)
    prefix = "notAfter="
    value = result.stdout.strip()
    if not value.startswith(prefix):
        raise PKIError("OpenSSL returned an unexpected certificate expiry")
    try:
        expiry = datetime.strptime(value[len(prefix):], "%b %d %H:%M:%S %Y GMT").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise PKIError("certificate expiry has an unsupported format") from exc
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise PKIError("current time must be timezone-aware")
    return int((expiry - current.astimezone(timezone.utc)).total_seconds() // 86400)



def _atomic_text(path: str, content: str, mode: int = 0o600) -> None:
    directory = os.path.dirname(path)
    fd, temporary = tempfile.mkstemp(prefix=".feclora-pki-state-", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="ascii") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
        dirfd = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(dirfd)
        finally:
            os.close(dirfd)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def register_age_recipient(
    pki_directory: str | os.PathLike[str],
    identity: str,
    recipient: str,
) -> None:
    """Register a Client age recipient for future captures and retain identity mapping."""
    if os.geteuid() != 0:
        raise PKIError("age recipient inventory updates require root")
    prefix = "URI:feclora-client-"
    if not isinstance(identity, str) or not identity.startswith(prefix):
        raise PKIError("age recipient must be associated with a Feclora Client URI identity")
    client_id = identity[len(prefix):]
    if not _CLIENT_ID.fullmatch(client_id) or not re.fullmatch(r"age1[0-9a-z]{20,}", recipient):
        raise PKIError("Client age recipient mapping is malformed")
    root = _root_only_directory(pki_directory)
    recipients_file = os.path.join(root, "age-recipients.txt")
    _regular_file(recipients_file, "Server age recipient inventory", root_owned=True)
    inventory = [
        line.strip() for line in Path(recipients_file).read_text(encoding="ascii").splitlines()
        if line.strip()
    ]
    if any(not re.fullmatch(r"age1[0-9a-z]{20,}", item) for item in inventory):
        raise PKIError("Server age recipient inventory contains an invalid entry")
    if recipient in inventory:
        raise PKIError(
            "Client age recipient is already registered; each Client must have a unique age identity"
        )
    directory = _root_only_directory(os.path.join(root, "age-recipients"))
    mapping_file = os.path.join(directory, client_id + ".txt")
    if os.path.lexists(mapping_file):
        raise PKIError("Client age-recipient mapping already exists; refusing to overwrite it")
    original_inventory = Path(recipients_file).read_text(encoding="ascii")
    updated_inventory = "\n".join(sorted(set(inventory + [recipient]))) + "\n"
    _atomic_text(recipients_file, updated_inventory)
    try:
        _atomic_text(mapping_file, recipient + "\n")
    except Exception as exc:
        try:
            _atomic_text(recipients_file, original_inventory)
        except Exception as rollback_error:
            raise PKIError(
                f"could not persist Client age-recipient mapping or roll back the inventory: {rollback_error}"
            ) from exc
        raise


def remove_age_recipient(
    pki_directory: str | os.PathLike[str],
    identity: str,
) -> bool:
    """Remove a revoked/rotated Client from future image encryption recipient lists."""
    prefix = "URI:feclora-client-"
    if not isinstance(identity, str) or not identity.startswith(prefix):
        return False
    client_id = identity[len(prefix):]
    if not _CLIENT_ID.fullmatch(client_id):
        return False
    root = os.path.abspath(os.fspath(pki_directory))
    mapping = os.path.join(root, "age-recipients", client_id + ".txt")
    if not os.path.exists(mapping):
        return False
    if os.geteuid() != 0:
        raise PKIError("age recipient revocation requires root")
    _root_only_directory(root)
    _regular_file(mapping, "Client age recipient mapping", root_owned=True)
    recipient = Path(mapping).read_text(encoding="ascii").strip()
    recipients_file = os.path.join(root, "age-recipients.txt")
    _regular_file(recipients_file, "Server age recipient inventory", root_owned=True)
    remaining = [
        line.strip() for line in Path(recipients_file).read_text(encoding="ascii").splitlines()
        if line.strip() and line.strip() != recipient
    ]
    _atomic_text(recipients_file, ("\n".join(sorted(set(remaining))) + "\n") if remaining else "")
    os.unlink(mapping)
    return True


