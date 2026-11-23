---
layout: default
title: Step-by-step operator guides
---
<link rel="stylesheet" href="{{ '/assets/css/site.css' | relative_url }}">
{% include brand-header.html %}
<main class="guide-page">
<header class="guide-intro">
<p class="eyebrow">OPERATOR DOCUMENTATION</p>
<h1>Step-by-step guides</h1>
<p>Choose a task, follow its numbered sequence, then verify the result before moving on. Every operation guide includes a task-specific illustrative mockup, prerequisites, safety checks and a verification stage.</p>
<div class="guide-note"><strong>Before you begin:</strong> restore and clone operations overwrite their destination. Practise with disposable virtual disks. Confirm the model, capacity and stable device identity (WWN/serial); never select a destructive target using a transient path such as <code>/dev/sdX</code> alone.</div>
</header>
<section class="section"><h2>1. Capture and restore</h2><div class="guide-grid">
<article class="guide-card"><img src="{{ '/assets/mockups/capture-wizard.svg' | relative_url }}" alt="Mockup of whole-disk capture source selection"><div class="guide-card-body"><h3>Capture a whole disk</h3><p>Create a manifest-backed RAW or QCOW2 image.</p><a href="./WHOLE-DISK-CAPTURE.html">Follow the capture steps →</a></div></article>
<article class="guide-card"><img src="{{ '/assets/mockups/restore-wizard.svg' | relative_url }}" alt="Mockup of whole-disk restore target review"><div class="guide-card-body"><h3>Restore a whole disk</h3><p>Verify the image, inspect the destination and authorize the write.</p><a href="./WHOLE-DISK-RESTORE.html">Follow the restore steps →</a></div></article>
<article class="guide-card"><img src="{{ '/assets/mockups/partition-workflow.svg' | relative_url }}" alt="Mockup of partition capture and restore"><div class="guide-card-body"><h3>Capture or restore a partition</h3><p>Operate on an existing partition; this does not create a partition table.</p><a href="./PARTITION-CAPTURE.html">Capture →</a> · <a href="./PARTITION-RESTORE.html">Restore →</a></div></article>
</div></section>
<section class="section"><h2>2. Clone and deploy</h2><div class="guide-grid">
<article class="guide-card"><img src="{{ '/assets/mockups/local-clone.svg' | relative_url }}" alt="Mockup of local source-to-target disk cloning"><div class="guide-card-body"><h3>Clone a local disk</h3><p>Copy one block device directly to another on the same Feclora machine.</p><a href="./GUIDE-LOCAL-DISK-CLONE.html">Follow the local clone steps →</a></div></article>
<article class="guide-card"><img src="{{ '/assets/mockups/network-deployment.svg' | relative_url }}" alt="Mockup of Feclora Server and Client deployment"><div class="guide-card-body"><h3>Set up Server and Clients</h3><p>Configure the control channel, trust, targets and explicit job arming.</p><a href="./DEPLOYMENT-SETUP.html">Server/Client setup →</a> · <a href="./REMOTE-DISK-CLONE.html">Remote cloning →</a></div></article>
<article class="guide-card"><img src="{{ '/assets/mockups/certificate-trust.svg' | relative_url }}" alt="Mockup showing Server certificate and Client CA trust"><div class="guide-card-body"><h3>Configure certificate trust</h3><p>Understand the one-way TLS trust model and provision Clients safely.</p><a href="./CERTIFICATE-MANAGEMENT.html">Certificate and trust steps →</a></div></article>
<article class="guide-card"><img src="{{ '/assets/mockups/multicast-workflow.svg' | relative_url }}" alt="Mockup of multicast receiver readiness and transfer"><div class="guide-card-body"><h3>Restore to multiple Clients</h3><p>Understand receiver readiness and the UDPcast data plane.</p><a href="./UDPCAST-MULTICAST.html">Multicast workflow →</a></div></article>
</div></section>
<section class="section"><h2>3. Repositories and network boot</h2><div class="guide-grid">
<article class="guide-card"><img src="{{ '/assets/mockups/repository-setup.svg' | relative_url }}" alt="Mockup of repository provider configuration"><div class="guide-card-body"><h3>Connect an image repository</h3><p>Configure local storage, SSHFS, NFS, SMB/CIFS or S3-compatible storage.</p><a href="./REMOTE-REPOSITORIES.html">Repository setup →</a></div></article>
<article class="guide-card"><img src="{{ '/assets/mockups/p2v-export.svg' | relative_url }}" alt="Mockup of a legacy S3 P2V bundle export"><div class="guide-card-body"><h3>Export a legacy P2V bundle</h3><p>Copy a legacy QCOW2 and sidecar from S3 to a filesystem repository.</p><a href="./P2V-S3-EXPORT.html">P2V S3 export →</a></div></article>
<article class="guide-card"><img src="{{ '/assets/mockups/pxe-workflow.svg' | relative_url }}" alt="Mockup of interactive PXE and unattended answer boot"><div class="guide-card-body"><h3>Boot with PXE</h3><p>Keep interactive Live boot distinct from the narrower unattended answer workflow.</p><a href="./PXE-UNATTENDED.html">PXE guide →</a></div></article>
<article class="guide-card"><img src="{{ '/assets/mockups/recovery-workflow.svg' | relative_url }}" alt="Mockup of recovery-media assembly and validation"><div class="guide-card-body"><h3>Prepare recovery media</h3><p>Review the recovery-ISO builder and guarded boot-time restore path.</p><a href="./RECOVERY-ISO.html">Recovery ISO procedure →</a></div></article>
</div></section>
<section class="section"><h2>4. Advanced restore workflows</h2><div class="guide-grid">
<article class="guide-card"><img src="{{ '/assets/mockups/proportional-restore.svg' | relative_url }}" alt="Mockup of staged proportional restore"><div class="guide-card-body"><h3>Restore to a smaller disk</h3><p>Use the guarded GPT workflow for supported final ext2/3/4 or NTFS partitions.</p><a href="./STAGED-PROPORTIONAL-SHRINK.html">Proportional restore →</a></div></article>
<article class="guide-card"><img src="{{ '/assets/mockups/restore-profile.svg' | relative_url }}" alt="Mockup of a single-use restore profile"><div class="guide-card-body"><h3>Create and execute a restore profile</h3><p>Bind a single-use profile to a persistent repository and stable target identity.</p><a href="./RESTORE-PROFILES.html">Restore profiles →</a></div></article>
</div></section>
<div class="guide-note"><strong>How to read the illustrations:</strong> all visuals are explicitly labeled mockups, not screenshots of a running system. They explain the sequence and safety concepts; they are not evidence of runtime acceptance. For exact support boundaries, use the <a href="./FEATURE-MATRIX.html">feature and compatibility matrix</a>.</div>
<section class="section"><h2>5. Start here and keep the system healthy</h2><ul>
<li><a href="./GETTING-STARTED.html">Getting started: first safe steps</a></li>
<li><a href="./OPERATIONS.html">Operational lifecycle, backup, upgrade and rollback</a></li>
<li><a href="./BUILD.html">Build and validate the Live ISO (maintainer procedure)</a></li>
<li><a href="./MAINTAINER-ACCEPTANCE.html">Maintainer acceptance checklist</a></li>
<li><a href="./FEATURE-MATRIX.html">Feature and compatibility matrix</a></li>
<li><a href="./ROADMAP.html">Remaining engineering work and project boundaries</a></li>
</ul></section>
<details class="section" id="engineering-references"><summary><strong>Engineering references (for maintainers and contributors)</strong></summary>
<p>These pages describe implementation contracts and safety boundaries. They are not required for routine operation.</p>
<h3>Storage, artifacts and safety</h3><ul>
<li><a href="./BTRFS-SUBVOLUME-SEND-RECEIVE.html">Btrfs subvolume send/receive</a></li><li><a href="./BTRFS-SEND-MANIFEST.html">Btrfs send-stream manifest contract</a></li>
<li><a href="./STORAGE-INVENTORY.html">Read-only storage inventory</a></li><li><a href="./CAPTURE-SOURCE-SAFETY.html">Capture and restore source safety</a></li><li><a href="./SAFE-STORAGE-SELECTION.html">Safe storage selection</a></li><li><a href="./ARTIFACT-WRITER.html">Image artifact writer and atomic publication</a></li><li><a href="./IMAGE-MANIFEST.html">Image manifest contract</a></li><li><a href="./IMAGE-ENCRYPTION.html">Image encryption</a></li><li><a href="./TOOLING-AND-TRANSPORTS.html">External tools and transport boundaries</a></li><li><a href="./FILESYSTEM-SHRINK-RESEARCH.html">Filesystem shrink research checkpoint</a></li>
</ul>
<h3>Deployment and local operations</h3><ul>
<li><a href="./DEPLOYMENT-JOB.html">Deployment job schema</a></li><li><a href="./DEPLOYMENT-CONTROL.html">Server/Client control protocol</a></li><li><a href="./DEPLOYMENT-COORDINATOR.html">Deployment coordinator state machine</a></li><li><a href="./DURABLE-LOCAL-OPERATIONS.html">Durable local operation lifecycle</a></li><li><a href="./DEPLOYMENT-ARTIFACT-BUNDLE.html">Deployment artifact bundle format</a></li>
</ul>
<h3>Build and site maintenance</h3><ul>
<li><a href="./FEDORA-45-COMPATIBILITY.html">Fedora 45 compatibility baseline</a></li><li><a href="./ACCEPTANCE-TESTS.html">Physical and remote-environment acceptance runbook</a></li><li><a href="./WEBSITE.html">GitHub Pages publishing and maintenance</a></li>
</ul></details>
</main>
