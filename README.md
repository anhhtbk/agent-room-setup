# Codex Room Setup

Reproducible configuration for a three-role room (Supervisor, Lead, Peer)
running through an official Paseo stable release. Each role is offered on four
runtimes: Codex, Claude Code, oh-my-pi (omp), and [Pi (pi.dev)](https://pi.dev).

```text
Paseo provider codex-<role>
  -> codex-room <role>
  -> codex-room-sync
  -> isolated ~/.codex-runtime/<role>
  -> Codex app-server

Paseo provider claude-<role> | omp-<role> | pi-<role>
  -> agent-room <claude|omp|pi> <role>
  -> operator's own runtime, plus role instructions and policy
```

This repository deliberately does **not** own `~/.codex`, `~/.claude`, `~/.omp`, or `~/.pi`. Each operator installs and authenticates each runtime independently. The Codex sync reads the operator's existing `~/.codex/config.toml` as its base and shares their auth, skills, plugins, and global `AGENTS.md` by symlink. Hooks are shared only when `hooks.json` exists. Claude Code, omp, and Pi keep the operator's home and login; `agent-room` adds the role per process (see [runtime roles](#claude-code-omp-and-pi-roles)).

## What gets installed

The `home/` directory mirrors `$HOME`:

| Repository source | Local destination |
| --- | --- |
| `home/.config/codex-room/` | `~/.config/codex-room/` |
| `home/.local/bin/codex-room*`, `home/.local/bin/agent-room` | `~/.local/bin/` |
| `home/.paseo/config.json.template` | `~/.paseo/config.json` |

The public installer creates this checkout-aware symlink:

```text
~/.local/bin/paseo
  -> ~/projects/supervisors/paseo/packages/cli/bin/paseo
```

`@@HOME@@` placeholders are rendered during installation. Runtime databases, sessions, logs, auth files, keypairs, tokens, worktrees, and backups are never installed from or exported into Git.

## Install

Prerequisites:

- macOS or another Unix-like environment with Bash, Python 3.11 or newer,
  Git, Node 22, npm, and jq.
- Optional: Codex CLI installed and authenticated, with an existing
  `~/.codex/config.toml`, `auth.json`, `AGENTS.md`, `skills/`, and `plugins/`.
  Without the CLI or any required shared resource, setup skips Codex runtime
  generation and verification, preserving any existing runtime unchanged.
  `hooks.json` remains optional.
- `~/.local/bin` on `PATH`.
- Optional: Claude Code (`claude`) and/or oh-my-pi (`omp`, 16.3.9 or newer)
  installed and logged in. Their `claude-*`/`omp-*` providers stay unavailable
  in Paseo until the runtime is on the daemon's PATH.
- Optional: Pi from pi.dev (`pi` >=1.3.0; current smoke baseline 1.3.0).
  The npm package is `@earendil-works/pi-coding-agent` and requires Node
  >=22.19. Pi is distinct from omp. Use an existing installation or the
  [official installation instructions](https://pi.dev).
  Setup never installs/authenticates Pi or requires it to be present.

```bash
git clone https://github.com/hoangnb24/codex-room-setup.git codex-room-setup
cd codex-room-setup

./install                         # read-only plan and prerequisite check
./install --apply                 # transactional Paseo/config/runtime install
./install --verify                # installed checks plus live provider inventory
```

The root command preflights the pinned Paseo checkout, installs dependencies,
builds the Paseo server/CLI bundles, renders managed HOME files, stages the
three Codex role runtimes when prerequisites are available, and publishes the transition with rollback on a
dependency, build, generation, or final verification failure. It does not
install or authenticate Codex, touch `~/.codex`, start a daemon, or build
Paseo Desktop. Start and reach the local provider daemon explicitly before
live verification:

```bash
paseo daemon start
paseo daemon status
./install --verify
```

`./install --verify` is read-only and fails when the live Paseo provider
inventory cannot be reached. Use `scripts/verify` for an installed-only
diagnostic while the daemon is stopped. Repeating `./install --apply` is the
upgrade path: when Codex prerequisites are available it regenerates the three
managed runtimes, preserves operator Codex files and existing runtime/session
data, and retires only recognized, unchanged legacy artifacts.

Codex is not required to install the room or use Claude/omp/Pi. All twelve role provider
definitions and their launchers remain installed; a definition alone does not
make its runtime usable. To enable Codex later, install/authenticate it, provide
the shared resources above, and rerun `./install --apply`. An explicit
`CODEX_ROOM_MODEL_CATALOG` can supply the catalog offline without the CLI;
launching Codex still requires its executable. Invalid available Codex inputs
(for example a malformed catalog or dangling shared link) still fail closed.

## Disposable container acceptance test

With Docker available, one command exercises the public installer twice against
a fresh, fake operator home:

```bash
make test-container
```

The test uses a digest-pinned Node 22 base with Debian's Python 3.11, mounts
this checkout read-only, and supplies `tests/fixtures/model-catalog.json` so it
does not need Codex API authentication. It downloads the pinned Paseo source
and npm dependencies (excluding untested Electron/Playwright GUI binaries),
but never mounts or copies the host's `~/.codex`, auth,
sessions, plugins, or other operator data. A successful run prints the exact
Codex role inventory, Paseo MCP recipients, runtime tree, and
`CONTAINER_ACCEPTANCE_OK`.

This Linux container checks installer topology, legacy-role rejection,
repeatability, preservation, and real Paseo daemon startup with a provider RPC.
Authenticated Codex sessions, Paseo Desktop/GUI behavior, and macOS
signing/TCC/application restart remain operator checks.

Each install resolves the newest published **stable** Paseo release from the
official repository (currently v0.11.4) and holds that tag→commit for the whole
install; drafts, prereleases, and main are never installed, and the repository
needs no change for a new release. The plan, apply, verify, and doctor output show
the installed release. See [release selection, Pi compatibility, and fork
migration](docs/paseo-release.md). The public installer
preflights Paseo in a disposable location before changing live state. Paseo uses
`npm ci` and refuses custom Git hooks because its `prepare` lifecycle
installs lefthook. The public transaction makes the selected release authoritative for
a clean checkout on the configured branch and official origin, including when
the checkout is ahead or divergent; the standalone helper remains
fast-forward-only. The recognized old Room fork is migrated once inside the
backed-up install transaction.

If a new stable release breaks the Pi MCP delivery or tool-policy contract, it is
still installed with a warning; Pi Supervisor/Lead sessions then refuse to start
with that reason, while Pi Peer and the Codex, Claude, and omp roles keep working.

The installer backs up every replaced managed file and the Paseo checkout under
`~/.codex-room-backups/core3-<UTC timestamp>-<pid>-<nanoseconds>/` with
owner-only permissions. The coordinator owns the CLI-link backup as part of
the same transaction; the delegated Paseo helper does not create a second
backup. Customized obsolete files are preserved with a warning; only
recognized, unchanged legacy artifacts are retired after backup.

If `Ctrl-C` or `SIGTERM` arrives during apply, the installer settles its
owned helper process group and rolls back the published state. A power loss or
`SIGKILL` can interrupt before rollback and remains an operating-system
durability limit; inspect the restricted transaction backup before retrying.

It never writes to `~/.codex`.

## Paseo Desktop

After the stable checkout exists at `~/projects/supervisors/paseo`:

```bash
paseo daemon start
paseo daemon status
paseo-local-update
```

That command validates provenance and hook/lock safety, fast-forwards to the
latest stable release, runs `npm ci`, builds and ad-hoc signs the local Desktop app,
backs up the prior `/Applications/Paseo.app`, installs the new build, and
restarts Paseo.

## Roles

| Role | Codex overlay model | Reasoning | Paseo MCP injection (all runtimes) |
| --- | --- | --- | --- |
| Supervisor | `gpt-6.1-sol` | medium | yes |
| Lead | `gpt-6-astra` | medium | yes |
| Peer | `gpt-6.1-sol` | medium | no |
Human retains product, cost, external-effect, and irreversible-risk decisions.
Supervisor routes Human intent and bounded recovery. Lead owns technical
framing, dependency order, verification, and explicit candidate acceptance.
Peer owns one bounded outcome and returns an immutable candidate or a concrete
block signal. Lead may request a fresh read-only Peer review when independent
judgment can change a technical decision. All Codex role overlays currently
request `danger-full-access` with `approval_policy = "never"`. Read
[docs/architecture.md](docs/architecture.md) before changing these boundaries.

Writable Peers may commit their own files on the branch Lead assigned unless
Human forbids it, and at most three run in parallel with disjoint write scopes.

### Running a spec

Give Lead a spec with tickets. Lead follows the operator's global skill
`~/.agents/skills/implement-spec/SKILL.md` (not copied into this repository)
with the Room mapping in `~/.config/codex-room/workflow/IMPLEMENT_SPEC.md`:
implementer Peers each work in a Lead-created worktree and branch per
repository, merger Peers merge them into a local integration branch per
repository, Lead coordinates `code-review` with two read-only axis Peers per
repository, and
Lead dispositions every response. Push, PRs, merges into
the base branch, and deployment stay Human decisions.

Room tools in `~/.config/codex-room/tools/`: `tree-audit.py` reports branch
switches, resets, stash, pushes, and edits to files Human had dirty in the
main checkout; `worktree-guard.py` removes a worktree only when its content
equals the writer's handoff baseline; `run-procs.py` runs commands in a
run-owned process group and stops only that group; `room-gc.py` reports and
deletes the rebuildable `$RUN/cache`, refusing while a registered process
still uses it (`make doctor` reports run directories under
`~/.local/state/codex-room/runs` and `CODEX_ROOM_RUN_ROOTS`); `room-close.py`
runs once `<slug>/integration` is merged into the working branch and removes
that run's worktrees, `<slug>/*` branches, adopted Paseo workspaces, the Paseo
projects registered for them, and `$RUN`, keeping the main checkout and its
project, and anything dirty or unmerged (`room-close.py scan --repo R` lists
leftover runs in a repository).

## Claude Code, omp, and Pi roles

`claude-supervisor|lead|peer`, `omp-supervisor|lead|peer`, and
`pi-supervisor|lead|peer` extend Paseo's corresponding built-in adapters and launch
`~/.local/bin/agent-room <runtime> <role>`. The launcher reads the same
`developer_instructions` as the Codex role overlay, so role authority has one
source, and then execs the operator's `claude`, `omp`, or `pi`:

| | Claude Code | omp |
| --- | --- | --- |
| Role instructions | `SessionStart` hook merged into `--settings` (re-injected after compaction) | merged into the single `--append-system-prompt` |
| Native subagents | `--disallowedTools Agent,Workflow` | `--config ~/.config/codex-room/omp-room.config.yml` (`task.maxRecursionDepth: 0`) |
| Paseo tools | Supervisor/Lead only (MCP) | Supervisor/Lead only (native host tools) |
| Home and login | operator `~/.claude` | operator `~/.omp` |

Models, thinking, and permission mode come from the Paseo agent settings; the
Codex-only overlay keys do not apply. Paseo lists only the Room model set
(Claude Fable 5.1, Opus 5.5, Sonnet 5.5, GPT 6 Astra, GPT 6.1 Sol, as each
runtime can run them); see [profiles and overlays](docs/profiles-and-overlays.md).
`agent-room claude lead` also works from a
terminal for an interactive role session. See
[docs/architecture.md](docs/architecture.md) for why no per-role home is created.

### Pi (pi.dev)

Pi uses its own adapter and `--mode rpc`, not omp's `rpc-ui` or YAML config.
The launcher adds the role through a separate additive `--append-system-prompt`.
Pi itself handles the host's text/file appends and `--` message boundaries;
the launcher also applies the role to positional initial prompts.
It leaves Pi's default `~/.pi/agent` and an operator-provided
`PI_CODING_AGENT_DIR` unchanged. `PI_BIN` may select an absolute executable
path; otherwise `pi` is resolved from PATH. Set that environment on the Paseo
daemon as well when using a nonstandard binary.
An explicit append follows native Pi semantics: implicit `APPEND_SYSTEM.md`
discovery is skipped. Pass that file explicitly with another
`--append-system-prompt /path/to/APPEND_SYSTEM.md` when needed.

The managed `~/.config/codex-room/pi-mcp-adapter.mjs` bridges the pinned
Paseo adapter's per-session MCP configuration to Pi's native MCP support.
It does not install the third-party `pi-mcp-adapter` package or edit Pi's
configuration. Select a Pi role in Paseo for automatic Supervisor/Lead
orchestration tools; a standalone `agent-room pi lead` adds the role but
does not manufacture a Paseo endpoint or credentials. Peer has no automatic
Paseo tool injection. Builtin MCP must remain enabled and must not be replaced
by an operator extension. Native configuration must not shadow the injected
Paseo server. Native Pi may write its own runtime logs.

```bash
./install                         # Pi absent is informational, not an error
./install --apply
agent-room pi lead --version       # probe passes through
agent-room pi lead                 # interactive role session
agent-room pi peer "Inspect this project"
# In Paseo, select pi-supervisor, pi-lead, or pi-peer.
```

Pi has no built-in subagents or approval sandbox. This launcher does not
disable operator extensions or their custom tools; those remain trusted
operator code, not a security boundary. Delegation follows the shared role
contract. Model/thinking choices come from Pi/Paseo, not Codex's overlay
model. Authentication remains a separate operator step.
See [Pi integration research](paseo/notes/pi-integration.md) for pinned
official sources and adapter details.

## Common operations

```bash
# Lower-level maintenance: regenerate all role runtimes after changing an overlay
./scripts/sync-all

# Validate source only, without requiring installed runtimes
./scripts/verify --source

# Verify installed state and the live Paseo provider inventory
./install --verify

# Optional sanitized runtime summaries for local comparison
./scripts/export-runtime-snapshots

```

The lower-level scripts are maintenance interfaces used by the public
lifecycle and are not alternate fresh-install commands. See
[docs/operations.md](docs/operations.md) for scope-owned parallel work and handoff,
candidate acceptance, and maintenance runbooks. The composed evidence and
single final Human runbook are in
[docs/acceptance/core4.md](docs/acceptance/core4.md).

Official Codex configuration precedence is documented by OpenAI in the [Codex config basics](https://learn.chatgpt.com/docs/config-file/config-basic.md). `codex-room` uses a separate `CODEX_HOME` per role; this is a local orchestration layer, not a replacement for the operator's Codex installation.
