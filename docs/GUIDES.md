---
layout: default
title: Operator guides
---

<link rel="stylesheet" href="{{ '/assets/css/site.css' | relative_url }}">
{% include brand-header.html %}

<link rel="stylesheet" href="{{ '/assets/css/site.css' | relative_url }}">

<main class="guide-page">
  <header class="guide-intro">
    <p class="eyebrow">OPERATOR DOCUMENTATION</p>
    <h1>Step-by-step guides</h1>
    <p>Choose a task, follow the sequence and review the safety checks before starting. These guides describe the current Cockpit workflows; availability and limitations are called out explicitly.</p>
    <div class="guide-note"><strong>Before any destructive operation:</strong> identify disks by model, capacity and stable identifiers where available. A restore or clone can overwrite the selected destination and cannot be rolled back automatically.</div>
  </header>

  <section class="guide-grid" aria-label="Operator workflow guides">
    <article class="guide-card">
      <img src="{{ '/assets/mockups/capture-wizard.svg' | relative_url }}" alt="Illustrative mockup of the disk capture wizard">
      <div class="guide-card-body"><h2>Capture a disk or partition</h2><p>Create a manifest-backed image in a configured repository. Review source safety, compression and optional image encryption.</p><a href="./WHOLE-DISK-CAPTURE.html">Whole-disk capture →</a> · <a href="./PARTITION-CAPTURE.html">Partition capture →</a></div>
    </article>
    <article class="guide-card">
      <img src="{{ '/assets/mockups/restore-wizard.svg' | relative_url }}" alt="Illustrative mockup of the restore destination review">
      <div class="guide-card-body"><h2>Restore an image</h2><p>Select a verified image, inspect the destination and confirm the exact target before writing.</p><a href="./WHOLE-DISK-RESTORE.html">Whole-disk restore →</a> · <a href="./PARTITION-RESTORE.html">Partition restore →</a></div>
    </article>
    <article class="guide-card">
      <img src="{{ '/assets/mockups/network-deployment.svg' | relative_url }}" alt="Illustrative mockup of Server and Client deployment status">
      <div class="guide-card-body"><h2>Deploy to other machines</h2><p>Prepare the Server, trust it from each Client, approve local destinations and explicitly arm the job.</p><a href="./DEPLOYMENT-SETUP.html">Server and Client setup →</a> · <a href="./REMOTE-DISK-CLONE.html">Remote cloning →</a></div>
    </article>
    <article class="guide-card">
      <div class="guide-card-body"><h2>Clone a local disk</h2><p>Copy one local block device to another without creating an intermediate image file.</p><a href="./GUIDE-LOCAL-DISK-CLONE.html">Local disk clone procedure →</a></div>
    </article>
    <article class="guide-card">
      <div class="guide-card-body"><h2>Connect image repositories</h2><p>Configure mounted filesystem repositories or S3-compatible object storage and understand credential handling.</p><a href="./REMOTE-REPOSITORIES.html">Repository setup and behavior →</a></div>
    </article>
    <article class="guide-card">
      <div class="guide-card-body"><h2>Boot over the network</h2><p>Understand interactive PXE and the unattended answer-file workflow, including its security boundary.</p><a href="./PXE-UNATTENDED.html">PXE workflow and setup →</a></div>
    </article>
  </section>

  <p class="guide-note">The illustrations on this page are <strong>illustrative mockups, not screenshots from a running Feclora system</strong>. They explain the intended operator flow and do not prove runtime acceptance. See the <a href="./assets/screenshots/README.html">image policy</a> for real screenshots and mockups.</p>

  <section class="section">
    <h2>Reference and operations</h2>
    <ul>
      <li><a href="./FEATURE-MATRIX.html">Feature and compatibility matrix</a></li>
      <li><a href="./CERTIFICATE-MANAGEMENT.html">Certificate and enrollment policy</a></li>
      <li><a href="./OPERATIONS.html">Backup, upgrade, rollback and distribution</a></li>
      <li><a href="./BUILD.html">Build instructions</a></li>
      <li><a href="./MAINTAINER-ACCEPTANCE.html">Maintainer-owned release acceptance</a></li>
    </ul>
  </section>
</main>