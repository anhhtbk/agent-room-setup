#!/usr/bin/env python3
"""List the tickets of a spec folder and mark the dispatch frontier.

Usage:  frontier.py <spec folder> [--running NN,NN]

Output columns: NN, Status, Repo, Blocked by, Touches, VERDICT
  FRONTIER        open, every blocker done, Touches disjoint from running tickets
  CONFLICT:NN     frontier, but Touches overlap running ticket NN
  NEEDS-TOUCHES   frontier, but the ticket has no Touches: line yet
  (empty)         not ready
Ticket headers are `Key: value` (or `**Key:** value`) lines before the first `## ` heading.
"""
import pathlib
import re
import sys

DONE = {"done", "resolved"}
OPEN = {"ready-for-agent", "todo", "needs-fix"}
RUNNING = {"in-progress", "review", "needs-info"}


def field(head: str, key: str) -> str:
    match = re.search(rf"^\*{{0,2}}{re.escape(key)}:\*{{0,2}}\s*(.+)$", head, re.M)
    return match.group(1).strip() if match else ""


def parse_touches(raw: str) -> list[tuple[str, str]]:
    """'api:src/X/** · web:src/app/y/**' -> [(repo, literal path prefix)]"""
    result = []
    for part in re.split(r"\s*[·,;]\s*", raw):
        if ":" not in part:
            continue
        repo, pattern = part.split(":", 1)
        prefix = re.split(r"[*?\[]", pattern.strip(), maxsplit=1)[0]
        result.append((repo.strip(), prefix))
    return result


def overlap(left, right) -> bool:
    return any(
        left_repo == right_repo and (left_path.startswith(right_path) or right_path.startswith(left_path))
        for left_repo, left_path in left
        for right_repo, right_path in right
    )


def main() -> None:
    args = sys.argv[1:]
    if not args:
        sys.exit(__doc__)
    root = pathlib.Path(args[0])
    running_arg = args[args.index("--running") + 1] if "--running" in args else ""
    tickets = {}
    for path in sorted((root / "issues").glob("[0-9][0-9]-*.md")):
        head = path.read_text(encoding="utf-8").split("\n## ", 1)[0]
        blocked = field(head, "Blocked by")
        deps = [] if not blocked or blocked.lower().startswith("none") else re.findall(r"\b(\d{2})\b", blocked)
        tickets[path.name[:2]] = {
            "status": field(head, "Status").lower(),
            "repo": field(head, "Repo"),
            "deps": deps,
            "touches": parse_touches(field(head, "Touches")),
            "touches_raw": field(head, "Touches"),
        }
    running = {nn for nn in running_arg.split(",") if nn}
    running |= {nn for nn, ticket in tickets.items() if ticket["status"] in RUNNING}
    for nn, ticket in tickets.items():
        verdict = ""
        if ticket["status"] in OPEN and all(tickets.get(dep, {}).get("status") in DONE for dep in ticket["deps"]):
            clash = [
                other for other in sorted(running)
                if other != nn and overlap(ticket["touches"], tickets.get(other, {}).get("touches", []))
            ]
            if not ticket["touches"]:
                verdict = "NEEDS-TOUCHES"
            elif clash:
                verdict = "CONFLICT:" + ",".join(clash)
            else:
                verdict = "FRONTIER"
        print("\t".join([
            nn, ticket["status"] or "-", ticket["repo"] or "-", ",".join(ticket["deps"]) or "-",
            ticket["touches_raw"] or "-", verdict,
        ]))


if __name__ == "__main__":
    main()
