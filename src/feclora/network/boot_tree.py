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
    return (
        "#!ipxe\n"
        "dhcp\n"
        f"kernel {base}/vmlinuz root=live:{base}/squashfs.img ro rd.live.image "
        "ip=dhcp rd.neednet=1\n"
        f"initrd {base}/initrd.img\n"
        "boot\n"
    )


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
