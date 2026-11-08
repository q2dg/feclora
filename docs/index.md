---
layout: home
title: Feclora documentation
---

# Feclora

**Fedora-based disk imaging, cloning, recovery and deployment appliance.**

Feclora combines a shared Python storage engine with a Cockpit web interface.
Its goal is to provide guided local imaging and remote deployment workflows
using Fedora-native tools.

## Start here

- [Project overview](https://github.com/q2dg/feclora)
- [Build and installation](BUILD.md)
- [Cockpit interface and first login](COCKPIT.md)
- [Local imaging and cloning workflows](LOCAL-RESCUE-UI.md)
- [Feature and compatibility matrix](FEATURE-MATRIX.md)
- [Clonezilla functional comparison](CLONEZILLA-FEATURE-PARITY.md)
- [Security and certificate management](CERTIFICATE-MANAGEMENT.md)
- [Deployment setup](DEPLOYMENT-SETUP.md)
- [PXE and multicast deployment](UDPCAST-MULTICAST.md)
- [Roadmap](ROADMAP.md)

## Important status

The Cockpit application exposes local whole-disk and partition capture,
restore, disk cloning and partition cloning. Remote Server/Client provisioning
and complete PXE deployment orchestration are still being integrated into
Cockpit.

ISO generation and real BIOS/UEFI, PXE and destructive laboratory validation
are operator-owned acceptance steps. Read the [feature matrix](FEATURE-MATRIX.md)
before treating any capability as hardware-verified.
