"""Stage the Fedora Live kernel, initramfs and squashfs for iPXE HTTP boot."""
from __future__ import annotations

import hashlib
import ipaddress
import os
import shutil
import stat
import tempfile
from pathlib import Path
from typing import Any


class LiveBootAssetError(RuntimeError):
    """The current Live media does not contain a safe PXE boot payload."""


def _digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            value.update(chunk)
    return value.hexdigest()


def _publish_readonly(source: Path, destination: Path) -> None:
    try:
        source_info = source.lstat()
    except OSError as exc:
        raise LiveBootAssetError(f"cannot inspect Live boot source {source}: {exc}") from exc
    if not stat.S_ISREG(source_info.st_mode):
        raise LiveBootAssetError(f"Live boot source is not a regular file: {source}")
    destination.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    if destination.exists() or destination.is_symlink():
        try:
            dest_info = destination.lstat()
        except OSError as exc:
            raise LiveBootAssetError(f"cannot inspect existing boot asset {destination}: {exc}") from exc
        if not stat.S_ISREG(dest_info.st_mode) or _digest(source) != _digest(destination):
            raise LiveBootAssetError(f"refusing to replace a different or non-regular boot asset: {destination}")
        os.chmod(destination, 0o444)
        return
    fd, temporary = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
    try:
        with os.fdopen(fd, "wb") as output, source.open("rb") as input_file:
            shutil.copyfileobj(input_file, output, length=1024 * 1024)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, 0o444)
        os.link(temporary, destination)
        os.unlink(temporary)
    except OSError as exc:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise LiveBootAssetError(f"cannot stage Live boot asset {destination}: {exc}") from exc


def render_ipxe_script(address: str, http_port: int = 8080) -> str:
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError as exc:
        raise LiveBootAssetError("PXE boot address must be IPv4") from exc
    if parsed.version != 4 or parsed.is_unspecified or parsed.is_loopback or parsed.is_multicast:
        raise LiveBootAssetError("PXE boot address must be usable unicast IPv4")
    if isinstance(http_port, bool) or not isinstance(http_port, int) or not 1 <= http_port <= 65535:
        raise LiveBootAssetError("PXE HTTP port is invalid")
    base = f"http://{parsed}:{http_port}/live"
    unattended = f"http://{parsed}:{http_port}/unattended-answer.ipxe"
    return (
        "#!ipxe\n"
        "dhcp\n"
        "set live_base " + base + "\n"
        "menu Feclora Live PXE\n"
        "item interactive Boot interactive Feclora Live session\n"
        "item unattended Unattended signed answer-file restore\n"
        "choose pxe_mode || exit\n"
        "goto ${pxe_mode}\n"
        ":interactive\n"
        "kernel ${live_base}/vmlinuz root=live:${live_base}/squashfs.img ro rd.live.image "
        "ip=dhcp rd.neednet=1 feclora.pxe_mode=interactive\n"
        "initrd ${live_base}/initrd.img\n"
        "boot\n"
        ":unattended\n"
        f"chain {unattended} || goto unattended_missing\n"
        ":unattended_missing\n"
        "echo No active signed unattended answer-file handoff is published by this Server.\n"
        "shell\n"
    )


def _answer_job_id(job_id: str) -> str:
    import uuid
    try:
        canonical = str(uuid.UUID(job_id))
    except (ValueError, TypeError, AttributeError) as exc:
        raise LiveBootAssetError("unattended PXE answer job ID must be a UUID") from exc
    if canonical != job_id:
        raise LiveBootAssetError("unattended PXE answer job ID must use canonical UUID notation")
    return canonical


def render_unattended_answer_ipxe_script(
    address: str,
    job_id: str,
    answer_url: str,
    http_port: int = 8080,
) -> str:
    """Render an identity-free Live boot handoff to a plain HTTP JSON answer."""
    from urllib.parse import urlsplit

    try:
        parsed = ipaddress.ip_address(address)
    except ValueError as exc:
        raise LiveBootAssetError("PXE boot address must be IPv4") from exc
    if parsed.version != 4 or parsed.is_unspecified or parsed.is_loopback or parsed.is_multicast:
        raise LiveBootAssetError("PXE boot address must be usable unicast IPv4")
    if isinstance(http_port, bool) or not isinstance(http_port, int) or not 1 <= http_port <= 65535:
        raise LiveBootAssetError("PXE HTTP port is invalid")
    canonical_job_id = _answer_job_id(job_id)
    expected_answer = f"http://{parsed}:{http_port}/answers/{canonical_job_id}/answer.json"
    if answer_url != expected_answer:
        raise LiveBootAssetError("PXE answer URL must match this Server, port and canonical job UUID")
    parsed_url = urlsplit(answer_url)
    if (parsed_url.scheme != "http" or parsed_url.username is not None
            or parsed_url.password is not None or parsed_url.query or parsed_url.fragment):
        raise LiveBootAssetError("PXE answer URL is not a plain Caddy answer URL")
    live_base = f"http://{parsed}:{http_port}/live"
    return (
        "#!ipxe\\n"
        "dhcp\\n"
        f"kernel {live_base}/vmlinuz root=live:{live_base}/squashfs.img ro rd.live.image "
        f"ip=dhcp rd.neednet=1 feclora.pxe_mode=unattended-answer "
        f"feclora.pxe_job_id={canonical_job_id} "
        f"feclora.pxe_answer_url={answer_url}\\n"
        f"initrd {live_base}/initrd.img\\n"
        "boot\\n"
    )



def _safe_http_root(http_root: str) -> Path:
    root = Path(http_root)
    try:
        info = root.lstat()
    except OSError as exc:
        raise LiveBootAssetError(f"PXE HTTP root is unavailable: {exc}") from exc
    if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)
            or info.st_uid != os.geteuid() or info.st_mode & 0o022
            or info.st_mode & 0o005 != 0o005):
        raise LiveBootAssetError("PXE HTTP root must be owned by the publisher and not group/other-writable")
    return root


def publish_unattended_answer_ipxe_script(
    http_root: str,
    address: str,
    job_id: str,
    answer_url: str,
    http_port: int = 8080,
) -> str:
    """Atomically publish one answer-specific, identity-free iPXE script."""
    target_root = _safe_http_root(http_root)
    content = render_unattended_answer_ipxe_script(
        address, job_id, answer_url, http_port,
    )
    destination = target_root / "unattended-answer.ipxe"
    if os.path.lexists(destination):
        existing = destination.lstat()
        if (not stat.S_ISREG(existing.st_mode) or stat.S_ISLNK(existing.st_mode)
                or existing.st_uid != os.geteuid() or existing.st_mode & 0o022):
            raise LiveBootAssetError("refusing to replace an unsafe unattended answer boot script")
        try:
            current = destination.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise LiveBootAssetError(f"cannot inspect existing unattended answer script: {exc}") from exc
        if current != content:
            raise LiveBootAssetError("a different unattended PXE answer job is already published")
        return str(destination)
    fd, temporary = tempfile.mkstemp(prefix=".unattended-answer.ipxe.", dir=target_root)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, 0o444)
        try:
            os.link(temporary, destination)
        except FileExistsError as exc:
            raise LiveBootAssetError("another unattended PXE answer job was published concurrently") from exc
        os.unlink(temporary)
        directory_fd = os.open(target_root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except LiveBootAssetError:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    except OSError as exc:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise LiveBootAssetError(f"cannot publish unattended PXE answer script: {exc}") from exc
    return str(destination)


def revoke_unattended_answer_ipxe_script(http_root: str, job_id: str) -> bool:
    """Remove only a safe answer-specific script whose public job ID matches."""
    target_root = _safe_http_root(http_root)
    canonical_job_id = _answer_job_id(job_id)
    destination = target_root / "unattended-answer.ipxe"
    try:
        info = destination.lstat()
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise LiveBootAssetError(f"cannot inspect unattended answer boot script: {exc}") from exc
    if (not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)
            or info.st_uid != os.geteuid() or info.st_mode & 0o022 or info.st_size > 8192):
        raise LiveBootAssetError("unattended answer boot script is not a safe regular file")
    try:
        current = destination.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise LiveBootAssetError(f"cannot read unattended answer boot script: {exc}") from exc
    if (not current.startswith("#!ipxe\n")
            or current.count(f"feclora.pxe_job_id={canonical_job_id}") != 1
            or "feclora.pxe_mode=unattended-answer" not in current
            or f"/answers/{canonical_job_id}/answer.json" not in current
            or f"/answers/{canonical_job_id}/answer.minisig" not in current):
        raise LiveBootAssetError("unattended answer boot script belongs to a different job; refusing to revoke it")
    destination.unlink()
    directory_fd = os.open(target_root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    return True


def clear_stale_unattended_ipxe_script(http_root: str) -> bool:
    """Remove stale legacy and answer-specific handoff scripts before PXE starts."""
    target_root = _safe_http_root(http_root)
    removed = False
    for name in ("unattended.ipxe", "unattended-answer.ipxe"):
        destination = target_root / name
        try:
            info = destination.lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise LiveBootAssetError(f"cannot inspect stale unattended PXE script: {exc}") from exc
        if (not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)
                or info.st_uid != os.geteuid() or info.st_mode & 0o022 or info.st_size > 8192):
            raise LiveBootAssetError(f"stale unattended PXE script {name} is not a safe regular file")
        destination.unlink()
        removed = True
    if removed:
        directory_fd = os.open(target_root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    return removed


def stage_live_boot_assets(
    live_root: str,
    http_root: str,
    *,
    address: str,
    http_port: int = 8080,
) -> dict[str, str]:
    """Publish kernel/initramfs/squashfs from mounted Fedora Live media."""
    source_root = Path(live_root)
    if source_root.is_symlink() or not source_root.is_dir():
        raise LiveBootAssetError("Live media root must be a real mounted directory")
    target_root = Path(http_root)
    target_root.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    if target_root.parent.is_symlink() or not target_root.parent.is_dir():
        raise LiveBootAssetError("HTTP parent root must be a real directory")
    os.chmod(target_root.parent, 0o755)
    target_root.mkdir(mode=0o755, parents=True, exist_ok=True)
    if target_root.is_symlink() or not target_root.is_dir():
        raise LiveBootAssetError("HTTP root must be a real directory")
    os.chmod(target_root, 0o755)
    live_target = target_root / "live"
    live_target.mkdir(mode=0o755, exist_ok=True)
    if live_target.is_symlink() or not live_target.is_dir():
        raise LiveBootAssetError("HTTP live payload directory must be a real directory")
    os.chmod(live_target, 0o755)
    sources = {
        "vmlinuz": source_root / "images" / "pxeboot" / "vmlinuz",
        "initrd.img": source_root / "images" / "pxeboot" / "initrd.img",
        "squashfs.img": source_root / "LiveOS" / "squashfs.img",
    }
    staged: dict[str, str] = {}
    for name, source in sources.items():
        destination = target_root / "live" / name
        _publish_readonly(source, destination)
        staged[name] = str(destination)
    script = render_ipxe_script(address, http_port)
    script_path = target_root / "boot.ipxe"
    if script_path.exists() or script_path.is_symlink():
        try:
            info = script_path.lstat()
        except OSError as exc:
            raise LiveBootAssetError(f"cannot inspect existing iPXE script: {exc}") from exc
        if not stat.S_ISREG(info.st_mode) or script_path.read_text(encoding="utf-8") != script:
            raise LiveBootAssetError("refusing to replace a different or non-regular boot.ipxe")
        os.chmod(script_path, 0o444)
    else:
        fd, temporary = tempfile.mkstemp(prefix=".boot.ipxe.", dir=target_root)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as output:
                output.write(script)
                output.flush()
                os.fsync(output.fileno())
            os.chmod(temporary, 0o444)
            os.link(temporary, script_path)
            os.unlink(temporary)
        except OSError as exc:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise LiveBootAssetError(f"cannot stage iPXE boot script: {exc}") from exc
    staged["boot.ipxe"] = str(script_path)
    return staged
