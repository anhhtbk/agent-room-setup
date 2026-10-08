# Spec orchestration (Lead)

Run the Markdown tickets of one spec folder with up to three writable Peers on
the current branch of a shared working tree. Lead invokes this when Human
gives a folder containing `spec.md` and `issues/NN-<slug>.md`, or asks Lead to
run such tickets.

In this mode Lead writes only ticket header lines, the `## Comments` section
(through `scripts/ticket-field.py`), and files under `<SPEC>/.room/`. Every
code change goes to a **fresh** Peer. Lead reads, diagnoses, reviews, and
verifies; it does not implement.

References: [`reference.md`](reference.md) (ticket fields, Peers through Paseo,
shared tree, review, audit, servers, cleanup) ·
[`questions.md`](questions.md) (Peer signals, Human questions, pausing) ·
[`brief-template.md`](brief-template.md).

`S=~/.config/codex-room/skills/spec-orchestration/scripts` · `RUN_ROOT=<SPEC>/.room`

## 1. Prepare

1. Read the shared and project `WORKSPACE_PROTOCOL.md`, project `AGENTS.md`
   or `CLAUDE.md`, `<SPEC>/spec.md`, and every ticket.
2. If Human has forbidden commits for this work, stop and ask: this workflow
   reviews Peer commits by SHA. Commits stay local; nobody pushes, merges, or
   deploys without Human.
3. Choose the Peer provider: the `*-peer` provider of Lead's own runtime
   (`claude-lead` → `claude-peer`) unless Human or a ticket `Runtime:` line
   names another. Never use a bare `claude`, `omp`, or `codex` provider.
4. Choose the lock command: `lockf -k -t <seconds> <file>` when `lockf`
   exists (macOS/BSD), otherwise `flock -w <seconds> <file>`.
5. Create `$RUN_ROOT/{locks,runs}` and record the baseline of every repository
   named in any ticket `Repo:` line:
   `python3 $S/tree-audit.py snapshot $RUN_ROOT/baseline.json <repo>...`.
   Files dirty at this point belong to Human: no ticket may touch or commit
   them. A ticket that needs one is a question for Human.

Done when `baseline.json` lists every ticket repository.

## 2. Choose tickets

1. `python3 $S/frontier.py <SPEC>`.
2. For each `NEEDS-TOUCHES` ticket, estimate Touches (reference.md › Ticket
   fields), write it with `ticket-field.py <ticket> Touches "<...>"`, and rerun.
3. Pick `FRONTIER` tickets in ascending order until **three** Peers are
   writing. After each pick, rerun with `--running <NN,...>` to catch
   `CONFLICT`. Overlapping Touches never run in parallel.

Done when every free slot holds a `FRONTIER` ticket, or none is left.

## 3. Dispatch a ticket (attempt K, starting at 1)

1. `NAME=p<NN>-a<K>`, `RUN=$RUN_ROOT/runs/<NN>-a<K>`. Copy
   `brief-template.md` to `$RUN/brief.md` and fill every `{{...}}`:
   - `{{SEAMS}}`: the test seams **you** fix from the ticket criteria:
     public interface and behavior to test.
   - `{{BASE}}`: HEAD per repository from `baseline.json` at dispatch time.
   - `{{PREV_REVIEW}}`: the previous attempt's `review.md`, when fixing.

   Done when no `{{` remains.
2. Set `Status: in-progress` and `Assignee: <NAME>`.
3. Create the Peer with the Paseo agent tool in the same workspace: chosen
   `*-peer` provider and model, full-access mode, title `<NAME>`, background
   with finish notification, prompt:
   `Read and follow the brief at $RUN/brief.md. End by writing $RUN/report.md.`
   Record the agent id in `$RUN/peer.txt`.

Done when the Peer is running. Continue with other slots; wait for events.

## 4. When a Peer finishes, errors, or needs attention

Read `$RUN/report.md` and the Peer's last message.

| Situation | Action |
| --- | --- |
| `SIGNAL: CANDIDATE` | step 5 |
| `REOPEN_REQUEST`, `DEPENDENCY_REQUEST`, `BLOCKED` | [`questions.md`](questions.md) |
| permission request | approve when inside the brief; otherwise questions.md |
| no report, Peer idle | read its activity; if it stopped midway, prompt "Continue per the brief and end with the report." |
| provider error | read activity; retry once with a new NAME, then treat as `BLOCKED` |

## 5. Review by SHA

1. Set `Status: review`. Run every check in reference.md › Review by SHA,
   including the tree audit, and write `$RUN/review.md`.
2. Accepted: `Commits: ...`, `Status: done`, `--tick` met criteria, and a
   `--comment` with the summary plus the report's "For Comments" section.
3. Rejected: `Status: needs-fix`, `--comment` with the defects; the ticket
   returns to step 2 as attempt K+1 whose brief points at this `review.md`.

Done when every reported SHA passed review and the ticket is `done` or
`needs-fix`. This is the explicit ACCEPT/REJECT of the room protocol.

## 6. Close the Peer

Archive the Peer agent, then do reference.md › Cleanup.

## 7. Loop and finish

Return to step 2 whenever a slot frees or a ticket unblocks. While a product
question is open, follow **Pausing** in questions.md.

Finish when every ticket is `done`, `needs-info`, `ready-for-human`, or
`wontfix` and no Peer is running. Then:
- `python3 $S/tree-audit.py check $RUN_ROOT/baseline.json --quiet-point`;
- run each repository's full test suite once;
- report to Human: finished tickets with `Commits:`, waiting tickets with
  their questions, audit and full-suite results, and that nothing was pushed.
