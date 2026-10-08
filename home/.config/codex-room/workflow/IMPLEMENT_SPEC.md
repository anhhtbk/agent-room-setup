# implement-spec in the Room

Lead runs `~/.agents/skills/implement-spec/SKILL.md` step by step. This file
maps the skill's subagents and git steps onto Room roles, Paseo, and the
authority in `WORKSPACE_PROTOCOL.md`. On authority and safety this file and the
protocol win; everything else follows the skill. Any agent loads a named skill
(`tdd`, `code-review`) by reading `~/.agents/skills/<name>/SKILL.md`.

## Names

- `T=~/.config/codex-room/tools`.
- `RUN`: Lead's run directory, outside every repository checkout:
  `<spec folder>/.room` when the spec folder is outside all repositories,
  otherwise `~/.local/state/codex-room/runs/<slug>`. Lead creates it
  (`mkdir -p $RUN`) and owns it, except the per-Peer paths granted below.
- Repositories: every repository the spec or a ticket names (for example a
  ticket's `Repo:` line; `cross-repo` means each repository it touches). For
  each repository `R`: `W_R` = the project's documented worktree directory,
  else `<parent of R>/.worktrees`. Worktrees are `W_R/<R name>-<slug>-integration`
  (`I_R` below) and `W_R/<R name>-<slug>-NN-a<K>` (`X_R` below). `W_R` must
  not be under Paseo's own worktree root (`~/.paseo/worktrees`): archiving a
  workspace there deletes it without a content check.

## Subagents are Peers

| Skill | Room |
| --- | --- |
| exploration subagent | Peer, read-only on repositories; writes notes to `$RUN/notes/` |
| implementer subagent | fresh writable Peer per ticket attempt, in that ticket's worktrees |
| merger subagent | fresh writable Peer in the integration worktree(s); one at a time |
| `code-review` call | Lead runs the skill as its coordinator; its parallel sub-agents are two fresh read-only Peers (Standards, Spec) |
| review-fix implementer | one writable Peer in its own worktrees, then a merger |

Create each Peer with the Paseo agent tool in the adopted workspace of its
first worktree: the `*-peer` provider of Lead's runtime unless Human names
another, background, notify on finish. Peers have no subagents of their own.
At most three writable Peers run at once. Every Peer response closes with a
Lead disposition. Lead writes no ticket code.

## Git layout

Lead creates branches and worktrees; main checkouts stay on their branch,
untouched (no checkout, reset, stash, clean).

1. `mkdir -p $RUN && python3 $T/tree-audit.py snapshot $RUN/baseline.json <every R>`.
   Files dirty there are Human's.
2. Per `R`: `git -C R branch <slug>/integration <base>` (`<base>`: the commit
   Human named, else R's main checkout HEAD), then
   `git -C R worktree add I_R <slug>/integration`. Adopt it with the Paseo
   workspace tool (`isolation: local`, `path: I_R`).
3. Ticket `NN`, attempt `K` (first attempt `K=1`), per touched `R`:
   `git -C R worktree add -b <slug>/NN-a<K> X_R <start SHA>`. Start SHA: the
   integration tip; for a fix attempt, Lead may name the rejected head
   instead. Adopt the first worktree as the Peer's workspace.

## Implementer brief

Pointers to spec, ticket, and notes; per repository the main checkout path,
worktree path, branch, start SHA, and the recorded integration tip. Write
scope: those worktrees, plus `$RUN/procs/NN-a<K>/`,
`$RUN/logs/NN-a<K>/`, and `$RUN/baselines/NN-a<K>-<R name>.json`. The brief
states:

- Start check per worktree: `git status --porcelain --untracked-files=all` is
  empty and `HEAD` is the start SHA. If clean and `HEAD` is an ancestor of the
  start SHA, `git merge --ff-only <start SHA>`. Anything else is a
  `DEPENDENCY_REQUEST`; work is never reset, stashed, or cleaned.
- Build with the `tdd` skill. Run every build/test through
  `mkdir -p $RUN/logs/NN-a<K> && python3 $T/run-procs.py run $RUN/procs/NN-a<K> -- <command> > $RUN/logs/NN-a<K>/<gate>.log 2>&1`;
  stop processes only that way, never by name.
- Project instructions: read `AGENTS.md`/`CLAUDE.md` from the repository's
  main checkout path given in the brief, not only the worktree copy; the main
  checkout may carry instruction updates that are not committed yet.
- Before reporting, per worktree: commit locally, `git merge <integration tip
  of R named in the brief, or a newer recorded tip Lead sends>` (merge, not rebase), rerun the gate, delete your own untracked
  scratch by path (never `git clean`), then as the last actions:

      python3 $T/run-procs.py stop $RUN/procs/NN-a<K>
      python3 $T/worktree-guard.py record $RUN/baselines/NN-a<K>-<R name>.json --repo <R> --worktree <X_R> --root <W_R> --owner <slug> --head <head SHA>

  `record` refuses unless `HEAD` is that SHA and everything outside ignored
  files equals it; fix the cause or report it, never work around it.
- Report per repository: branch, head SHA, start SHA, changed paths, gate
  logs, manifest path, its `digest=`, and the `IGNORED` paths it listed (your
  build outputs); residual risk. Push, PR, and repositories outside the brief
  are out of scope.

## Disposition, merge, review

- Accepting an implementer: per repository, run
  `python3 $T/worktree-guard.py check <manifest> --owner <slug>`; it must
  print `OK` with the reported digest, the manifest's head must equal the
  reported head SHA, and ignored paths must be build outputs. The disposition
  records head SHA and digest; the merger gets exactly that SHA. A rejected
  attempt keeps its branch; the fix is attempt `K+1`.
- Merger brief: per repository the accepted SHA, `I_R`, and the tip Lead
  recorded. Write scope: the `I_R` of those repositories, `$RUN/procs/merge-NN/`
  and `$RUN/logs/merge-NN/`. Before merging, in every `I_R`,
  `git status --porcelain --untracked-files=all` is empty and `HEAD` is the
  recorded tip. It runs `git merge --no-ff --no-commit <SHA>` in each
  repository, resolves conflicts within ticket intent, runs each gate as
  `python3 $T/run-procs.py run $RUN/procs/merge-NN -- <command> > $RUN/logs/merge-NN/<R name>.log 2>&1`,
  and commits in every repository only when every gate passes; it reports
  each merge SHA. Any unresolvable conflict or failing gate: `git merge --abort`
  in every repository of the ticket (its own uncommitted merges only) and
  `BLOCKED`, so the integration branches never diverge.
- Accepting a merger, per repository: `git -C R rev-list --parents -n1 <new tip>`
  prints `<new tip> <recorded tip> <accepted SHA>` (exactly one merge commit
  on the recorded tip), and the gate log passes. Lead records the new tip;
  implementers and mergers start from recorded tips only.
- After all tickets: Lead runs `code-review` as its coordinator with fixed
  point `<base>`, once per repository `R` with changes. Its two sub-agents are
  two read-only Peers per repository (Standards, Spec) working in the adopted
  `I_R`, each given the skill's step-4 prompt. Lead presents their reports as
  the skill's step 5 says (separate axes, no merging or reranking). Per skill
  step 7 every valid finding is fixed; a finding Lead judges invalid is
  recorded with the reason (Lead's technical acceptance under the protocol).
  One review-fix implementer (ticket id `rf`, same naming and baseline rules)
  and a merger follow.
- Ticket closing: a local tracker (Markdown files) is updated by Lead as the
  project's issue-tracker doc says. When the tracker lives inside one of the
  repositories, Lead edits it only after the Finish check below. Changes on a
  remote tracker (Plane, GitHub, GitLab), push, PR, merging into the base
  branch, and deployment happen only when Human asks.
- Finish: every accepted SHA is an ancestor of its integration tip;
  `python3 $T/tree-audit.py check $RUN/baseline.json --quiet-point`; report
  each `<slug>/integration` branch and SHA.

## Cleanup

The writer's handoff baseline ties a worktree to its writer: recorded in the
same session as the last write, `--head` pins the candidate SHA, and only
ignored files can differ from that commit. No writer-recorded baseline, or a
disposition without a verified digest, means the worktree's bytes have no
proven origin: keep it, mark it `cleanup-blocked`, and ask Human. Lead never
records on a writer's behalf.

At skill step 9, per ticket-attempt worktree (accepted or rejected): archive
its adopted workspace (the response must show `removedDirectory: false`), then
`python3 $T/worktree-guard.py remove <manifest> --owner <slug> --digest <digest from the disposition>`.
`REFUSE`, `DIFF`, or `PARTIAL`: keep what is left and ask Human. Branches,
integration worktrees, and their workspaces stay for Human.
