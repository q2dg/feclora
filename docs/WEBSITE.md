# Project website and GitHub Pages

The source for Feclora's minimal landing page and technical documentation is
in this repository under `docs/`. The `Documentation site` workflow builds
that directory with Jekyll and deploys it with GitHub Pages.

## Important URL distinction

The canonical URL requested for the project is
`https://feclora.github.io/`. GitHub Pages reserves that hostname for a
user/organization site owned by the GitHub account or organization named
`feclora`; its source repository must be named exactly
`feclora.github.io`.

The current source repository is `q2dg/feclora`, so it cannot publish the
`feclora.github.io` hostname from its current owner namespace. Its default
project-site URL, once Pages is enabled and the workflow succeeds, is
`https://q2dg.github.io/feclora/`.

To publish at the requested canonical hostname, the repository must be
transferred to (or the site source copied into) the `feclora` account or
organization in a repository named `feclora.github.io`. That ownership
change cannot be inferred or performed safely from this repository alone.

## Publication status

The repository includes a Jekyll landing page, responsive CSS and a GitHub
Actions deployment workflow. The repository's Pages setting and deployment
must be checked in GitHub before the site can be called live. A successful
workflow run publishes the project-site URL; it does not change the owner
namespace to `feclora`.
