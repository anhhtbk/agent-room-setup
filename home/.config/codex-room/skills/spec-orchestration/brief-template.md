# Brief for Peer {{NAME}}

Nobody watches this session. Lead is the "user" of every skill you use and
has pre-answered the usual questions (seams, fixed point) below.

## Outcome
- Ticket: {{TICKET}} (read all of it, including `## Comments`)
- Spec: {{SPEC}}, the sections the ticket cites
- Project instructions: {{PROJECT_DOCS}}
- Workflow to follow, if any: {{WORKFLOW}}
- Previous review (fix attempts only): {{PREV_REVIEW}}

## Write scope (Touches)
Edit only: {{TOUCHES}}
Needing another file: stop and end with `SIGNAL: DEPENDENCY_REQUEST`,
`Kind: technical`, naming the file and why.
These files were already changed by Human and are not yours; never edit,
stage, or commit them: {{BASELINE_DIRTY}}

## Test seams (fixed by Lead)
{{SEAMS}}
Test at exactly these seams; treat them as confirmed.

## Shared working tree
Other Peers edit the same checkout on the same branch right now.
- Use absolute paths: `git -C <absolute repo path> ...`.
- Run tests and commit as separate commands. Commit only after the gate
  (test command) exits 0, and the gate must run after your last code change
  before that commit.
- Save each gate's output to `{{RUN}}/gate-<repo>-<n>.log` (plus trx/junit
  when the runner supports it). Lead accepts from these logs.
- Stage and commit **only your files**, inside the repository's git lock:
  - `{{LOCK_GIT}} {{RUN_ROOT}}/locks/git-<repo>.lock git -C <repo> add -- <new files...>`
  - `{{LOCK_GIT}} {{RUN_ROOT}}/locks/git-<repo>.lock git -C <repo> commit -m "<msg>" -- <files...>`
- Build and test inside the repository's build lock:
  `{{LOCK_BUILD}} {{RUN_ROOT}}/locks/build-<repo>.lock <command>`.
- Red tests in files outside your Touches: report them, leave them.
- Every change is a new commit on the current branch. Never stash,
  checkout/switch, reset/restore/clean, rebase/merge, pull/push,
  cherry-pick/revert, `add -A`/`.`/`-u`, `commit -a`, or `commit --amend`.
  Lead audits the tree after you finish.
- Do not start servers. Needing one: `SIGNAL: DEPENDENCY_REQUEST`,
  `Kind: technical`.
- Do not open interactive question tools; end with a signal instead.

## Self-review
Fixed point: {{BASE}}. Review only the commits you made in this attempt (list
their SHAs) and files within your Touches. Other authors' commits on the same
branch are out of scope.

## Commit message
One summary line, at most one body line. Project content only.

## Finish (required)
Write {{RUN}}/report.md:

    SIGNAL: CANDIDATE | REOPEN_REQUEST | DEPENDENCY_REQUEST | BLOCKED
    ## Commits        <repo> <sha> <message>, one per line
    ## Files          <repo> <path in repo>, one per line
    ## Tests          per gate: repo · command · SHA it guards · log in {{RUN}}/ · exit · passed/failed/skipped · excluded tests and why
    ## Criteria       each ticket checkbox → met/not met + evidence
    ## Signal         (non-CANDIDATE) Kind: technical|product · evidence · consequence · options · recommended default
    ## Residual risk  untested scope, failed checks, unknowns
    ## For Comments   what the ticket asks to record under `## Comments`

`CANDIDATE` means your commits are ready for Lead's review. A failed premise
is `REOPEN_REQUEST`, a missing prerequisite (file outside Touches, server,
unanswered question) is `DEPENDENCY_REQUEST`, and no safe in-scope progress is
`BLOCKED`. Then reply with exactly one line: `REPORT: {{RUN}}/report.md`.
{{EXTRA}}
