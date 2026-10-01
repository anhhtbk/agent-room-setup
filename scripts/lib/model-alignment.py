#!/usr/bin/env python3
"""Read-only comparison of explicit Room defaults; not model availability proof."""

import argparse
import json
from pathlib import Path
import sys

try:
    import tomllib
except ImportError:
    raise SystemExit("ERROR: model alignment requires Python 3.11+ with tomllib; set CODEX_ROOM_TOML_PYTHON")


ROLES = ("supervisor", "lead", "peer")


def identifier(value, context):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context}: expected a nonempty string ID")
    return value


def default_entry(entries, context):
    if not isinstance(entries, list):
        raise ValueError(f"{context}: expected an array with exactly one default")
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(f"{context}[{index}]: expected an object")
        identifier(entry.get("id"), f"{context}[{index}].id")
        if "isDefault" in entry and not isinstance(entry["isDefault"], bool):
            raise ValueError(f"{context}[{index}].isDefault: expected a boolean")
    defaults = [entry for entry in entries if entry.get("isDefault") is True]
    if len(defaults) != 1:
        raise ValueError(f"{context}: expected exactly one default, found {len(defaults)}")
    return defaults[0]


def toml_defaults(path, layer):
    try:
        with path.open("rb") as stream:
            config = tomllib.load(stream)
    except (OSError, ValueError) as error:
        # Do not echo arbitrary config content (which may contain credentials).
        raise ValueError(f"cannot read {layer} TOML {path} ({type(error).__name__})") from error
    return tuple(identifier(config.get(key), f"{layer} {path}: {key}")
                 for key in ("model", "model_reasoning_effort"))


def compare(expected, actual, layer):
    mismatches = []
    for key, want, got in zip(("model", "model_reasoning_effort"), expected, actual):
        if want != got:
            mismatches.append(f"{layer} {key}={got!r}; overlay {key}={want!r}")
    if mismatches:
        raise ValueError("; ".join(mismatches))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("providers", type=Path)
    parser.add_argument("overlays", type=Path)
    parser.add_argument("--runtime-root", type=Path)
    args = parser.parse_args()
    try:
        config = json.loads(args.providers.read_text())
        providers = config["agents"]["providers"]
        if not isinstance(providers, dict):
            raise TypeError("providers must be an object")
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"ERROR: cannot read Paseo providers from {args.providers} ({type(error).__name__})", file=sys.stderr)
        return 1

    failures = 0
    for role in ROLES:
        try:
            provider = providers.get(f"codex-{role}")
            if not isinstance(provider, dict):
                raise ValueError("missing or invalid Paseo provider")
            model = default_entry(provider.get("models"), "Paseo models")
            effort = default_entry(model.get("thinkingOptions"), "Paseo default model thinkingOptions")
            expected = toml_defaults(args.overlays / f"{role}.config.toml", "overlay")
            compare(expected, (model["id"], effort["id"]), "Paseo")
            if args.runtime_root is not None:
                actual = toml_defaults(args.runtime_root / role / "config.toml", "runtime")
                compare(expected, actual, "runtime")
        except ValueError as error:
            print(f"ERROR: {role} model alignment: {error}", file=sys.stderr)
            failures += 1
    return int(failures > 0)


if __name__ == "__main__":
    sys.exit(main())
