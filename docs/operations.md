# Operations

The public lifecycle is `./install`, `./install --apply`, then an explicit
Paseo daemon start followed by `./install --verify`. The other scripts in this
repository are focused maintenance interfaces used after that installation;
they are not alternate fresh-install workflows.

## Change a role

1. Edit `home/.config/codex-room/overlays/<role>.config.toml`.
2. Run `make test` and `./scripts/verify --source`.
3. Run `./install` to inspect the complete read-only plan.
4. Run `./install --apply` to publish the changed source transactionally.
5. Start Paseo when no agent turn is active, then run `./install --verify`.

The three roles have distinct authority. Human keeps product, cost, external
effect, and irreversible-risk decisions. Supervisor observes and routes Human
intent. Lead owns the project's technical decision and acceptance. Lead may
run writable Peers in parallel only with verified, accepted inputs and separate
write scopes. Each moving scope has one owner; shared file or interface changes
are sequenced against agreed contracts. A Peer owns one bounded outcome and returns
an immutable candidate or a concrete premise, dependency, or block signal.

## Run a bounded project handoff

### Supervision and attention

Assign a new Supervisor a named project to begin monitoring. It first reads
the current Lead, decisions, and local contract without sending an onboarding
message to Lead. Private conversations remain private; Lead receives only a
needed project decision or an evidence-based open question about actual drift.
Healthy work does not require periodic Lead reports.

The Supervisor's wake-up is the `room-watch` Paseo plugin
(`paseo/plugins/room-watch`). It watches every agent a Supervisor creates and
their descendants (through `parentAgentId`); `room_watch_add` adopts an
existing Lead. While the Supervisor is idle it receives one `<room-watch>`
message batching:

- Lead/Peer turn ends (completed, failed, canceled), after a 30 s debounce;
- pending permissions or questions, and room stalls, immediately;
- archives of watched agents;
- a checkpoint every 30 min while a Lead stays in one turn;
- a stall when a watched agent is running and no watched agent has added a
  timeline entry for 8 min (once per episode). Updates inside one entry, such
  as a tool waiting on a background job or one long build, do not count, so a
  single long command also reports as a stall.

Supervisors get `room_watch_add`, `room_watch_remove`, and `room_watch_list`.
Only when those tools are missing does the Supervisor fall back to one
ten-minute Paseo heartbeat. Thresholds can be overridden in
`~/.config/codex-room/room-watch.json`
(`stallMinutes`, `checkpointMinutes`, `debounceSeconds`); watch state lives in
`~/.local/state/codex-room/room-watch.json`.

Install or update the plugin from this checkout:

```bash
cd paseo/plugins/room-watch && npm install && npm run typecheck && npm test
paseo plugin install "$PWD"   # first time; later: paseo plugin reload room-watch
```

Limits: the plugin receives the Paseo SDK only through hooks and tools, so
after a plugin reload or daemon restart its timer starts at the first agent
event on the daemon. Queued, undelivered events live in memory and are lost on
reload. `./install --apply` keeps `plugins` and `pluginsEnabled` from the
installed `~/.paseo/config.json` (`scripts/lib/paseo_config.py`); every other
key comes from the template, and `scripts/export-current` leaves those two
keys out of the template.

After syncing an overlay, create a new Supervisor session to test it; existing
sessions can retain earlier instructions and conversation history. Check that
assignment does not message a healthy Lead, that a real
ownership/dependency/acceptance deviation elicits one concise open question
without private attribution, and that a `<room-watch>` wake with nothing
actionable produces a one-line reply. Prompt and runtime checks alone do not
establish this behavioral acceptance.

### Project handoff

Lead first records the observable outcome, dependencies, write scope, relevant
invariants, acceptance evidence, and the condition that would reopen the
decision. The writer then reports the exact candidate, original base, changed
paths, commands run, and residual risk. Lead inspects that candidate and
explicitly accepts or rejects it. Tests and lifecycle state support the
decision but do not replace it.

When independent architecture or candidate judgment can change the decision,
Lead requests a fresh read-only Peer against an exact candidate or deterministic
snapshot. The reviewer returns only evidence relevant to the bounded question;
there is no extra standing role or dependency to install.

After dispatch, wait for finish, error, attention, or decision events. Do not
repeatedly query a seat while its state is unchanged. Preserve existing private
notebooks, runtime/session state, and operator-owned `.codex` bytes.

## Change the Paseo provider catalog

1. Edit `home/.paseo/config.json.template`.
2. Run `make test` and `./scripts/verify --source`.
3. Inspect `./install` and apply with `./install --apply`.
4. Restart Paseo explicitly.
5. Run `./install --verify`.

The installer does not restart the daemon because an active restart can
interrupt running agents. The source contract keeps exactly three room
providers per runtime (`codex-*`, `claude-*`, `omp-*`, `pi-*`) and injects Paseo tools
into Supervisor and Lead only. A live provider inventory still needs an
operator check with a running daemon.

## Update to the latest stable Paseo release

Run `paseo-local-update` only when no important agent turn or Desktop operation
is active. It resolves the newest published stable release from the official
repository, requires normalized remotes/tracking plus a clean tracked/index state,
and permits only a no-op or clean fast-forward to that release's commit; a tag
that moves during the update is refused. Run `./install --apply` first when the
checkout is ahead/divergent or uses the recognized old fork; the public installer
backs it up before switching to the selected release. The updater refuses
detached, dirty, ahead/divergent, custom-topology, custom-hook, and lock-integrity
states; then it runs `npm ci`, builds, checks the Pi contract (warning only),
replaces the app, and restarts the daemon. It never pulls, rebases, resets, or
merges automatically. `scripts/doctor` shows the installed release.
