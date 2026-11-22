#!/usr/bin/env python3
"""Boot the Feclora ISO in BIOS and UEFI QEMU guests and verify kiosk readiness."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time


OVMF_PATHS = (
    ("/usr/share/edk2/ovmf/OVMF_CODE.fd", "/usr/share/edk2/ovmf/OVMF_VARS.fd"),
    ("/usr/share/OVMF/OVMF_CODE.fd", "/usr/share/OVMF/OVMF_VARS.fd"),
)


def _tail(path: Path) -> str:
    if not path.is_file():
        return "(QEMU did not write a log.)"
    return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-40:])


def _connect(
    path: Path, process: subprocess.Popen[bytes], timeout: float, log: Path
) -> socket.socket:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"QEMU exited early:\n{_tail(log)}")
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            connection.connect(str(path))
            connection.settimeout(1)
            return connection
        except OSError:
            connection.close()
            time.sleep(0.2)
    raise TimeoutError(f"QEMU did not open its boot-smoke channel.\n{_tail(log)}")


def _ovmf_paths(code: Path | None, vars_template: Path | None) -> tuple[Path, Path]:
    if code is not None or vars_template is not None:
        if code is None or vars_template is None:
            raise ValueError("Pass both --ovmf-code and --ovmf-vars for UEFI testing.")
        if not code.is_file() or not vars_template.is_file():
            raise FileNotFoundError("The specified OVMF CODE or VARS image does not exist.")
        return code, vars_template

    env_code = os.environ.get("OVMF_CODE")
    env_vars = os.environ.get("OVMF_VARS")
    if env_code or env_vars:
        if not env_code or not env_vars:
            raise ValueError("Set both OVMF_CODE and OVMF_VARS to test UEFI.")
        return _ovmf_paths(Path(env_code), Path(env_vars))

    for code_candidate, vars_candidate in OVMF_PATHS:
        code_path, vars_path = Path(code_candidate), Path(vars_candidate)
        if code_path.is_file() and vars_path.is_file():
            return code_path, vars_path
    raise FileNotFoundError(
        "UEFI firmware was not found. Pass --ovmf-code and --ovmf-vars "
        "using the paths reported by rpm -ql edk2-ovmf."
    )


def _run_guest(
    *,
    qemu: str,
    iso: Path,
    firmware: str,
    timeout: int,
    ovmf_code: Path | None,
    ovmf_vars: Path | None,
) -> None:
    with tempfile.TemporaryDirectory(prefix="feclora-boot-smoke-") as directory:
        work = Path(directory)
        channel = work / "boot-smoke.sock"
        log = work / "qemu.log"
        command = [
            qemu,
            "-m",
            "4096",
            "-smp",
            "2",
            "-display",
            "none",
            "-monitor",
            "none",
            "-serial",
            "none",
            "-nic",
            "none",
            "-device",
            "virtio-serial-pci",
            "-chardev",
            f"socket,id=boot-smoke,path={channel},server=on,wait=off",
            "-device",
            "virtserialport,chardev=boot-smoke,name=org.feclora.boot-smoke",
            "-cdrom",
            str(iso),
            "-boot",
            "order=d",
        ]
        if os.access("/dev/kvm", os.R_OK | os.W_OK):
            command.append("-enable-kvm")
        if firmware == "UEFI":
            assert ovmf_code is not None and ovmf_vars is not None
            writable_vars = work / "OVMF_VARS.fd"
            shutil.copyfile(ovmf_vars, writable_vars)
            command.extend(
                [
                    "-drive",
                    f"if=pflash,format=raw,readonly=on,file={ovmf_code}",
                    "-drive",
                    f"if=pflash,format=raw,file={writable_vars}",
                ]
            )

        with log.open("wb") as output:
            process = subprocess.Popen(command, stdout=output, stderr=subprocess.STDOUT)
            try:
                connection = _connect(channel, process, min(timeout, 30), log)
                with connection:
                    deadline = time.monotonic() + timeout
                    buffer = b""
                    last_event = "(no guest status received)"
                    while time.monotonic() < deadline:
                        if process.poll() is not None:
                            raise RuntimeError(
                                f"{firmware} QEMU guest exited before reporting readiness.\n"
                                f"Last guest status: {last_event}\n{_tail(log)}"
                            )
                        try:
                            chunk = connection.recv(4096)
                        except TimeoutError:
                            continue
                        if not chunk:
                            raise RuntimeError(
                                f"{firmware} boot-smoke channel closed unexpectedly.\n{_tail(log)}"
                            )
                        buffer += chunk
                        while b"\n" in buffer:
                            line, buffer = buffer.split(b"\n", 1)
                            event = line.decode("utf-8", errors="replace").strip()
                            if not event.startswith("FECLORA_BOOT_SMOKE "):
                                continue
                            last_event = event
                            if event == "FECLORA_BOOT_SMOKE ready":
                                print(
                                    f"{firmware}: Cockpit HTTP 200, Wayland socket and Firefox are ready."
                                )
                                return
                            if event.startswith("FECLORA_BOOT_SMOKE fallback-ready-http-"):
                                status = event.removeprefix(
                                    "FECLORA_BOOT_SMOKE fallback-ready-http-"
                                )
                                raise RuntimeError(
                                    f"{firmware} Cockpit returned HTTP {status}; "
                                    "the local diagnostic screen, Wayland and Firefox are ready."
                                )
                    raise TimeoutError(
                        f"{firmware} guest did not reach kiosk readiness within {timeout}s.\n"
                        f"Last guest status: {last_event}\n{_tail(log)}"
                    )
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iso", required=True, type=Path, help="Built Feclora Live ISO")
    parser.add_argument("--qemu", default="qemu-system-x86_64", help="QEMU system binary")
    parser.add_argument("--timeout", default=300, type=int, help="Per-firmware timeout in seconds")
    parser.add_argument("--ovmf-code", type=Path, help="UEFI OVMF_CODE image")
    parser.add_argument("--ovmf-vars", type=Path, help="UEFI OVMF_VARS template")
    args = parser.parse_args()

    if not args.iso.is_file():
        parser.error(f"ISO does not exist: {args.iso}")
    if args.timeout <= 0:
        parser.error("--timeout must be a positive number of seconds.")
    qemu = shutil.which(args.qemu)
    if qemu is None:
        parser.error(f"QEMU executable not found: {args.qemu}")
    try:
        ovmf_code, ovmf_vars = _ovmf_paths(args.ovmf_code, args.ovmf_vars)
        for firmware in ("BIOS", "UEFI"):
            _run_guest(
                qemu=qemu,
                iso=args.iso.resolve(),
                firmware=firmware,
                timeout=args.timeout,
                ovmf_code=ovmf_code if firmware == "UEFI" else None,
                ovmf_vars=ovmf_vars if firmware == "UEFI" else None,
            )
    except (FileNotFoundError, OSError, RuntimeError, TimeoutError, ValueError) as error:
        print(f"Boot smoke test failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
