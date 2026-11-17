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
<p class="lead">Feclora is a Fedora Live appliance with a Cockpit interface for creating verified disk images, restoring compatible targets and coordinating network deployments.</p>
<div class="hero-actions"><a class="button button-primary" href="./GETTING-STARTED.html">Start with the step-by-step guides</a><a class="button button-secondary" href="https://github.com/q2dg/feclora">View source on GitHub</a></div>
</header>
<section class="section" aria-labelledby="workflow-title"><p class="eyebrow">CHOOSE A TASK</p><h2 id="workflow-title">What would you like to do?</h2><div class="feature-grid">
<article class="feature"><img class="feature-visual" src="{{ '/assets/mockups/capture-wizard.svg' | relative_url }}" alt="Illustrative capture wizard"><span class="feature-number">01 · CREATE</span><h3>Capture an image</h3><p>Save a whole disk or supported partition to a local or remote repository, with a manifest and SHA-256 integrity metadata.</p><a href="./WHOLE-DISK-CAPTURE.html">Capture a whole disk →</a></article>
<article class="feature"><img class="feature-visual" src="{{ '/assets/mockups/restore-wizard.svg' | relative_url }}" alt="Illustrative restore destination review"><span class="feature-number">02 · RECOVER</span><h3>Restore an image</h3><p>Verify the image, inspect the destination and confirm the destructive operation before writing.</p><a href="./WHOLE-DISK-RESTORE.html">Restore a whole disk →</a></article>
<article class="feature"><img class="feature-visual" src="{{ '/assets/mockups/network-deployment.svg' | relative_url }}" alt="Illustrative Server and Client deployment"><span class="feature-number">03 · DEPLOY</span><h3>Clone or deploy</h3><p>Copy locally, stream to a remote Client, or coordinate multicast restore and PXE boot.</p><a href="./GUIDES.html">Explore deployment guides →</a></article>
</div></section>
<section class="status" aria-labelledby="status-title"><div><p class="eyebrow">READ THE LIMITS</p><h2 id="status-title">Implementation status is not the same as release acceptance.</h2><p>The source contains implemented Cockpit workflows for local imaging, remote repositories, Server/Client deployment, multicast and PXE. Some advanced storage-layer workflows remain partial or unsupported. The self-contained recovery ISO builder and guarded boot-time restore path are implemented; firmware and destructive-media acceptance remain separate. Automated tests do not prove behavior on physical hardware, live storage services or real networks.</p></div><a class="text-link" href="./FEATURE-MATRIX.html">Feature and compatibility matrix →</a></section>
<section class="section links" aria-labelledby="learn-title"><p class="eyebrow">DOCUMENTATION</p><h2 id="learn-title">Learn, operate and maintain</h2><ul>
<li><a href="./GETTING-STARTED.html">Getting started — safe first steps</a></li><li><a href="./GUIDES.html">All step-by-step operator guides</a></li><li><a href="./REMOTE-REPOSITORIES.html">Configure image repositories</a></li><li><a href="./DEPLOYMENT-SETUP.html">Configure Server and Clients</a></li><li><a href="./PXE-UNATTENDED.html">Interactive PXE and unattended restore</a></li><li><a href="./BUILD.html">Build and validate the Live ISO</a></li><li><a href="./FEATURE-MATRIX.html">Feature and compatibility matrix</a></li><li><a href="./GUIDES.html#engineering-references">Engineering and compatibility references</a></li><li><a href="./OPERATIONS.html">Operational lifecycle and maintenance</a></li>
</ul></section><footer class="landing-footer"><span>Feclora · Fedora Live imaging and deployment</span><a href="https://github.com/q2dg/feclora">Source code ↗</a></footer></main>