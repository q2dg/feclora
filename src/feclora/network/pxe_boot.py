"""Assemble a complete read-only PXE boot tree from the running Fedora Live media."""
from __future__ import annotations

import pwd
from typing import Any, Callable

from feclora.network.boot_assets import stage_ipxe_assets
from feclora.network.boot_tree import stage_live_boot_assets
from feclora.network.pxe_config import PXENetworkConfig


class PXEBootTreeError(RuntimeError):
    """The PXE boot tree could not be assembled safely."""


def stage_pxe_boot_tree(
    config: PXENetworkConfig,
    *,
    live_root: str = "/run/initramfs/live",
    account_lookup: Callable[[str], Any] = pwd.getpwnam,
) -> dict[str, dict[str, str]]:
    """Stage iPXE firmware, Live kernel/initrd/squashfs and the iPXE script."""
    config.validated()
    try:
        account = account_lookup("dnsmasq")
    except KeyError as exc:
        raise PXEBootTreeError("the dnsmasq system account is required by tftp-secure") from exc
    try:
        tftp = stage_ipxe_assets(
            config.tftp_root,
            bios_filename=config.bios_boot_file,
            uefi_filename=config.uefi_boot_file,
            owner_uid=account.pw_uid,
            owner_gid=account.pw_gid,
        )
        http = stage_live_boot_assets(
            live_root,
            config.http_root,
            address=config.address,
            http_port=config.http_port,
        )
    except Exception as exc:
        raise PXEBootTreeError(f"cannot stage PXE boot assets: {exc}") from exc
    return {"tftp": tftp, "http": http}
