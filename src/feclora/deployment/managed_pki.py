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
import tempfile
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
        _run([openssl, "verify", "-CAfile", paths["ca_file"], paths["server_certificate"]], runner)
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


def ca_fingerprint(ca_file: str, *, runner: Callable[..., Any] | None = None,
                   openssl: str = "/usr/bin/openssl") -> str:
    _regular_file(ca_file, "CA certificate", root_owned=True)
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
) -> tuple[str, str, str]:
    """Generate the Client private key locally and export only its CSR."""
    if not isinstance(client_id, str) or not _CLIENT_ID.fullmatch(client_id):
        raise PKIError("Client identifier must contain 1-48 lowercase letters, digits or hyphens")
    root = _root_only_directory(pki_directory)
    export = os.path.abspath(os.fspath(export_directory))
    if not os.path.isdir(export) or os.path.islink(export):
        raise PKIError("CSR export destination must be an existing real directory")
    identity = "URI:feclora-client-" + client_id
    key = os.path.join(root, f"client-{client_id}.key")
    csr = os.path.join(root, f"client-{client_id}.csr")
    exported = os.path.join(export, f"feclora-{client_id}.csr")
    if os.path.lexists(key) or os.path.lexists(csr) or os.path.lexists(exported):
        raise PKIError("Client identity files already exist; use renewal rather than overwriting a key")
    _run([
        openssl, "req", "-new", "-newkey", "rsa:3072", "-nodes",
        "-keyout", key, "-out", csr, "-subj", f"/CN=feclora-client-{client_id}",
        "-addext", f"subjectAltName={identity}",
    ], runner)
    os.chmod(key, 0o600)
    os.chmod(csr, 0o600)
    _atomic_copy(csr, exported, 0o644)
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
    lines = result.stdout.splitlines()
    entries = ",".join(lines[1:]).replace(" ", "").split(",")
    identities = [item[4:] for item in entries if item.startswith("URI:feclora-client-")]
    if len(identities) != 1 or len(entries) != 1 or not _CLIENT_ID.fullmatch(identities[0]):
        raise PKIError("CSR must contain exactly one Feclora Client URI SAN")
    return "URI:feclora-client-" + identities[0]


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
    extension_file = os.path.join(root, ".client-extensions.tmp")
    temporary = output_certificate + ".tmp"
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
        _regular_file(path, label)
    actual_fingerprint = ca_fingerprint(ca_path, runner=runner, openssl=openssl)
    if actual_fingerprint != expected_fingerprint.replace(":", "").lower():
        raise PKIError("CA fingerprint does not match the fingerprint verified from the Server")
    _run([openssl, "verify", "-purpose", "sslclient", "-CAfile", ca_path, certificate_path], runner)
    san = _run([openssl, "x509", "-in", certificate_path, "-noout", "-ext", "subjectAltName"], runner)
    identity_entries = [item.strip() for item in ",".join(san.stdout.splitlines()[1:]).split(",") if item.strip()]
    if identity_entries != [expected_identity] or not expected_identity.startswith("URI:feclora-client-"):
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
