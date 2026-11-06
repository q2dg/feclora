# feclora

**feclora** is an independent project to build a Fedora-based live system for disk imaging, cloning, and recovery, aiming for functional coverage comparable to Clonezilla.

It is not a fork of Clonezilla and does not depend on its repository, branches, or release process. Clonezilla may be used as a functional reference during requirements analysis; implementation and project history live here.

## Initial target

- Fedora 43
- x86_64
- Clonezilla-Live-style bootable ISO
- BIOS and UEFI boot support
- Native Fedora package management and system integration
- Imaging, cloning, restoration, and storage administration

The first milestone is a reproducible bootable live ISO with a verified core workflow. Broader functionality will be added in measured, testable increments.

## Design principles

1. **Independent implementation:** no upstream submodule, tracking branch, or automatic code synchronization.
2. **Fedora-native build:** use Fedora tooling and RPM packages; evaluate Lorax/livemedia-creator, Kickstart, and dracut for the image pipeline.
3. **Modular capabilities:** keep image orchestration, storage discovery, filesystem support, networking, boot integration, and user interfaces separable.
4. **Safe operations:** make destructive actions explicit, validate source and target devices, and provide dry-run or confirmation paths where feasible.
5. **Reproducibility:** pin build inputs where practical and record package versions and build metadata.
6. **Tested compatibility:** document filesystem, partition-table, encryption, transport, firmware, and hardware coverage rather than assuming parity.

## Planned areas

- build/ — ISO build tooling
- kickstart/ — Fedora installation and live-image configuration
- packages/ — RPM package manifests
- src/ — application and orchestration code
- scripts/ — developer and operator utilities
- tests/ — unit, integration, and VM smoke tests
- docs/ — architecture, compatibility, and operational documentation

## Development status

Early project setup. No functional parity claim is made yet. The initial implementation target is a bootable Fedora 43 live image; Clonezilla-equivalent workflows will be tracked in a feature matrix and implemented incrementally.

## License

License selection is pending. Individual components and dependencies may carry their own licenses; these will be documented before code is incorporated or redistributed.
