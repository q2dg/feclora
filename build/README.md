# Build pipeline

## Initial target

The first build target is a Fedora 43 x86_64 rescue live ISO. The build uses Lorax `livemedia-creator` with QEMU virtualization. It intentionally avoids `--no-virt`: Lorax documents that direct Anaconda/no-virt builds have a greater risk of affecting the host if Anaconda behaves unexpectedly. See the [upstream livemedia-creator documentation](https://github.com/weldr/lorax/blob/master/docs/livemedia-creator.rst).

## Static validation

Run the repository checks before building:

```bash
make validate
```

GitHub Actions runs Bash syntax checks, project-input validation, ShellCheck and the Makefile help target on pushes and pull requests. These checks do not prove that an ISO can be built or booted.

## Build host

Use a disposable Fedora 43 x86_64 virtual machine if possible. Allocate at least 4 CPU cores, 8 GiB RAM, and 30 GiB free disk space. Install dependencies:

```bash
sudo bash build/install-host-deps.sh
```

Download the Fedora 43 x86_64 **DVD installation ISO**. The DVD image is the simplest initial package source because it contains installation repositories. Then run:

```bash
sudo env FEDORA_INSTALL_ISO=/path/to/Fedora-43-x86_64-DVD.iso bash build/build-iso.sh
```

The script uses QEMU, not `--no-virt`, and writes results under `out/`. The expected ISO name is `feclora-live.iso`; inspect the complete result directory and logs before treating the build as successful.

## Important limitations

- The Kickstart is an initial recipe, not yet a validated Fedora live-media configuration.
- The live console currently uses an automatically logged-in `feclora` account with passwordless sudo. This is intentional for a physical-access rescue environment; anyone who can boot the media can obtain root. Do not use this policy on an installed system.
- BIOS and UEFI boot, Secure Boot, device discovery, and the first rescue workflow must be tested in virtual machines before a release is declared usable.
- Fedora 43 is the agreed initial baseline, but its support window is close to ending. Keep the release version configurable and plan a tested migration to a supported Fedora release.

## Troubleshooting

Preserve the entire result directory, especially Anaconda and livemedia-creator logs. Do not retry with `--no-virt` on a normal workstation as a workaround. Reproduce failures in a disposable VM and record the Fedora release, package versions, installer ISO checksum, and exact command line.
