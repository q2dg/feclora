# Project website and GitHub Pages

The source for Feclora's minimal landing page and technical documentation is
in this repository under `docs/`. The `Documentation site` workflow builds
that directory with Jekyll and deploys it with GitHub Pages.

## Project URL

The selected project URL is
[`https://q2dg.github.io/feclora/`](https://q2dg.github.io/feclora/).
This is the standard GitHub Pages project-site URL for the source repository
`q2dg/feclora`.

The separate hostname `https://feclora.github.io/` would require a user or
organization account named `feclora` and a repository named
`feclora.github.io`; it is not needed for this project-site publication.

## Publication status

The repository includes a Jekyll landing page, responsive CSS and a GitHub
Actions deployment workflow. The workflow uses the GitHub Pages Actions
deployment method and does not require a dedicated publishing branch.

One repository-level setting must be enabled by an owner/administrator:
open **Settings → Pages → Build and deployment → Source** and select
**GitHub Actions**. The workflow deliberately does not try to create the Pages
site using `GITHUB_TOKEN`, because GitHub's `configure-pages` action requires
a separate elevated token for that operation. After selecting GitHub Actions,
pushes to `main` will publish the site automatically. The site is considered
published only after the workflow completes successfully and GitHub Pages
reports the deployment URL; publication can take several minutes.
