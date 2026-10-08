# Spec orchestration reference

## Ticket fields

Only Lead writes these lines, through `scripts/ticket-field.py`.

| Line | Value |
| --- | --- |
| `Status:` | `ready-for-agent` → `in-progress` → `review` → `done`; `review` → `needs-fix` → `in-progress` (fresh Peer); stopped: `needs-info`, `ready-for-human`, `wontfix` |
| `Assignee:` | Peer name `p<NN>-a<K>`, K = attempt |
| `Commits:` | `<repo> <sha>, <sha> · <repo> <sha>` after acceptance |
| `Touches:` | `<repo>:<glob> · <repo>:<glob>`, estimated by Lead before dispatch |
| `Runtime:` | optional `claude`, `omp`, or `codex`: Peer runtime for this ticket |

Estimate Touches from "What to build", the checklist, and a search for the
named terms, endpoints, or components, guided by the project's routing notes.
Use the narrowest glob that still suffices. Name shared files (DI/startup,
module registries, routing, shared enums, project or package manifests,
migrations) explicitly so `frontier.py` serializes the tickets that touch them.
Touches must not include files that were dirty in `baseline.json`.

## Peers through Paseo

- Create each Peer with the Paseo agent tool from Lead's session: it lands in
  Lead's workspace (same working tree), runs in the background, and Paseo
  notifies Lead on finish, error, or permission. Do not poll.
- Provider must be a `*-peer` provider so the Peer gets the room role and has
  its native subagents disabled. Check `list_providers`/`list_models` rather
  than guessing a model.
- The report file, not an idle status, proves the Peer finished.
- One Peer per attempt. A fix after review is a fresh Peer with the review.

## Shared tree rules (given to every Peer in the brief)

- `git commit -m ... -- <paths>` commits only those paths even when the index
  holds other staged files. New files need `add -- <file>` first. Pathspecs
  split at file level, so Touches must not overlap.
- Two concurrent index writers fail with `index.lock: File exists`; the git
  lock serializes them. Remove a stale `.git/index.lock` only when no `git`
  process is running.
- Forbidden on the shared tree: stash, checkout/switch, reset, restore,
  clean, rebase, merge, pull, push, cherry-pick, revert, `add -A`/`.`/`-u`,
  `commit -a`, `commit --amend`, and starting servers.

## Tree audit (replaces a blocking hook)

`tree-audit.py check $RUN_ROOT/baseline.json` detects branch switches,
resets, rebases, amends, merges, pulls, stash changes, pushes, and changes to
Human's pre-existing dirty files, for every runtime. Run it in each review and
at the end with `--quiet-point`. Files inside the spec folder (tickets and
`.room/`) are Lead's own and are ignored, so a spec folder may live inside the
repository. Build byproducts not covered by `.gitignore` appear as
UNCOMMITTED; note them in `review.md` rather than deleting them.

It detects after the fact; it does not prevent. A `reset --hard` or `clean`
can destroy another Peer's uncommitted work before the audit sees it. On any
VIOLATION: stop dispatching, identify the responsible Peer from reflog time
and assignments, record it in `review.md`, and ask Human before any repair
that rewrites history or discards files. Violations are cumulative from the
snapshot; after Human resolves one, take a fresh snapshot only at a quiet
point (no Peer running), or running Peers' edits become "Human's" files.

## Review by SHA

Review the SHAs in the report, not `base..HEAD`: the shared branch contains
other Peers' commits.

1. `git -C <repo> show --stat --format='%h %an %s%n%b' <sha>` per SHA: one or
   two line message, project content only.
2. `git -C <repo> show --name-only --format= <sha>` ⊆ Touches, and contains
   no baseline-dirty file.
3. `git -C <repo> show <sha>`: check every ticket checkbox and quoted spec
   section against the diff.
4. `python3 $S/tree-audit.py check $RUN_ROOT/baseline.json`: no VIOLATION;
   UNCOMMITTED lines belong only to Peers still running.
5. Tests: verify the Peer's gate evidence (below); do not rerun the same gate
   on the same code.
6. Write `review.md` with `ACCEPT` or `REJECT: ...`, citing code lines or
   criteria.

## Checking a Peer's gate

The Peer ran its gate inside the build lock before each commit.

1. The report's `## Tests` lists per gate: repo, command, the SHA it guards,
   log path in `$RUN/`, exit code, passed/failed/skipped, excluded tests.
2. The log exists, exits 0, and counts match. Excluded tests are only the
   known-red ones named in the brief.
3. The Peer's last commit per repository is guarded by a gate run after the
   last code change.
4. The tests cover every test file in the SHAs' `--name-only` and the tests of
   every production class changed. Derive this set from the diff yourself.

Rerun, inside the build lock, only when 1–3 are missing or inconsistent (the
Peer's gate), when 4 is missing (only the missing tests), or when a log shows
flakiness (only that class). Note in `review.md` what was checked from logs
and what was rerun and why.

Run full suites only at a quiet point (no Peer running): they are the final
evidence for interleaved changes.

## Servers (only when a ticket needs end-to-end checks)

Peers never start long-running servers; they ask with `DEPENDENCY_REQUEST`.
Lead starts one with a Paseo terminal in the repository, inside
`<lock> $RUN_ROOT/locks/server-<repo>.lock <server command>`, and owns its
restart and shutdown. Server commands, ports, and shared test environments
come from the project's `docs/WORKSPACE_PROTOCOL.md`.

## Cleanup after a Peer

1. Archive the Peer agent.
2. Look for processes the Peer left (dev servers, watchers, test runners) in
   its repositories; stop only those you can attribute to it and that are not
   Lead's server terminals.
3. `tree-audit.py check`: note unexpected files in `review.md`; do not delete
   them.
4. Keep `brief.md`, `report.md`, and `review.md` until the ticket is `done`.
