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
        <p>Create and restore whole-disk, partition and eligible logical-volume images with manifests, integrity verification and optional encryption.</p>
      </article>
      <article class="feature">
        <span class="feature-number">02</span>
        <h3>Clone</h3>
        <p>Clone whole disks and partitions locally; authenticated remote whole-disk cloning is implemented, with remote partition cloning still pending.</p>
      </article>
      <article class="feature">
        <span class="feature-number">03</span>
        <h3>Deploy over a network</h3>
        <p>Authenticated Server/Client deployment, unicast transfer, UDPcast multicast restore and PXE/iPXE Live boot and an initial NFS-backed unattended answer workflow.</p>
      </article>
    </div>
  </section>

  <section class="status" aria-labelledby="status-title">
    <div>
      <p class="eyebrow">PROJECT STATUS</p>
      <h2 id="status-title">Implemented in stages. Not yet lab-certified.</h2>
      <p>The Cockpit application exposes local whole-disk, partition and eligible LVM capture/restore, disk and partition cloning, storage and image inventories, and durable local-operation status. Authenticated Server/Client workflows include enrollment, deployment jobs, unicast image transfer, multicast restore and direct remote whole-disk cloning. PXE/iPXE supports interactive Live boot and an initial unattended answer-file path: the Server publishes a validated answer, Live downloads and validates it, and NFS-backed whole-disk restore uses the existing guarded restore engine. This unattended path is not yet a complete fleet solution. Remote partition cloning, complete remote-transport coverage (including WebDAV and BitTorrent), Btrfs snapshot-consistent and multi-device imaging, richer transfer telemetry and end-to-end physical acceptance remain outstanding. Source implementation and automated tests do not establish ISO boot, firmware, hardware, provider or network-lab acceptance.</p>
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
