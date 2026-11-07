"""Operator-owned keys in ~/.paseo/config.json.

The repository template owns the rest of the file. Paseo writes plugin
registrations into the same file (`paseo plugin install`, Settings → Plugins),
so installing the template must carry these keys over, and exporting the
installed file must leave them out of the template.

CLI (for the shell scripts):
  paseo_config.py carry <rendered-template> <installed-config> <output>
  paseo_config.py strip <installed-config> <output>
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

OPERATOR_KEYS = ("plugins", "pluginsEnabled")


def _dump(value: dict) -> bytes:
    # Matches the template's own formatting, so an unchanged install stays byte-identical.
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode()


def carry_operator_keys(rendered: bytes, installed: Path) -> bytes:
    """Return the rendered template plus the operator keys of the installed config.

    Paseo rewrites the file in its own key order; when the installed content
    already equals the result, return its bytes so the install is a no-op.
    """
    try:
        raw = installed.read_bytes()
        current = json.loads(raw)
    except (OSError, ValueError):
        return rendered
    if not isinstance(current, dict):
        return rendered
    config = json.loads(rendered)
    config.update({key: current[key] for key in OPERATOR_KEYS if key in current})
    if config == current:
        return raw
    return rendered if config == json.loads(rendered) else _dump(config)


def strip_operator_keys(installed: bytes) -> bytes:
    config = json.loads(installed)
    if not any(key in config for key in OPERATOR_KEYS):
        return installed
    for key in OPERATOR_KEYS:
        config.pop(key, None)
    return _dump(config)


if __name__ == "__main__":
    command, *paths = sys.argv[1:]
    if command == "carry" and len(paths) == 3:
        Path(paths[2]).write_bytes(carry_operator_keys(Path(paths[0]).read_bytes(), Path(paths[1])))
    elif command == "strip" and len(paths) == 2:
        Path(paths[1]).write_bytes(strip_operator_keys(Path(paths[0]).read_bytes()))
    else:
        sys.exit(__doc__)
