"""Feclora-managed TLS certificate bootstrap and removable-media enrollment.

Private keys are generated and retained on their owning endpoint. Only CSRs
and signed public certificates cross the removable-media trust boundary.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
import subprocess
import tarfile
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


class PKIError(RuntimeError):
    """Managed deployment PKI setup or enrollment failed."""


_CLIENT_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,47}$")


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


def create_client_csr(
    pki_directory: str | os.PathLike[str],
    export_directory: str | os.PathLike[str],
    client_id: str,
    *,
    runner: Callable[..., Any] | None = None,
    openssl: str = "/usr/bin/openssl",
    reuse_existing_key: bool = False,
    age_keygen: str = "/usr/bin/age-keygen",
) -> tuple[str, str, str]:
    """Generate a Client key locally, or reuse it for renewal, and export only its CSR."""
    if not isinstance(client_id, str) or not _CLIENT_ID.fullmatch(client_id):
        raise PKIError("Client identifier must contain 1-48 lowercase letters, digits or hyphens")
    root = _root_only_directory(pki_directory)
    export = os.path.abspath(os.fspath(export_directory))
    if not os.path.isdir(export) or os.path.islink(export):
        raise PKIError("CSR export destination must be an existing real directory")
    identity = "URI:feclora-client-" + client_id
    key = os.path.join(root, f"client-{client_id}.key")
    suffix = "-renewal" if reuse_existing_key else ""
    csr = os.path.join(root, f"client-{client_id}{suffix}.csr")
    exported = os.path.join(export, f"feclora-{client_id}{suffix}.csr")
    age_identity = os.path.join(root, f"client-{client_id}.age")
    age_recipient_export = os.path.join(export, f"feclora-{client_id}{suffix}.age-recipient")
    if os.path.lexists(csr) or os.path.lexists(exported) or os.path.lexists(age_recipient_export):
        raise PKIError("CSR or age-recipient export already exists; remove or rename the previous request")
    if reuse_existing_key:
        _regular_file(key, "existing Client private key", root_owned=True)
        if os.stat(key).st_mode & 0o077:
            raise PKIError("existing Client private key must not be accessible by group or other users")
        argv = [openssl, "req", "-new", "-key", key, "-out", csr,
                "-subj", f"/CN=feclora-client-{client_id}", "-addext", f"subjectAltName={identity}"]
    else:
        if os.path.lexists(key):
            raise PKIError("Client identity key already exists; use renewal rather than replacing it")
        argv = [openssl, "req", "-new", "-newkey", "rsa:3072", "-nodes",
                "-keyout", key, "-out", csr, "-subj", f"/CN=feclora-client-{client_id}",
                "-addext", f"subjectAltName={identity}"]
    _run(argv, runner)
    os.chmod(key, 0o600)
    os.chmod(csr, 0o600)
    _atomic_copy(csr, exported, 0o644)
    if not os.path.exists(age_identity):
        age_result = _run([age_keygen, "-o", age_identity], runner)
        os.chmod(age_identity, 0o600)
        match = re.search(r"Public key:\s*(age1[0-9a-z]+)", age_result.stdout)
        if not match:
            raise PKIError("age-keygen did not report a valid public recipient")
        recipient = match.group(1)
    else:
        _regular_file(age_identity, "Client age identity", root_owned=True)
        if os.stat(age_identity).st_mode & 0o077:
            raise PKIError("Client age identity must not be accessible by group or other users")
        age_result = _run([age_keygen, "-y", age_identity], runner)
        recipient = age_result.stdout.strip()
        if not re.fullmatch(r"age1[0-9a-z]{20,}", recipient):
            raise PKIError("existing age identity did not produce a valid public recipient")
    fd, temporary = tempfile.mkstemp(prefix=".feclora-age-recipient-", dir=export)
    try:
        with os.fdopen(fd, "w", encoding="ascii") as stream:
            stream.write(recipient + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, age_recipient_export)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return identity, key, exported


def inspect_client_csr(
    csr_path: str,
    *,
    runner: Callable[..., Any] | None = None,
    openssl: str = "/usr/bin/openssl",
) -> str:
    _regular_file(csr_path, "Client CSR")
    if os.path.getsize(csr_path) > 64 * 1024:
        raise PKIError("Client CSR exceeds 64 KiB")
    _run([openssl, "req", "-in", csr_path, "-noout", "-verify"], runner)
    result = _run([openssl, "req", "-in", csr_path, "-noout", "-ext", "subjectAltName"], runner)
    identities = re.findall(r"URI:(feclora-client-[a-z0-9-]{1,48})", result.stdout)
    other_sans = re.findall(r"\b(?:DNS|IP Address|email):", result.stdout)
    if len(identities) != 1 or other_sans:
        raise PKIError("CSR must contain exactly one Feclora Client URI SAN")
    client_id = identities[0][len("feclora-client-"):]
    if not _CLIENT_ID.fullmatch(client_id):
        raise PKIError("CSR Client identity is malformed")
    return "URI:" + identities[0]


def issue_client_certificate(
    csr_path: str,
    output_certificate: str,
    *,
    pki_directory: str | os.PathLike[str] = "/etc/feclora/pki",
    validity_days: int = 90,
    runner: Callable[..., Any] | None = None,
    openssl: str = "/usr/bin/openssl",
) -> str:
    """Sign one verified Feclora Client CSR; never receives or copies its private key."""
    if isinstance(validity_days, bool) or not isinstance(validity_days, int) or not 1 <= validity_days <= 365:
        raise PKIError("Client certificate validity must be between 1 and 365 days")
    root = _root_only_directory(pki_directory)
    identity = inspect_client_csr(csr_path, runner=runner, openssl=openssl)
    ca_key = os.path.join(root, "ca.key")
    ca_file = os.path.join(root, "ca.crt")
    _regular_file(ca_key, "CA private key", root_owned=True)
    _regular_file(ca_file, "CA certificate", root_owned=True)
    if os.stat(ca_key).st_mode & 0o077:
        raise PKIError("CA private key must not be accessible by group or other users")
    output_directory = os.path.dirname(os.path.abspath(output_certificate))
    if not os.path.isdir(output_directory) or os.path.islink(output_directory):
        raise PKIError("certificate output directory must be an existing real directory")
    if os.path.lexists(output_certificate):
        raise PKIError("refusing to overwrite an existing Client certificate export")
    extension_file = os.path.join(root, ".client-extensions.tmp")
    fd, temporary = tempfile.mkstemp(prefix=".feclora-client-cert-", dir=output_directory)
    os.close(fd)
    serial = "0x" + os.urandom(16).hex()
    try:
        Path(extension_file).write_text(
            f"subjectAltName={identity}\n"
            "keyUsage=critical,digitalSignature,keyEncipherment\n"
            "extendedKeyUsage=clientAuth\n",
            encoding="ascii",
        )
        os.chmod(extension_file, 0o600)
        _run([
            openssl, "x509", "-req", "-in", csr_path, "-CA", ca_file,
            "-CAkey", ca_key, "-set_serial", serial, "-out", temporary,
            "-days", str(validity_days), "-sha256", "-extfile", extension_file,
        ], runner)
        _run([openssl, "verify", "-purpose", "sslclient", "-CAfile", ca_file, temporary], runner)
        os.replace(temporary, output_certificate)
        os.chmod(output_certificate, 0o644)
        return identity
    finally:
        for path in (extension_file, temporary):
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass


def install_client_certificate(
    certificate_path: str,
    ca_path: str,
    private_key_path: str,
    destination_directory: str,
    expected_identity: str,
    expected_fingerprint: str,
    *,
    runner: Callable[..., Any] | None = None,
    openssl: str = "/usr/bin/openssl",
) -> dict[str, str]:
    """Validate CA fingerprint, chain, identity and key match before local install."""
    destination = _root_only_directory(destination_directory)
    for path, label in ((certificate_path, "Client certificate"), (ca_path, "CA certificate"),
                        (private_key_path, "local Client private key")):
        _regular_file(path, label, root_owned=(path == private_key_path))
    if os.stat(private_key_path).st_mode & 0o077:
        raise PKIError("local Client private key must not be accessible by group or other users")
    actual_fingerprint = ca_fingerprint(ca_path, runner=runner, openssl=openssl)
    if actual_fingerprint != expected_fingerprint.replace(":", "").lower():
        raise PKIError("CA fingerprint does not match the fingerprint verified from the Server")
    _run([openssl, "verify", "-purpose", "sslclient", "-CAfile", ca_path, certificate_path], runner)
    san = _run([openssl, "x509", "-in", certificate_path, "-noout", "-ext", "subjectAltName"], runner)
    identity_entries = re.findall(r"URI:feclora-client-[a-z0-9-]{1,48}", san.stdout)
    other_sans = re.findall(r"\b(?:DNS|IP Address|email):", san.stdout)
    if identity_entries != [expected_identity] or other_sans or not expected_identity.startswith("URI:feclora-client-"):
        raise PKIError("issued certificate identity does not match the locally prepared Client identity")
    cert_key = _run([openssl, "x509", "-in", certificate_path, "-pubkey", "-noout"], runner).stdout.strip()
    local_key = _run([openssl, "pkey", "-in", private_key_path, "-pubout"], runner).stdout.strip()
    if not cert_key or cert_key != local_key:
        raise PKIError("issued certificate does not match the private key generated on this Client")
    installed = {
        "certificate_file": os.path.join(destination, "client.crt"),
        "ca_file": os.path.join(destination, "ca.crt"),
        "private_key_file": os.path.join(destination, "client.key"),
    }
    _atomic_copy(certificate_path, installed["certificate_file"], 0o644)
    _atomic_copy(ca_path, installed["ca_file"], 0o644)
    _atomic_copy(private_key_path, installed["private_key_file"], 0o600)
    return installed


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


def backup_server_ca(
    output_file: str,
    recipient: str,
    *,
    pki_directory: str | os.PathLike[str] = "/etc/feclora/pki",
    runner: Callable[..., Any] | None = None,
    openssl: str = "/usr/bin/openssl",
    age: str = "/usr/bin/age",
) -> dict[str, str]:
    """Create an age-encrypted offline backup containing only the managed CA.

    The CA private key is never written unencrypted outside the root-only PKI
    directory. The backup is staged and atomically published on removable
    media; an existing destination is never overwritten.
    """
    if not isinstance(recipient, str) or not re.fullmatch(r"age1[0-9a-z]{20,}", recipient):
        raise PKIError("backup encryption requires a valid age recipient")
    root = _root_only_directory(pki_directory)
    ca_key = os.path.join(root, "ca.key")
    ca_file = os.path.join(root, "ca.crt")
    _regular_file(ca_key, "CA private key", root_owned=True)
    _regular_file(ca_file, "CA certificate", root_owned=True)
    if os.stat(ca_key).st_mode & 0o077:
        raise PKIError("CA private key must not be accessible by group or other users")
    destination = os.path.abspath(output_file)
    parent = os.path.dirname(destination)
    parent_info = os.lstat(parent)
    if not stat.S_ISDIR(parent_info.st_mode) or stat.S_ISLNK(parent_info.st_mode):
        raise PKIError("CA backup destination must be an existing real directory")
    if os.path.lexists(destination):
        raise PKIError("refusing to overwrite an existing CA backup")
    fingerprint = ca_fingerprint(ca_file, runner=runner, openssl=openssl)
    temporary_directory = tempfile.mkdtemp(prefix=".feclora-ca-backup-", dir=root)
    fd, staged_output = tempfile.mkstemp(prefix=".feclora-ca-backup-", dir=parent)
    os.close(fd)
    # age deliberately refuses to overwrite an existing output file.
    os.unlink(staged_output)
    archive = os.path.join(temporary_directory, "ca-backup.tar")
    try:
        manifest = {
            "schema_version": 1,
            "purpose": "feclora-managed-deployment-ca-recovery",
            "ca_sha256_fingerprint": fingerprint,
            "contents": ["ca.crt", "ca.key"],
        }
        with tarfile.open(archive, "w") as bundle:
            bundle.add(ca_file, arcname="ca.crt", recursive=False)
            bundle.add(ca_key, arcname="ca.key", recursive=False)
            encoded = (json.dumps(manifest, sort_keys=True) + "\n").encode("ascii")
            info = tarfile.TarInfo("manifest.json")
            info.size = len(encoded)
            info.mode = 0o600
            import io
            bundle.addfile(info, io.BytesIO(encoded))
        os.chmod(archive, 0o600)
        _run([age, "-r", recipient, "-o", staged_output, archive], runner)
        info = os.lstat(staged_output)
        if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_size <= 0:
            raise PKIError("age did not produce a valid encrypted CA backup")
        os.chmod(staged_output, 0o600)
        # link() publishes atomically without replacing a destination created
        # concurrently after the earlier lexists() check.
        os.link(staged_output, destination, follow_symlinks=False)
        os.unlink(staged_output)
        directory_fd = os.open(parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        digest = hashlib.sha256(Path(destination).read_bytes()).hexdigest()
        return {
            "backup_file": destination,
            "sha256": digest,
            "ca_fingerprint": fingerprint,
            "message": "Encrypted offline CA backup created. Store the age identity needed to decrypt it separately and securely.",
        }
    finally:
        for path in (staged_output,):
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass
        shutil.rmtree(temporary_directory, ignore_errors=True)


def inspect_server_ca_backup(
    encrypted_file: str,
    identity_file: str,
    *,
    pki_directory: str | os.PathLike[str] = "/etc/feclora/pki",
    runner: Callable[..., Any] | None = None,
    openssl: str = "/usr/bin/openssl",
    age: str = "/usr/bin/age",
) -> dict[str, str]:
    """Decrypt and validate a CA backup without changing active PKI material.

    The identity must be a root-owned regular file with restrictive permissions.
    Archive members are read individually; tar extraction is never used.
    """
    encrypted = os.path.abspath(encrypted_file)
    identity = os.path.abspath(identity_file)
    _regular_file(encrypted, "encrypted CA backup")
    if os.stat(encrypted).st_size <= 0 or os.stat(encrypted).st_size > 16 * 1024 * 1024:
        raise PKIError("encrypted CA backup size is outside the permitted limit")
    identity_fd = -1
    try:
        identity_fd = os.open(
            identity, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        )
        identity_info = os.fstat(identity_fd)
        if not stat.S_ISREG(identity_info.st_mode) or identity_info.st_uid != 0:
            raise PKIError("age decryption identity must be a root-owned regular file")
        if identity_info.st_mode & 0o077:
            raise PKIError("age decryption identity must not be accessible by group or other users")
        if identity_info.st_size <= 0 or identity_info.st_size > 65536:
            raise PKIError("age decryption identity size is outside the permitted limit")
    except OSError as exc:
        if identity_fd >= 0:
            os.close(identity_fd)
        raise PKIError(f"age decryption identity is unavailable or unsafe: {exc}") from exc
    root = _root_only_directory(pki_directory)
    temporary_directory = tempfile.mkdtemp(prefix=".feclora-ca-inspection-", dir=root)
    os.chmod(temporary_directory, 0o700)
    archive = os.path.join(temporary_directory, "backup.tar")
    identity_copy = os.path.join(temporary_directory, "age-identity.txt")
    ca_file = os.path.join(temporary_directory, "ca.crt")
    ca_key = os.path.join(temporary_directory, "ca.key")
    try:
        with os.fdopen(identity_fd, "rb") as source, open(identity_copy, "xb") as target:
            identity_fd = -1
            shutil.copyfileobj(source, target, length=65536)
            target.flush()
            os.fsync(target.fileno())
        os.chmod(identity_copy, 0o600)
        _run([age, "-d", "-i", identity_copy, "-o", archive, encrypted], runner)
        _regular_file(archive, "decrypted CA archive", root_owned=True)
        if os.stat(archive).st_size <= 0 or os.stat(archive).st_size > 4 * 1024 * 1024:
            raise PKIError("decrypted CA archive size is outside the permitted limit")
        expected = {"ca.crt", "ca.key", "manifest.json"}
        extracted: dict[str, bytes] = {}
        try:
            with tarfile.open(archive, "r:") as bundle:
                members = bundle.getmembers()
                names = [member.name for member in members]
                if len(names) != len(expected) or set(names) != expected:
                    raise PKIError("CA archive must contain exactly ca.crt, ca.key and manifest.json")
                for member in members:
                    if not member.isfile() or member.issym() or member.islnk() or member.size < 1 or member.size > 1024 * 1024:
                        raise PKIError("CA archive contains an unsupported entry or file size")
                    stream = bundle.extractfile(member)
                    if stream is None:
                        raise PKIError("CA archive contains an unreadable entry")
                    data = stream.read(1024 * 1024 + 1)
                    if len(data) != member.size or len(data) > 1024 * 1024:
                        raise PKIError("CA archive entry size is invalid")
                    extracted[member.name] = data
        except (tarfile.TarError, OSError) as exc:
            raise PKIError(f"CA archive is invalid: {exc}") from exc
        try:
            manifest = json.loads(extracted["manifest.json"].decode("ascii"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise PKIError("CA archive manifest is not valid JSON") from exc
        if not isinstance(manifest, dict) or set(manifest) != {
            "schema_version", "purpose", "ca_sha256_fingerprint", "contents"
        }:
            raise PKIError("CA archive manifest has an unsupported schema")
        if (
            type(manifest["schema_version"]) is not int
            or manifest["schema_version"] != 1
            or manifest["purpose"] != "feclora-managed-deployment-ca-recovery"
            or manifest["contents"] != ["ca.crt", "ca.key"]
            or not isinstance(manifest["ca_sha256_fingerprint"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", manifest["ca_sha256_fingerprint"])
        ):
            raise PKIError("CA archive manifest values are invalid")
        for name, data in (("ca.crt", extracted["ca.crt"]), ("ca.key", extracted["ca.key"])):
            with open(os.path.join(temporary_directory, name), "xb") as output:
                output.write(data)
            os.chmod(os.path.join(temporary_directory, name), 0o600)
        fingerprint = ca_fingerprint(ca_file, runner=runner, openssl=openssl)
        if fingerprint != manifest["ca_sha256_fingerprint"]:
            raise PKIError("CA certificate fingerprint does not match the archive manifest")
        constraints = _run(
            [openssl, "x509", "-in", ca_file, "-noout", "-ext", "basicConstraints"],
            runner,
        ).stdout
        usage = _run(
            [openssl, "x509", "-in", ca_file, "-noout", "-ext", "keyUsage"],
            runner,
        ).stdout
        if "CA:TRUE" not in constraints or "Certificate Sign" not in usage:
            raise PKIError("backup certificate is not a CA certificate with certificate-signing usage")
        _run([openssl, "verify", "-no_check_time", "-CAfile", ca_file, ca_file], runner)
        certificate_public = _run([openssl, "x509", "-in", ca_file, "-pubkey", "-noout"], runner).stdout.strip()
        key_public = _run([openssl, "pkey", "-in", ca_key, "-pubout"], runner).stdout.strip()
        if not certificate_public or certificate_public != key_public:
            raise PKIError("CA private key does not match the CA certificate")
        return {
            "ca_fingerprint": fingerprint,
            "archive_valid": "true",
            "message": "Encrypted CA backup decrypted and validated. Active PKI was not changed.",
        }
    finally:
        if identity_fd >= 0:
            os.close(identity_fd)
        shutil.rmtree(temporary_directory, ignore_errors=True)
