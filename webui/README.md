# Feclora Cockpit application

The web application is a dedicated Cockpit package built with React and
PatternFly. It is intentionally read-only in this first integration slice:
it exposes status, signed/encrypted image inventory, deployment journal
summaries and storage inventory. It does not provide arbitrary command
execution or destructive storage controls.

Build with `npm install` followed by `npm run build`. The ISO build copies
`dist/` into `/usr/share/cockpit/feclora`. Cockpit remains disabled by
default; starting its socket and enabling remote access must be an explicit
operator action.

The UI calls only the fixed `status`, `images`, `journals` and
`inventory` actions through the root-owned `/usr/libexec/feclora/cockpit-api`
wrapper. The Python API rejects all other actions. Cockpit's superuser
authorization boundary is required for inventory access.
