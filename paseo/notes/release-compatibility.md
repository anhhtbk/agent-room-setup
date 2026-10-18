# Required release behavior

Room setup relies on official Paseo support for derived providers (`extends`,
including `claude` and `omp`), per-provider commands, replacement model catalogs
and default thinking settings, Codex app-server controls, provider-specific
`paseoTools.enabled`, and local CLI/daemon/Desktop builds. Stable releases since
v0.9.2 include these configuration interfaces; v0.11.4 was checked on 2026-10-19.

There is no version pin to update: each install/update selects the latest
published stable release (never main or a prerelease). The Pi MCP delivery and
tool-policy interfaces Room depends on are re-checked against every build by
`home/.config/codex-room/tools/paseo-pi-contract.mjs`; a release that fails it is
installed with a warning and Pi Supervisor/Lead sessions refuse to start. When
that warning appears, update the Room adapter and the probe for the new interface.
