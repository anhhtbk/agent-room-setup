# Pi integration: official Pi 1.3.0 and Paseo 0.9.2

## Scope and decision

Research baseline: repository base `d097d75516993b9ae5d56e859c95c461b2850153`; Paseo `v0.9.2`, commit `c67b7158b441bb09026b38d86ae335cc4b49190a`. Current Pi baseline is **1.3.0**, not omp. Historical Pi 0.84.4 was investigated and smoke-tested before the operator updated the machine. The disappearing Homebrew binary was the operator's update, not a repository defect or a research modification.

Shared workspace protocol was read. The target repository had no `docs/WORKSPACE_PROTOCOL.md`. Research changed only this note; no implementation, global install, real HOME/auth modification, commit, or push. Temporary downloads and empty smoke HOME directories were outside the repository.

**Decision:** use native additive Pi CLI flags: prepend `--append-system-prompt`, followed by the role text, and preserve the host argv verbatim. Do not fold host flags or resolve their files in a custom parser. Do not inject omp `--config`, relocate `PI_CODING_AGENT_DIR`, or disable arbitrary operator extensions. Positional initial prompts remain session launches; maintenance/probe routing must use known Pi commands, including current `mcp`. These are Lead-owned implementation decisions, not changes made by this research.

**REOPEN_REQUEST — Paseo tool delivery:** the pinned adapter accepts only the old `pi-mcp-adapter` discovery signature and emits its `--mcp-config` flag. Pi 1.3.0's built-in MCP extension has a different signature and configuration interface. Stock current Pi plus the pinned adapter therefore does not establish Supervisor/Lead Paseo-tool delivery. Exact-provider opt-out for Peer exists, but prompt instructions and that delivery policy are not a sandbox against operator extensions or shell access. Lead must choose and verify a compatible bridge or change the acceptance boundary explicitly; this research does not implement one.

## Primary-source identity and pins

- Official product: <https://pi.dev/> links the Earendil Pi project. Its live page is not a version pin.
- Current source: [`earendil-works/pi`, v1.3.0](https://github.com/earendil-works/pi/releases/tag/v1.3.0), resolved commit **`71023aec1546d6d677a65669c5665c0927ce0dd0`**. `git rev-parse v1.3.0^{commit}` returned this commit; source was read from its downloaded GitHub archive.
- [npm 1.3.0 metadata](https://registry.npmjs.org/@earendil-works/pi-coding-agent/1.3.0): package **`@earendil-works/pi-coding-agent`**, npm executable `pi -> dist/bundle/cli.js`, Node `>=22.19.0`, repository `earendil-works/pi`, directory `packages/coding-agent`. Dependencies include `@earendil-works/pi-mcp@1.3.0`. This metadata does not contain `gitHead`; do not invent npm provenance from that missing field.
- Current [npm tarball](https://registry.npmjs.org/@earendil-works/pi-coding-agent/-/pi-coding-agent-1.3.0.tgz): registry SHA-1 `a52ed0ef8ba4fd03de221ec52b0996855bf5bf4d` (metadata, not independently downloaded in this investigation).
- [Official release API](https://api.github.com/repos/earendil-works/pi/releases/tags/v1.3.0) supplies [Darwin ARM64 binary archive](https://github.com/earendil-works/pi/releases/download/v1.3.0/pi-darwin-arm64.tar.gz), declared SHA-256 `1f9ae61cdeae04dd68caf1a1e8ab8ec9b292062f6ccb3252e0a9cbe93b5b16f1`. The installed binary was version-smoked, not independently matched against this archive digest.
- Historical [npm 0.84.4 metadata](https://registry.npmjs.org/@earendil-works/pi-coding-agent/0.84.4): same package/bin, `gitHead=b79e4cc834970cca69daebffab7df1da7d1e52c4`. Downloaded [tarball](https://registry.npmjs.org/@earendil-works/pi-coding-agent/-/pi-coding-agent-0.84.4.tgz) SHA-1 independently matched registry value `3a2f04bfc5e463b4cfa36b174a586d11a0bdf9ad`.
- Paseo source checkout was detached at [`c67b7158b441bb09026b38d86ae335cc4b49190a`](https://github.com/getpaseo/paseo/tree/c67b7158b441bb09026b38d86ae335cc4b49190a). Repository `paseo/source.toml` agrees with this requested pin. `paseo/versions.toml` still says `0.7.0-beta.1`; that mismatch was observed, not edited, and is not the research baseline.

## CLI, home, and append semantics

Current source: [CLI parser](https://github.com/earendil-works/pi/blob/71023aec1546d6d677a65669c5665c0927ce0dd0/packages/coding-agent/src/cli/args.ts), [configuration](https://github.com/earendil-works/pi/blob/71023aec1546d6d677a65669c5665c0927ce0dd0/packages/coding-agent/src/config.ts#L584-L630), [resource loader](https://github.com/earendil-works/pi/blob/71023aec1546d6d677a65669c5665c0927ce0dd0/packages/coding-agent/src/core/resource-loader.ts#L657-L676).

- Default agent home is `~/.pi/agent`; `PI_CODING_AGENT_DIR` overrides it. `settings.json`, `auth.json`, `models.json`, and sessions/resources belong to Pi/operator state. Do not silently replace that home to implement roles.
- `--append-system-prompt <value>` is repeatable; parser pushes each value into an array in argv order. Both examined versions do this. There is no last-flag-wins behavior to compensate for.
- Each value independently passes through [`resolvePromptInput`](https://github.com/earendil-works/pi/blob/71023aec1546d6d677a65669c5665c0927ce0dd0/packages/coding-agent/src/core/resource-loader.ts#L167-L182): if the value names an existing filesystem path, read UTF-8 and strip BOM; otherwise use it literally. A read error warns and falls back to the literal string. This is an existence check, not an explicit `@file` convention; an ordinary string matching an existing path is treated as a file.
- Resolved append parts are joined with two newlines by [`AgentSession`](https://github.com/earendil-works/pi/blob/71023aec1546d6d677a65669c5665c0927ce0dd0/packages/coding-agent/src/core/agent-session.ts#L1715-L1725). Prepending the role flag preserves later host file/literal values without flattening them.
- Explicit append flags replace automatic discovery of `APPEND_SYSTEM.md`; this is native Pi behavior. Adding the role flag therefore means that implicit discovery is no longer used. Preserve this limit rather than claiming all implicit operator prompts remain included. Explicit host append flags remain additive.
- `--system-prompt` is separate from the append list. Paseo's generated extension appends to `event.systemPrompt`; it does not replace the role append. Arbitrary later operator extensions can still change the prompt; that is operator trust, not evidence of an adapter overwrite.
- Preserve `--` and all following argv. The parser treats following arguments as positional messages/files, not flags. Use the documented two-argument flag spelling; `--append-system-prompt=value` is not handled by the built-in append branch and instead enters unknown/extension-flag handling.
- `--offline` / `PI_OFFLINE=1` suppress startup network operations; `PI_TELEMETRY=0` disables telemetry. These are not a general network sandbox for extensions, MCP servers, or model requests.
- Pi 1.3.0 `--no-extensions` disables discovery **and built-in extensions**, while explicit `-e` still works. `--no-mcp` disables built-in MCP. Historical 0.84.4's built-in llama extension remained visible under `--no-extensions`; do not infer current behavior from that older smoke.
- Current `--exclude-tools` is a tool-name/pattern denylist covering MCP tools too. There are no built-in subagents; the [current README](https://github.com/earendil-works/pi/blob/71023aec1546d6d677a65669c5665c0927ce0dd0/packages/coding-agent/README.md) explicitly identifies sub-agents as an extension/package choice. Do not invent an omp-style subagent exclusion flag.

## RPC and extension contract

Current [RPC documentation](https://github.com/earendil-works/pi/blob/71023aec1546d6d677a65669c5665c0927ce0dd0/packages/coding-agent/docs/rpc.md) and [extensions documentation](https://github.com/earendil-works/pi/blob/71023aec1546d6d677a65669c5665c0927ce0dd0/packages/coding-agent/docs/extensions.md):

- `pi --mode rpc --no-session` is a long-lived stdin/stdout JSONL subprocess. Commands accept optional string `id`; responses contain `type: response`, `command`, `success`, matching `id`, and optional data/error. Events and extension UI records share stdout; correlate by ID, not arrival order. LF is the framing delimiter.
- `get_state` and `get_commands` inspect state/catalog without invoking a model. `prompt`, compaction, or arbitrary extension commands must not be substituted for these safe probes. Current RPC rejects CLI `@file` prompt arguments; send actual prompts through RPC when a model run is authorized.
- Extensions register tools/commands and can modify prompt/context or intercept tool calls. `before_agent_start` changes are chained; later handlers can modify earlier output. Startup-load proof alone does not prove the final model payload or role obedience.
- Current `pi.registerMcpServer(name, config)` registers session-only servers; builtin MCP connects them. A same-name server in `mcp.json` takes precedence. Default tool exposure and connection timing matter: absence from a direct tool list is not sufficient proof that MCP access is unavailable.
- Paseo's generated extension has **no imports**, so there is no `@mariozechner` versus `@earendil-works` import failure in that bridge. Current [extension loader](https://github.com/earendil-works/pi/blob/71023aec1546d6d677a65669c5665c0927ce0dd0/packages/coding-agent/src/core/extensions/loader.ts#L101-L115) also retains old namespace aliases for Node builds. This does not certify an arbitrary third-party MCP extension's runtime compatibility.

## Pinned Paseo launch and prompt bridge

Sources: [Pi runtime argv](https://github.com/getpaseo/paseo/blob/c67b7158b441bb09026b38d86ae335cc4b49190a/packages/server/src/server/agent/providers/pi/runtime.ts#L80-L155), [CLI runtime](https://github.com/getpaseo/paseo/blob/c67b7158b441bb09026b38d86ae335cc4b49190a/packages/server/src/server/agent/providers/pi/cli-runtime.ts#L28-L79), [generated extension](https://github.com/getpaseo/paseo/blob/c67b7158b441bb09026b38d86ae335cc4b49190a/packages/server/src/server/agent/providers/pi/agent.ts#L602-L740), [create/resume](https://github.com/getpaseo/paseo/blob/c67b7158b441bb09026b38d86ae335cc4b49190a/packages/server/src/server/agent/providers/pi/agent.ts#L2534-L2640).

1. Default command is `PI_COMMAND ?? PI_ACP_PI_COMMAND ?? "pi"`; provider runtime replacement command may replace it. Runtime and session environment are merged, session values taking precedence.
2. Append `--mode rpc` unless command argv already has `--mode`/`--mode=...`; then session extra args, optional `--model`, `--thinking`, `--no-session` or `--session`, optional `--mcp-config`, and repeatable `--extension` paths.
3. `createSession` and `resumeSession` compose configured system prompt with daemon append text and pass it into a temporary `paseo-integration.mjs`.
4. **Paseo does not emit `--append-system-prompt` for these fields.** Its generated `before_agent_start` hook returns `event.systemPrompt + "\n\n" + JSON-stringified-composed-text`. Thus wrapper native append flags and the Paseo hook are distinct additive layers, not competing last-wins flags.
5. The extension always exists, even without prompt text. It captures user entry IDs through `session_start`, message, and turn hooks and emits `ctx.ui.notify()` marker records. It registers internal capture and tree-navigation commands using base64url JSON payloads. Tree navigation explicitly sets `summarize: false`.
6. This extension is **not** native Paseo-tool injection. No `registerTool` or imported host tool catalog is present. Pi capabilities omit `supportsNativePaseoTools`; MCP support is only reported for a session when the MCP config was prepared.

## MCP mismatch and derived-provider boundary

Sources: [detection predicate](https://github.com/getpaseo/paseo/blob/c67b7158b441bb09026b38d86ae335cc4b49190a/packages/server/src/server/agent/providers/pi/agent.ts#L754-L768), [probe and prepare](https://github.com/getpaseo/paseo/blob/c67b7158b441bb09026b38d86ae335cc4b49190a/packages/server/src/server/agent/providers/pi/agent.ts#L2742-L2771), [temporary MCP config](https://github.com/getpaseo/paseo/blob/c67b7158b441bb09026b38d86ae335cc4b49190a/packages/server/src/server/agent/providers/pi/agent.ts#L516-L599).

- For configured MCP servers, Paseo starts a probe Pi process and calls `get_commands`. It requires `source === "extension"` and command name matching `/^mcp(?::\d+)?$/`. Missing `sourceInfo` is accepted; when present, its JSON must contain `pi-mcp-adapter`.
- Probe failure or missing matching command returns `null`: session launch continues **without** injected MCP config. This is a silent delivery gap, not a failed session.
- On successful detection it reads operator-global agent-dir `mcp.json`, merges configured servers, writes a temporary mode-0600 `mcp.json`, and launches with `--mcp-config <temp-path>`. It preserves other global keys and normalizes legacy `mcp-servers` to `mcpServers`; it does not overwrite the real file. HTTP conversion forwards headers and adds `auth: false`, `oauth: false` for the old adapter contract.
- Pi 1.3.0 has [builtin MCP](https://github.com/earendil-works/pi/blob/71023aec1546d6d677a65669c5665c0927ce0dd0/packages/coding-agent/src/extensions/index.ts#L7-L14). Real RPC returns command `mcp`, `source: extension`, `sourceInfo: {path: "builtin:mcp", source: "builtin", scope: "temporary", origin: "top-level"}`. This **fails the pinned Paseo predicate**.
- Current [builtin config loader](https://github.com/earendil-works/pi/blob/71023aec1546d6d677a65669c5665c0927ce0dd0/packages/coding-agent/src/extensions/mcp/config.ts#L141-L155) reads agent-dir and trusted project `.pi/mcp.json`. It does not consume the old `--mcp-config` path. Current [MCP registration API](https://github.com/earendil-works/pi/blob/71023aec1546d6d677a65669c5665c0927ce0dd0/packages/coding-agent/docs/extensions.md#L195-L206) is another possible interface, but implementing it is Lead's scope. Merely loosening detection is not a complete fix.
- Historical 0.84.4 [README](https://github.com/earendil-works/pi/blob/b79e4cc834970cca69daebffab7df1da7d1e52c4/packages/coding-agent/README.md#L499-L503) says no builtin MCP. That fact must not be applied to 1.3.0.

Derived providers are supported through [registry inheritance](https://github.com/getpaseo/paseo/blob/c67b7158b441bb09026b38d86ae335cc4b49190a/packages/server/src/server/agent/provider-registry.ts#L826-L863): `extends: pi` uses Pi's factory and merged runtime settings. Tool policy is separate: [exact-ID lookup](https://github.com/getpaseo/paseo/blob/c67b7158b441bb09026b38d86ae335cc4b49190a/packages/server/src/server/agent/paseo-tool-policy.ts#L7-L28) reads only `providerSettings[providerId].paseoTools`; missing policy defaults enabled. It does not inherit the parent's policy.

[AgentManager](https://github.com/getpaseo/paseo/blob/c67b7158b441bb09026b38d86ae335cc4b49190a/packages/server/src/server/agent/agent-manager.ts#L5121-L5211) gates injected Paseo MCP by policy for the stored exact provider ID and only supplies native catalogs when the client advertises support. Therefore each `pi-supervisor`, `pi-lead`, `pi-peer` policy must be explicit. A false Peer policy prevents this manager's automatic delivery; it does not erase operator MCP configuration, prohibit custom extensions, or prevent a bash-capable process from launching other tools.

## Exercised verification and reproduction

Environment: macOS Darwin ARM64; historical npm bundle executed with Node `v26.12.0`; current installed executable `/Users/hoanganh/.local/bin/pi` was reported by Lead as resolving to `/Users/hoanganh/.pi/agent/bin/pi` and independently returned `1.3.0` in this research. No model prompt was sent.

Smoke isolation: create an empty temporary HOME/cwd; launch with an environment allowlist containing only `HOME`, executable search `PATH`, `TERM=dumb`, `PI_OFFLINE=1`, `PI_TELEMETRY=0`. Do not copy API-key/provider/auth variables or point to the real agent home. Explicit executable paths avoid PATH selecting a different installation. Downloads used network; the Pi smoke commands did not request a model or MCP server connection. No packet-level network trace was captured; offline flags are not an OS network-deny guarantee.

Reproduction argv, replacing executable and temporary directories explicitly:

```text
pi --version
pi --offline --mode rpc --no-session --no-extensions --no-skills --no-prompt-templates --no-themes --no-approve
```

Send only these JSONL records; keep stdin open until responses arrive, then terminate the process:

```json
{"id":"state","type":"get_state"}
{"id":"commands","type":"get_commands"}
```

Actual observations:

| Surface | Result |
| --- | --- |
| Historical npm 0.84.4 bundle `--version` and `--help` | Exit 0; version `0.84.4`; no stderr |
| Historical 0.84.4 RPC with discovery disabled | Both commands success; `messageCount=0`, `pendingMessageCount=0`, `isStreaming=false`, no stderr; commands contained only inline `llama` |
| Current installed 1.3.0 `--version` | Exit 0; `1.3.0`; no stderr |
| Current 1.3.0 RPC with `--no-extensions` | Both commands success; `messageCount=0`, `pendingMessageCount=0`, `isStreaming=false`; empty command list; no stderr |
| Current 1.3.0 same isolated RPC without `--no-extensions` | `get_commands` success; builtin `llama` and `mcp` with builtin sourceInfo; no stderr |

The last run had an empty temporary agent home, ignored project configuration, and no configured MCP servers. It exercised actual builtin discovery without connecting any server. It provides the concrete `sourceInfo` rejected by Paseo's source predicate, not an end-to-end Paseo tool-delivery test.

Lead separately reported real 1.3.0 wrapper RPC smoke for supervisor/lead/peer: zero messages, correct role plus host append in `ctx.getSystemPrompt`, read/bash/edit/write tools, and preserved custom agent-dir/settings. That is **Lead-reported evidence**, not independently repeated or expanded here. Lead owns the generated Paseo-extension smoke and implementation acceptance.

Limits: no model turn, streaming/retry/compaction validation, real authenticated MCP tool execution, full Paseo session lifecycle, save/reopen or UI proof. The generated bridge was source-inspected, not executed by this Peer. No current third-party `pi-mcp-adapter` package was installed or certified. A temporary Git worktree checkout failed with an IO error; research recovered by downloading the exact-commit source tarball, without altering the target repository.

This note records the original research snapshot, whose REOPEN_REQUEST was
subsequently resolved by the Room compatibility implementation and execution
proof in the core acceptance record linked below. The original discovery
checks alone were not treated as tool-delivery acceptance.

## Room compatibility implementation

The room now supplies `home/.config/codex-room/pi-mcp-adapter.mjs`; it is
not the third-party npm package of the same name. `agent-room pi <role>`
loads it for sessions after checking Pi >=1.3.0. Probes and maintenance
subcommands bypass role/extension loading.

The extension implements the pinned host's `--mcp-config` flag and registers
session servers using native `registerMcpServer`. Its diagnostic command is
`mcp:1`: registering exact `mcp` would replace the builtin before command
collision resolution. See Pi's
[exact-key builtin replacement](https://github.com/earendil-works/pi/blob/71023aec1546d6d677a65669c5665c0927ce0dd0/packages/coding-agent/src/core/resource-loader.ts#L115-L150).
The builtin remains responsible for transport and execution.

Only legacy `auth:false`/`oauth:false` sentinels are removed. The injected
`paseo` endpoint receives direct exposure; operator servers retain their
settings and native precedence. A native configuration shadowing injected
Paseo, disabled/replaced builtin, or malformed session configuration terminates
the process with a fixed diagnostic and exit 1, rather than an extension error
that Pi could swallow. No endpoint, bearer token or input JSON is printed.
Setup and the bridge do not write operator MCP configuration; Pi itself may
write runtime logs.

Implementation and acceptance evidence after the original research snapshot
are maintained in [the core acceptance record](../../docs/acceptance/core4.md).
The original no-model discovery research above is not, by itself, proof of
tool delivery, execution or resume.

## Paseo latest-stable channel (2026-10-19)

The v0.9.2 source links above remain the research baseline. Paseo is no longer
pinned; setup installs the newest stable release. At v0.11.4
(`dc5b02f7d7c120baea380d76def8b968020d8823`) the Room-relevant interface is
unchanged from v0.9.2: `paseo-tool-policy.ts` and `runtime-mcp-config.ts` are
byte-identical, `buildPiLaunch` still appends `--mcp-config`/`--extension`, and
the adapter predicate (`mcp(:\d+)?` from an extension whose `sourceInfo`
contains `pi-mcp-adapter`) is checked before the new builtin-MCP path, so Room's
`mcp:1` keeps the `--mcp-config` delivery with `auth:false`/`oauth:false`.

Because a later release can change this, `tools/paseo-pi-contract.mjs` checks
each build with that release's own modules, and the adapter stops a
Paseo-started Supervisor/Lead session that has no `paseo` MCP server. Paseo's
session extension is recognized by its `paseo-integration.mjs` file name, which
is loaded into agent sessions but not into the capability probe.

## Known limitation: third-party `pi-mcp-adapter` (2026-10-19)

The operator's `~/.pi/agent` has the third-party `pi-mcp-adapter` npm package.
It registers `--mcp-config` and `/mcp` too, so Pi refuses Room's adapter flag and
skips builtin MCP; every `pi-*` role exits at startup on this machine. Human
deferred it: Pi is unused for now, `~/.pi` stays unchanged, and neither the package
nor Room's adapter is changed. Before using Pi again, decide whether to remove
that package or make Room's adapter coexist with it.
