# Paseo stable release

Room setup builds the newest published stable Paseo release, selected by the
`latest-stable` channel in `source.toml`:

```text
origin:   https://github.com/getpaseo/paseo.git
checkout: ~/projects/supervisors/paseo
release:  latest published stable release, resolved on each install/update
recorded: git config codex-room.paseoRelease in the checkout
```

Install/update never selects main, a draft, or a prerelease.
See [the release and migration guide](../docs/paseo-release.md).
