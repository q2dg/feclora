---
layout: default
title: Feclora
description: Fedora-based disk imaging, cloning, recovery and network deployment.
---

<link rel="icon" type="image/svg+xml" href="{{ '/assets/feclora-mark.svg' | relative_url }}">
<link rel="stylesheet" href="{{ '/assets/css/site.css' | relative_url }}">

<main class="landing">
  <header class="hero">
    <a class="brand" href="{{ '/' | relative_url }}" aria-label="Feclora home">
      <picture><source media="(prefers-color-scheme: dark)" srcset="{{ '/assets/feclora-logo-dark.svg' | relative_url }}"><img src="{{ '/assets/feclora-logo.svg' | relative_url }}" alt="Feclora"></picture>
    </a>
    <p class="eyebrow">FEDORA LIVE · DISK IMAGING · DEPLOYMENT</p>
    <h1>Disk imaging and recovery, with a clear path from one machine to many.</h1>
    <p class="lead">Feclora is a minimal Fedora Live appliance for capturing, restoring and cloning disks, with a Cockpit interface and network deployment workflows.</p>
    <div class="hero-actions">
      <a class="button button-primary" href="./GETTING-STARTED.html">Start with the guides</a>
      <a class="button button-secondary" href="https://github.com/q2dg/feclora">View source on GitHub</a>
    </div>
  </header>

  <section class="section" aria-labelledby="what-title">
    <p class="eyebrow">CORE WORKFLOWS</p>
    <h2 id="what-title">A focused toolset for imaging and deployment.</h2>
    <div class="feature-grid">
      <article class="feature">
        <span class="feature-number">01 · IMAGE</span>
        <h3>Capture and restore</h3>
        <p>Create manifest-backed disk and partition images, verify byte counts and SHA-256 digests, and restore to compatible targets with explicit safety checks.</p>
      </article>
      <article class="feature">
        <span class="feature-number">02 · CLONE</span>
        <h3>Clone locally or remotely</h3>
        <p>Copy disks or partitions directly, or stream a clone from a Feclora Server to an approved Client over authenticated TLS.</p>
      </article>
      <article class="feature">
        <span class="feature-number">03 · DEPLOY</span>
        <h3>Deploy across a network</h3>
        <p>Coordinate Client jobs, multicast restore and interactive or unattended PXE boot, while keeping destructive authorization explicit.</p>
      </article>
    </div>
  </section>

  <section class="status" aria-labelledby="status-title">
    <div>
      <p class="eyebrow">IMPLEMENTATION STATUS</p>
      <h2 id="status-title">Implemented capabilities, stated with their limits.</h2>
      <p>The source includes local disk/partition imaging and cloning, eligible LVM workflows, SSHFS/NFS/SMB and S3 repositories, Server/Client deployment, UDPcast multicast restore, P2V export and PXE workflows. Some advanced storage paths remain incomplete: multi-device and snapshot-aware Btrfs imaging, opened-LUKS-mapping workflows and selected recovery paths. Provider and physical-network acceptance are recorded separately from automated software tests.</p>
    </div>
    <a class="text-link" href="./FEATURE-MATRIX.html">Read the feature matrix →</a>
  </section>

  <section class="section links" aria-labelledby="learn-title">
    <p class="eyebrow">DOCUMENTATION</p>
    <h2 id="learn-title">Choose what you need to do.</h2>
    <ul>
      <li><a href="./GETTING-STARTED.html">Step-by-step operator guides</a></li>
      <li><a href="./GUIDES.html">All operator workflows</a></li>
      <li><a href="./BUILD.html">Build the Live image</a></li>
      <li><a href="./FEATURE-MATRIX.html">Features and compatibility</a></li>
      <li><a href="./REMOTE-REPOSITORIES.html">Configure image repositories</a></li>
      <li><a href="./DEPLOYMENT-SETUP.html">Set up Server and Clients</a></li>
      <li><a href="./PXE-UNATTENDED.html">Interactive and unattended PXE</a></li>
      <li><a href="./OPERATIONS.html">Backup, upgrade and rollback</a></li>
    </ul>
  </section>

  <footer class="landing-footer">
    <span>Feclora · Fedora-based imaging and deployment</span>
    <a href="https://github.com/q2dg/feclora">Source code ↗</a>
  </footer>
</main>