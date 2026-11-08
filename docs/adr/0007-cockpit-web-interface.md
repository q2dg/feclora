# ADR 0007: Cockpit as the platform for the web interface

- Status: Accepted for architectural direction; implementation pending
- Date: 2026-11-08

## Context

The initial Live interface uses dialog so that Local rescue remains usable
without a browser or network service. A richer interface is desirable for
storage workflows and especially for remote Server-mode administration.

The Anaconda Web UI demonstrates a Cockpit-based web service and a React /
PatternFly frontend. Feclora should reuse this established platform rather
than embed Anaconda's installer screens or build a new web server, session
layer and component system from scratch.

## Decision

Build Feclora as its own Cockpit application/package using the Cockpit web
service, React and PatternFly. Do not fork Anaconda, depend on Anaconda's
installer-specific Web UI internals, or attempt to extend Anaconda's screens:
third-party add-on support in Anaconda's Web UI is not yet available.

The frontend will call a separately testable Feclora backend. Storage,
imaging, deployment and PXE operations remain in domain modules and must not
depend on Cockpit. The initial backend may remain Python; a narrow privileged
service/API boundary must validate every request and must not expose arbitrary
shell execution.

The interface should provide local rescue, image capture/restore, clone,
Server/PXE administration, connected-client status, deployment progress and
operation logs. Destructive operations require explicit review and typed
confirmation, enforced by the backend as well as the UI.

Keep the dialog/text-console interface as an offline fallback until the
Cockpit application has passed equivalent usability, accessibility and
failure-mode tests. Cockpit services are not started automatically in Client
or Local rescue mode. Remote access must be opt-in, authenticated and bound
to explicitly selected interfaces.

## Consequences

- Reuse Cockpit's service/session infrastructure and PatternFly visual
  components without coupling Feclora to Anaconda.
- The web frontend can be accessed locally and, when explicitly enabled,
  remotely by an administrator.
- Cockpit packaging, authentication, privilege separation, SELinux policy,
  service lifecycle, browser availability and Live-image resource cost need
  implementation and validation.
- The dialog interface remains supported until the web UI reaches feature
  parity and has been tested without network connectivity.

## References

- Anaconda Web UI architecture and Cockpit integration:
  https://fedoramagazine.org/reimagining-the-fedora-linux-installer-anacondas-new-web-ui/
- Anaconda Web UI customization and Cockpit service configuration:
  https://anaconda-installer.readthedocs.io/en/latest/anaconda-webui/docs/customization.html
- Cockpit project: https://cockpit-project.org/
- PatternFly: https://www.patternfly.org/
