---
layout: default
title: Getting started
---

<link rel="stylesheet" href="{{ '/assets/css/site.css' | relative_url }}">

<main class="guide-page">
  <header class="guide-intro">
    <p class="eyebrow">FIRST STEPS</p>
    <h1>Use Feclora safely</h1>
    <p>Feclora runs as a temporary Fedora Live system. Start with a small, reversible task to understand the interface before performing a restore or clone.</p>
    <div class="guide-note"><strong>Important:</strong> restoring or cloning overwrites the selected destination. Use disposable media for practice and verify device identity by model, capacity and stable identifiers—not by a device path alone.</div>
  </header>

  <section class="section">
    <h2>1. Prepare the environment</h2>
    <ol>
      <li>Obtain a Feclora ISO from a trusted source and verify its published SHA-256 when one is available.</li>
      <li>Boot the Live system. Feclora starts the Cockpit application in a restricted browser kiosk; it is not a general-purpose desktop.</li>
      <li>Complete the first-boot administrator password setup and open the local Cockpit interface.</li>
      <li>Configure the network only if you need a remote repository, a Server/Client workflow or PXE.</li>
    </ol>
    <p><a href="./BUILD.html">Build and boot instructions →</a></p>
  </section>

  <section class="section">
    <h2>2. Add an image repository</h2>
    <ol>
      <li>Open the repository configuration in Cockpit.</li>
      <li>Select a supported provider: local filesystem, SSHFS, NFS, SMB/CIFS or S3-compatible object storage.</li>
      <li>Enter the endpoint and access details in the protected UI. Never put credentials in documentation, screenshots or PXE answer files.</li>
      <li>Test the connection and confirm that the expected repository is visible before capturing data.</li>
    </ol>
    <p><a href="./REMOTE-REPOSITORIES.html">Repository setup and provider limits →</a></p>
  </section>

  <section class="section">
    <h2>3. Capture a source disk</h2>
    <div class="guide-grid">
      <article class="guide-card">
        <img src="{{ '/assets/mockups/capture-wizard.svg' | relative_url }}" alt="Illustrative mockup of source selection in the capture wizard">
        <div class="guide-card-body"><p>Illustrative view of a source-selection step. Device names and capacities are fictional.</p></div>
      </article>
      <div>
        <ol>
          <li>Open <strong>Operations</strong> and choose whole-disk capture.</li>
          <li>Select the source after checking model, size and device identity. Feclora applies read-only and mounted-source safety checks.</li>
          <li>Choose the destination repository, image identifier, compression and optional age encryption.</li>
          <li>Review the summary and start capture. Keep the source connected until the operation completes.</li>
          <li>Confirm that the image manifest appears in inventory and that integrity metadata is present.</li>
        </ol>
        <p><a href="./WHOLE-DISK-CAPTURE.html">Detailed whole-disk capture guide →</a></p>
      </div>
    </div>
  </section>

  <section class="section">
    <h2>4. Restore only after checking the target</h2>
    <div class="guide-grid">
      <article class="guide-card">
        <img src="{{ '/assets/mockups/restore-wizard.svg' | relative_url }}" alt="Illustrative mockup of destination review in the restore wizard">
        <div class="guide-card-body"><p>Illustrative destination review. This is not a screenshot of a running system.</p></div>
      </article>
      <div>
        <ol>
          <li>Select a verified whole-disk image from the repository.</li>
          <li>Choose a destination disk that is equal to or larger than the source and has a compatible logical sector size.</li>
          <li>Check the destination model, capacity and stable identity again. Do not rely on <code>/dev/sdX</code> alone.</li>
          <li>Read the destructive warning and type the exact confirmation requested by Cockpit.</li>
          <li>Start restore and wait for read-back verification. An interrupted write can leave the destination partially overwritten.</li>
        </ol>
        <p><a href="./WHOLE-DISK-RESTORE.html">Detailed whole-disk restore guide →</a></p>
      </div>
    </div>
  </section>

  <section class="section">
    <h2>5. Move on to cloning and network deployment</h2>
    <p>Local disk cloning, remote Server/Client cloning, multicast restore and PXE are separate workflows with additional trust and safety requirements. Follow their dedicated guides rather than inferring that one workflow authorizes another.</p>
    <p><a href="./GUIDE-LOCAL-DISK-CLONE.html">Local cloning →</a> · <a href="./DEPLOYMENT-SETUP.html">Server/Client setup →</a> · <a href="./PXE-UNATTENDED.html">PXE deployment →</a></p>
  </section>

  <section class="section">
    <h2>What Feclora does not do</h2>
    <ul>
      <li>The Live root and session credentials are ephemeral; images belong in an external or separately selected repository.</li>
      <li>Image manifests record size and SHA-256 but are not digitally signed.</li>
      <li>Advanced Btrfs multi-device/snapshot imaging and opened-LUKS-mapping image workflows are not complete.</li>
      <li>Feclora does not automatically roll back or resume an interrupted destructive write.</li>
    </ul>
    <p><a href="./FEATURE-MATRIX.html">Full feature and compatibility matrix →</a></p>
  </section>
</main>