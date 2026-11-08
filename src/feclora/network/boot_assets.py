"""Stage packaged iPXE firmware assets into a read-only PXE boot tree."""
from __future__ import annotations

import hashlib
import os
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable


class BootAssetError(RuntimeError):
    """The packaged iPXE boot assets cannot be staged safely."""

def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _package_files(
    package: str,
    *,
    rpm: str,
    runner: Callable[..., Any],
) -> list[Path]:
    try:
        result = runner(
            [rpm, "-ql", package], check=True, capture_output=True,
            text=True, timeout=20,
        )
    except subprocess.TimeoutExpired as exc:
        raise BootAssetError("RPM file-list query timed out") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or "").strip()
        raise BootAssetError(detail or f"cannot query installed package {package}") from exc
    return [Path(line.strip()) for line in result.stdout.splitlines() if line.strip()]


def stage_ipxe_assets(
    destination: str,
    *,
    bios_filename: str = "undionly.kpxe",
    uefi_filename: str = "ipxe-snponly-x86_64.efi",
    package: str = "ipxe-bootimgs-x86",
    rpm: str | None = None,
    runner: Callable[..., Any] = subprocess.run,
    owner_uid: int | None = None,
    owner_gid: int | None = None,
) -> dict[str, str]:
    """Locate firmware by RPM ownership, then atomically copy regular files."""
    rpm_bin = rpm or shutil.which("rpm")
    if not rpm_bin:
        raise BootAssetError("rpm is required to locate packaged iPXE firmware")
    for name in (bios_filename, uefi_filename):
        if not name or Path(name).name != name or name in {".", ".."}:
            raise BootAssetError("iPXE firmware names must be simple filenames")
    candidates = _package_files(package, rpm=rpm_bin, runner=runner)
    staged: dict[str, str] = {}
    target = Path(destination)
    target.mkdir(mode=0o755, parents=True, exist_ok=True)
    if target.is_symlink() or not target.is_dir():
        raise BootAssetError("TFTP root must be a real directory")
    os.chmod(target, 0o755)
    for filename in (bios_filename, uefi_filename):
        matches = [path for path in candidates if path.name == filename]
        if len(matches) != 1:
            raise BootAssetError(
                f"expected exactly one {filename} in RPM package {package}; found {len(matches)}"
            )
        source = matches[0]
        try:
            info = source.lstat()
        except OSError as exc:
            raise BootAssetError(f"cannot inspect packaged firmware {source}: {exc}") from exc
        if not stat.S_ISREG(info.st_mode):
            raise BootAssetError(f"packaged firmware is not a regular file: {source}")
        destination_path = target / filename
        if destination_path.exists() or destination_path.is_symlink():
            try:
                existing = destination_path.lstat()
            except OSError as exc:
                raise BootAssetError(f"cannot inspect existing boot asset {destination_path}: {exc}") from exc
            if not stat.S_ISREG(existing.st_mode) or _sha256(source) != _sha256(destination_path):
                raise BootAssetError(f"refusing to replace a different or non-regular boot asset: {destination_path}")
            os.chmod(destination_path, 0o444)
            if owner_uid is not None or owner_gid is not None:
                os.chown(destination_path, owner_uid if owner_uid is not None else -1, owner_gid if owner_gid is not None else -1)
            staged[filename] = str(destination_path)
            continue
        fd, temporary = tempfile.mkstemp(prefix=f".{filename}.", dir=target)
        try:
            with os.fdopen(fd, "wb") as output, source.open("rb") as input_file:
                shutil.copyfileobj(input_file, output, length=1024 * 1024)
                output.flush()
                os.fsync(output.fileno())
            os.chmod(temporary, 0o444)
            if owner_uid is not None or owner_gid is not None:
                os.chown(temporary, owner_uid if owner_uid is not None else -1, owner_gid if owner_gid is not None else -1)
            os.link(temporary, destination_path)
            os.unlink(temporary)
        except OSError as exc:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise BootAssetError(f"cannot stage {filename}: {exc}") from exc
        staged[filename] = str(destination_path)
    return staged
