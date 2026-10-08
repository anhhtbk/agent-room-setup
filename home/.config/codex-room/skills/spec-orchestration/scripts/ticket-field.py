#!/usr/bin/env python3
"""Set one `Key: value` ticket header line, append a comment, or tick criteria.

Usage:
  ticket-field.py <ticket.md> <Key> <value>       replace the Key line, or insert it after the header block
  ticket-field.py <ticket.md> --comment "<text>"  append "- <timestamp> <text>" under ## Comments
  ticket-field.py <ticket.md> --tick all|"<text>" check [ ] boxes (all, or those containing <text>)
Keeps the `**Key:**` bold form when the ticket already uses it.
"""
import datetime
import pathlib
import re
import sys


def is_header_line(line: str) -> bool:
    return bool(re.match(r"^\*{0,2}[A-Z][\w ]*:\*{0,2}\s", line)) and not line.lstrip("*").startswith("What to build")


def set_field(text: str, key: str, value: str) -> str:
    head, separator, body = text.partition("\n## ")
    pattern = re.compile(rf"^(\*{{0,2}}){re.escape(key)}:(\*{{0,2}})\s*.*$", re.M)
    if pattern.search(head):
        head = pattern.sub(lambda match: f"{match.group(1)}{key}:{match.group(2)} {value}", head, count=1)
    else:
        lines = head.split("\n")
        first = next((index for index, line in enumerate(lines) if is_header_line(line)), None)
        if first is None:
            index = 1  # directly after the H1
        else:
            index = first
            while index + 1 < len(lines) and is_header_line(lines[index + 1]):
                index += 1
        lines.insert(index + 1, f"{key}: {value}")
        head = "\n".join(lines)
    return head + separator + body


def add_comment(text: str, note: str) -> str:
    line = f"- {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')} {note}"
    if re.search(r"^## Comments\s*$", text, re.M):
        return text.rstrip("\n") + "\n" + line + "\n"
    return text.rstrip("\n") + "\n\n## Comments\n\n" + line + "\n"


def tick(text: str, wanted: str) -> str:
    return "\n".join(
        line.replace("- [ ]", "- [x]", 1)
        if line.lstrip().startswith("- [ ]") and (wanted == "all" or wanted in line)
        else line
        for line in text.split("\n")
    )


def main() -> None:
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    path = pathlib.Path(sys.argv[1])
    text = path.read_text(encoding="utf-8")
    if sys.argv[2] == "--comment":
        text = add_comment(text, sys.argv[3])
    elif sys.argv[2] == "--tick":
        text = tick(text, sys.argv[3])
    else:
        text = set_field(text, sys.argv[2], sys.argv[3])
    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
