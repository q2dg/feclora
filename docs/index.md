---
layout: default
title: Feclora
description: Fedora-based disk imaging, cloning and recovery.
---

<link rel="stylesheet" href="{{ '/assets/css/site.css' | relative_url }}">

<main class="landing">
  <header class="hero">
    <p class="eyebrow">FEDORA-BASED RESCUE & DEPLOYMENT</p>
    <h1>Feclora</h1>
    <p class="lead">Disk imaging, cloning and recovery — built around Fedora and guided by Cockpit.</p>
    <div class="hero-actions">
      <a class="button button-primary" href="https://github.com/q2dg/feclora">View source on GitHub</a>
      <a class="button button-secondary" href="./COCKPIT.html">Explore the interface</a>
    </div>
  </header>

  <section class="section" aria-labelledby="what-title">
    <p class="eyebrow">WHAT IT DOES</p>
    <h2 id="what-title">One toolkit for local and network workflows.</h2>
    <div class="feature-grid">
      <article class="feature">
        <span class="feature-number">01</span>
        <h3>Capture & restore</h3>
        <p>Capture and restore whole disks, partitions and eligible active LVM logical volumes. Image sets include manifests, byte counts and SHA-256 verification; optional age encryption is supported.</p>
      </article>
      <article class="feature">
        <span class="feature-number">02</span>
        <h3>Clone & convert</h3>
        <p>Clone whole disks and partitions locally or through authenticated Server/Client jobs. Convert offline physical disks to QCOW2 with P2V metadata.</p>
      </article>
      <article class="feature">
        <span class="feature-number">03</span>
        <h3>Deploy over a network</h3>
        <p>Manage Clients, transfer images over authenticated TLS, restore to multiple Clients with UDPcast multicast, and boot the Live environment interactively or through an unattended PXE answer workflow.</p>
      </article>
    </div>
  </section>

  <section class="status" aria-labelledby="status-title">
    <div>
      <p class="eyebrow">PROJECT STATUS</p>
      <h2 id="status-title">Broad implementation; release acceptance remains.</h2>
      <p>The source and Cockpit application include local imaging, storage and image inventories, durable operation history, SSHFS/NFS/SMB filesystem repositories, S3 object storage, authenticated Server/Client deployment, unicast transfer, multicast restore, remote disk/partition cloning, P2V conversion/export, interactive PXE and unattended whole-disk restore. These are implementation claims, not proof of end-to-end release acceptance.</p>
      <p>Remaining software work includes completing and validating selected storage-layer workflows (notably Btrfs multi-device/snapshot-aware imaging and opened-LUKS-mapping workflows), closing repository-provider I/O and recovery gaps, expanding unattended-PXE failure-path and result handling, and finishing localization coverage. ISO generation, BIOS/UEFI boot, destructive restore, multi-host networking, UDPcast/IGMP and representative hardware still require operator-run acceptance on disposable equipment. See the <a href="./FEATURE-MATRIX.html">feature matrix</a> and <a href="./ROADMAP.html">roadmap</a> for the authoritative status and limitations.</p>
    </div>
    <a class="text-link" href="./ROADMAP.html">See what is next →</a>
  </section>

  <section class="section links" aria-labelledby="learn-title">
    <p class="eyebrow">LEARN MORE</p>
    <h2 id="learn-title">Project resources</h2>
    <ul>
      <li><a href="./GUIDES.html">Step-by-step operator guides</a></li>
      <li><a href="./BUILD.html">Build and installation</a></li>
      <li><a href="./FEATURE-MATRIX.html">Features and compatibility</a></li>
      <li><a href="./CERTIFICATE-MANAGEMENT.html">Security and certificates</a></li>
      <li><a href="./DEPLOYMENT-SETUP.html">Network deployment setup</a></li>
    </ul>
  </section>

  <footer class="landing-footer">
    <span>Feclora · Project source</span>
    <a href="https://github.com/q2dg/feclora">GitHub repository ↗</a>
  </footer>
</main>
