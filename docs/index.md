---
layout: default
title: Feclora
description: Fedora Live disk imaging, cloning, recovery and network deployment.
---
<link rel="icon" type="image/svg+xml" href="{{ '/assets/feclora-mark.svg' | relative_url }}">
<link rel="stylesheet" href="{{ '/assets/css/site.css' | relative_url }}">
<main class="landing">
<header class="hero">
<a class="brand" href="{{ '/' | relative_url }}" aria-label="Feclora home"><picture><source media="(prefers-color-scheme: dark)" srcset="{{ '/assets/feclora-logo-dark.svg' | relative_url }}"><img src="{{ '/assets/feclora-logo.svg' | relative_url }}" alt="Feclora"></picture></a>
<p class="eyebrow">FEDORA LIVE · DISK IMAGING · DEPLOYMENT</p>
<h1>Capture, restore and clone disks — locally or across a network.</h1>
<p class="lead">Feclora is a Fedora Live appliance with a Cockpit interface for creating manifest-backed disk images, restoring compatible targets and coordinating network deployments.</p>
<div class="hero-actions"><a class="button button-primary" href="./GETTING-STARTED.html">Start with the safe first steps</a><a class="button button-secondary" href="./GUIDES.html">Browse all operator guides</a></div>
</header>
<section class="section" aria-labelledby="workflow-title"><p class="eyebrow">CHOOSE A TASK</p><h2 id="workflow-title">What would you like to do?</h2><div class="feature-grid">
<article class="feature"><img class="feature-visual" src="{{ '/assets/mockups/capture-wizard.svg' | relative_url }}" alt="Illustrative mockup of the capture wizard"><span class="feature-number">01 · CREATE</span><h3>Capture an image</h3><p>Save a whole disk or supported partition in a local or remote repository, with a manifest and SHA-256 integrity metadata.</p><a href="./WHOLE-DISK-CAPTURE.html">Capture a whole disk →</a></article>
<article class="feature"><img class="feature-visual" src="{{ '/assets/mockups/restore-wizard.svg' | relative_url }}" alt="Illustrative mockup of restore destination review"><span class="feature-number">02 · RECOVER</span><h3>Restore an image</h3><p>Verify the image, inspect the destination and explicitly authorize the destructive write.</p><a href="./WHOLE-DISK-RESTORE.html">Restore a whole disk →</a></article>
<article class="feature"><img class="feature-visual" src="{{ '/assets/mockups/network-deployment.svg' | relative_url }}" alt="Illustrative mockup of Server and Client deployment"><span class="feature-number">03 · DEPLOY</span><h3>Clone or deploy</h3><p>Clone locally, deploy to remote Clients, coordinate multicast restore or boot Feclora over PXE.</p><a href="./GUIDES.html">Explore deployment guides →</a></article>
</div></section>
<section class="status" aria-labelledby="status-title"><div><p class="eyebrow">IMPORTANT SCOPE</p><h2 id="status-title">Implemented software is not the same as release acceptance.</h2><p>Automated tests and static validation cover software behavior. They do not prove BIOS/UEFI boot, firmware behavior, destructive writes on physical disks, or interoperability with live storage services and real networks. Advanced multi-device Btrfs imaging and opened-LUKS-mapping workflows remain unsupported or incomplete.</p></div><a class="text-link" href="./FEATURE-MATRIX.html">Check features and compatibility →</a></section>
<section class="section links" aria-labelledby="learn-title"><p class="eyebrow">DOCUMENTATION</p><h2 id="learn-title">Find the right documentation</h2><ul>
<li><a href="./GETTING-STARTED.html">Getting started — first safe steps</a></li>
<li><a href="./GUIDES.html">Operator guides — illustrated procedures</a></li>
<li><a href="./FEATURE-MATRIX.html">Feature and compatibility matrix — what is supported</a></li>
<li><a href="./OPERATIONS.html">Operations — backup, upgrade and rollback</a></li>
<li><a href="./BUILD.html">Build and software validation — maintainer procedure</a></li>
<li><a href="./ROADMAP.html">Roadmap — remaining engineering work</a></li>
<li><a href="./GUIDES.html#engineering-references">Engineering references — implementation contracts</a></li>
</ul></section>
<footer class="landing-footer"><span>Feclora · Fedora Live imaging and deployment</span><a href="https://github.com/q2dg/feclora">Source code ↗</a></footer>
</main>
