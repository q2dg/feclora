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
