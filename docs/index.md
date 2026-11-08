---
layout: default
title: Feclora
description: Fedora-based disk imaging, cloning and recovery.
---

<link rel="stylesheet" href="./assets/css/site.css">

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
        <p>Create and restore whole-disk or partition images with manifests, SHA-256 verification and optional encryption.</p>
      </article>
      <article class="feature">
        <span class="feature-number">02</span>
        <h3>Clone</h3>
        <p>Copy disks or partitions directly, with explicit target checks and destructive-operation confirmation.</p>
      </article>
      <article class="feature">
        <span class="feature-number">03</span>
        <h3>Deploy over a network</h3>
        <p>Server/Client deployment engines, PXE/iPXE boot and multicast restore foundations for managed environments.</p>
      </article>
    </div>
  </section>

  <section class="status" aria-labelledby="status-title">
    <div>
      <p class="eyebrow">PROJECT STATUS</p>
      <h2 id="status-title">Implemented in stages. Not yet lab-certified.</h2>
      <p>The Cockpit interface currently guides local capture, restore and clone operations. Remote Server/Client setup and deployment orchestration are still being integrated into Cockpit.</p>
    </div>
    <a class="text-link" href="./ROADMAP.html">See what is next →</a>
  </section>

  <section class="section links" aria-labelledby="learn-title">
    <p class="eyebrow">LEARN MORE</p>
    <h2 id="learn-title">Project resources</h2>
    <ul>
      <li><a href="./BUILD.html">Build and installation</a></li>
      <li><a href="./FEATURE-MATRIX.html">Features and compatibility</a></li>
      <li><a href="./CERTIFICATE-MANAGEMENT.html">Security and certificates</a></li>
      <li><a href="./DEPLOYMENT-SETUP.html">Network deployment setup</a></li>
      <li><a href="./CLONEZILLA-FEATURE-PARITY.html">Clonezilla feature comparison</a></li>
    </ul>
  </section>

  <footer class="landing-footer">
    <span>Feclora · Open source project</span>
    <a href="https://github.com/q2dg/feclora">GitHub repository ↗</a>
  </footer>
</main>
