# Peer signals and questions

Read when a report carries `REOPEN_REQUEST`, `DEPENDENCY_REQUEST`, or
`BLOCKED`, or when a Peer asks for a permission outside its brief.

## Classify

The Peer writes `Kind:`. Lead reclassifies with the first matching rule:

1. **Product:** the answer changes what end users see or real data:
   behavior, states, screen flow, UI text, permissions, business rules,
   production data, migrations. Also product when an interpretation must be
   chosen because the spec is silent, contradictory, or disagrees with a
   mock-up or domain glossary.
2. **Product:** it changes a locked spec decision, the ticket scope, or drops
   a ticket criterion; or it needs a file that Human had dirty at baseline.
3. **Technical:** answerable by quoting the ticket, spec, project docs, or
   existing code. Answer with the path and quoted lines.
4. **Technical:** only about how: code placement, internal names,
   implementation choice, build/test failures, commands, seams, extending
   Touches to infrastructure files, requesting a server.
5. Unsure: **product**.

## Technical: Lead answers

- Extending Touches: rerun `frontier.py --running ...` with the new Touches.
  On conflict, tell the Peer to wait or to end with a signal for later
  redispatch.
- Reply with the Paseo prompt tool: `Answer: ... (source: ...). Continue per
  the brief.` in the background.
- Record question and answer under `## Comments` (`ticket-field.py --comment`).

## Product: ask Human

1. Record in `$RUN_ROOT/questions.md`: ticket, Peer, question, options,
   recommended default, time asked. Set `Status: needs-info`.
2. State the question in your own response so Paseo surfaces it to Human (or
   to Supervisor, who relays it). Do not open a blocking interactive question
   tool; it stalls the whole run.
3. When Human answers: record it in `## Comments` and `questions.md`, send it
   to the Peer, set `Status: in-progress`.

## Pausing

Pausing starts when a product question is sent.

- The asking Peer stays idle until Lead forwards the answer.
- Other running Peers finish their attempt and are reviewed normally;
  interrupting them leaves half-edited files on the shared tree.
- Dispatch only tickets independent of the question: not depending on the
  `needs-info` ticket, Touches disjoint from it, not relying on the spec text
  in question.
- Out of independent work: end the turn with a summary of open questions,
  held tickets, and running Peers. On return, read `questions.md` and resume.
