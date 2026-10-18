# Paseo stable release

`./install --apply` owns the Paseo checkout and Room configuration transition.
The source of truth is [`paseo/source.toml`](../paseo/source.toml), which selects
the `latest-stable` channel instead of a fixed version:

- Official repository: `https://github.com/getpaseo/paseo.git` (no fork or mirror).
- Release: the newest **published stable** GitHub release, resolved anew on each
  `./install` (plan), `./install --apply`, and `scripts/update-paseo`. Drafts,
  prereleases (`-beta`, `-rc`), and main are never chosen; the highest
  `vMAJOR.MINOR.PATCH` wins, so a later-published backport cannot downgrade.
  On 2026-10-19 that was `v0.11.4` (`dc5b02f7d7c120baea380d76def8b968020d8823`);
  `v0.12.0-beta.3` was ignored.
- Checkout: `~/projects/supervisors/paseo`, local branch `main`, only remote `origin`.

Two installs at different times may install different versions. That is intended:
the repository does not change for a new Paseo release.

## Release selection

`home/.config/codex-room/tools/paseo-release.py resolve` reads the release list
and peels the chosen tag to a commit with `git ls-remote`. The coordinator does
this once per install and passes that exact tag→commit pair to every later step.
The helper re-checks the remote tag before dependency work and compares the
fetched object again, so a tag moved mid-install is refused before publication.
Lightweight and annotated tags are supported. `PASEO_RELEASE_TAG` and
`PASEO_VERIFIED_COMMIT` cannot be supplied to the public installer.

The installed checkout records its release in `git config codex-room.paseoRelease`.
The install plan, apply output, `scripts/verify`, and `scripts/doctor` show the
release and commit, so operators know which Paseo is running. Verification checks
that the checkout is exactly at that recorded tag.

The local branch keeps normal origin/main tracking, but install/update never pull
or select the head of main.

## Pi compatibility with each release

Room Pi roles depend on two Paseo interfaces a later release could change: the Pi
provider delivering the per-session `paseo` MCP server to Room's
`pi-mcp-adapter.mjs` (via `--mcp-config`, or Paseo's own builtin-MCP extension),
and exact-provider `paseoTools` policy. Detection has two layers:

1. After building, install/update runs `tools/paseo-pi-contract.mjs` against that
   build. The release's own config schema and policy functions must give tools to
   Supervisor/Lead only, and its Pi provider must deliver the `paseo` server with
   caller identity and bearer header to a scripted Pi. No Pi install, model, or
   daemon is used. `scripts/verify` and `scripts/doctor` repeat the check.
2. A Paseo-started Pi Supervisor/Lead session that arrives without the `paseo`
   MCP server exits 1 at startup with that reason instead of running without tools.

Operator decision (2026-10-19): an incompatible release **is still installed**.
Install, update, verify, and doctor print a warning and do not fail. Pi Peer,
standalone `agent-room pi`, and the Codex, Claude, and omp runtimes are unaffected.
Pi Supervisor/Lead sessions refuse to start until the Room adapter supports that
release. v0.11.4 passes the contract: its Pi provider, MCP config, and tool-policy
sources keep the v0.9.2 interface, and its new builtin-MCP path is preempted by
Room's adapter signature.

## Installation and migration

A fresh install builds in a sibling staging directory before publication. It runs
`npm ci` and `npm run build:server:clean`, requires both CLI and daemon bundles,
and smoke-tests `paseo --help`. Custom hooks/core.hooksPath and lockfile mutation
are refused. The public coordinator snapshots the checkout and CLI link before
publishing; dependency/build/runtime/final-verification failures restore that snapshot.

Existing official checkouts must be clean, on the expected branch, and use only
the configured official `origin`. The public transaction backs up the checkout
and makes the selected release authoritative even when the current commit is ahead or
divergent. The standalone helper accepts only that release or an ancestor of it,
so a history replacement cannot occur without the coordinator's backup and
rollback boundary. Untracked operator state is preserved.

One explicit exception handles the old Room fork at
`8511089eaeb06cddd049b629562926822020de5c`. The recognized layouts are:

- `origin = git@github.com:hoangnb24/paseo.git`, `upstream = git@github.com:getpaseo/paseo.git`.
- Historical `origin = git@github.com:getpaseo/paseo.git`, `hoangnb24 = git@github.com:hoangnb24/paseo.git`.

`./install --apply` backs up this checkout, changes the working files to the stable
release, sets origin to the official HTTPS source, and removes the fork remote.
No merge or rebase is needed. Unknown fork commits, dirty checkouts, detached HEAD,
and custom remote layouts are refused. The lower-level helper only permits this
migration inside the coordinator's transaction; use the public install command.

The install does not restart a running daemon or replace Desktop. After reviewing
and applying, restart/reload Paseo when existing agent work has finished. New or
reloaded sessions receive the new tool policy; an already-running session keeps
its launch-time tools. Run `./install --verify` against the restarted daemon.

## Provider tools

Keep `daemon.mcp.enabled` and `daemon.mcp.injectIntoAgents` true. Configure
`agents.providers.<id>.paseoTools.enabled` true for Supervisor/Lead and false for
Peer and every other known provider. The old `injectIntoProviders` field is removed.

This gates both MCP and native Paseo tools. Peer receives neither catalog. Model,
thinking, command, and runtime settings are retained. `disabledTools` is available
for partial restrictions, but is unnecessary for this all-or-nothing split.

Upstream defaults to enabled for an unspecified provider and does not inherit this
policy through `extends`. Add an explicit policy whenever adding a provider.
`scripts/verify` and `scripts/export-current` reject missing policies or unexpected
recipients. Voice-only `speak` is separate; voice is disabled in this setup.
This controls tool delivery, not what an agent with shell access can discover.

## Desktop

`scripts/update-paseo` delegates to the installed `paseo-local-update`. It resolves
the latest stable release the same way, fast-forwards to it, runs the Pi contract
check (warning only), builds and signs Desktop, backs up the previous app, and
restarts Paseo. Migrate the fork or a divergent checkout through `./install --apply`
first. See [`paseo/notes/desktop-build.md`](../paseo/notes/desktop-build.md).

The old fork bypassed bearer authentication for loopback clients even when the
daemon had a password. Official Paseo requires that token when a password is set.
The Room template does not configure a password; check Desktop/CLI connectivity
if the daemon receives one through other settings.

## Historical validation of the v0.8.0 pin (2026-09-15)

- GitHub release metadata confirms v0.8.0 is published, not draft/prerelease.
- Real isolated `scripts/install-paseo --preflight`: PASS for v0.8.0, including
  `npm ci`, unchanged lockfile, server/CLI build, required outputs, and CLI help.
  An initial esbuild install failed with macOS spawn error -88; a retry with
  foreground lifecycle output completed successfully without dependency changes.
- v0.8.0 provider schema and policy functions: PASS for all 11 configured providers.
- Source verification, shell/Python syntax, and whitespace checks: PASS.
- Python 3.11 suite: 63/64 PASS. The existing `test_role_defaults_are_aligned`
  fails because the pre-existing working config selects Astra for Lead/Peer while
  their overlays still select Sol. Those user model edits and overlays were retained.
- New release/migration tests cover annotated tags, moved/missing/beta tags,
  tag changes during fetch, main advancing past the release, explicit tool policies,
  both recognized fork remote layouts, unknown-fork refusal, journal-required
  migration, untracked-note preservation, rollback after final verification failure,
  and successful retry with a retained fork backup.
- Docker acceptance was not run: the Docker daemon is unavailable. Desktop build,
  live daemon sessions, and authenticated provider connections were not exercised.

Only Room setup source files were updated. The operator's Paseo checkout, remotes,
installed config, running daemon, and Desktop app were not changed in this review.
