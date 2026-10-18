#!/usr/bin/env node
// Check that a built Paseo checkout still honors the contract Room Pi roles use:
//   1. the Room config parses and its exact-ID paseoTools policy gives tools to
//      Supervisor/Lead only, evaluated by the release's own policy functions;
//   2. the release's Pi provider, shown Room's adapter signature (`mcp:1` from
//      pi-mcp-adapter.mjs), delivers the per-session `paseo` MCP server with
//      caller identity and bearer header to the launched Pi session.
// A scripted stand-in plays Pi, so no Pi install, model, network or daemon is
// needed. Exit 0 prints PI_CONTRACT_OK; exit 1 explains the broken contract.
// Usage: paseo-pi-contract.mjs <paseo-checkout> <paseo-config.json>

import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const [checkout, configPath] = process.argv.slice(2);
if (!checkout || !configPath) {
  console.error("usage: paseo-pi-contract.mjs <paseo-checkout> <paseo-config.json>");
  process.exit(2);
}

const ROLE_PROVIDER = /^(codex|claude|omp|pi)-(supervisor|lead|peer)$/;
const CALLER = "room-contract-probe";
const TOKEN = "room-contract-token";
const BASE_URL = "http://127.0.0.1:9/mcp/agents";
const dist = join(checkout, "packages/server/dist/server/server");

async function load(relative, names) {
  let module;
  try {
    module = await import(pathToFileURL(join(dist, relative)).href);
  } catch (error) {
    throw new Error(`cannot load Paseo module ${relative}: ${error.message}`);
  }
  for (const name of names) {
    if (typeof module[name] === "undefined") throw new Error(`Paseo module ${relative} no longer exports ${name}`);
  }
  return module;
}

function checkPolicy(config, policy, schema) {
  const parsed = schema.PersistedConfigSchema.safeParse(config);
  if (!parsed.success) throw new Error(`Paseo rejects the Room config: ${parsed.error.issues[0]?.message ?? "invalid"}`);
  const providers = parsed.data.agents?.providers ?? {};
  const roles = Object.keys(providers).filter((id) => ROLE_PROVIDER.test(id));
  if (!roles.some((id) => id.startsWith("pi-"))) throw new Error("Room config has no pi-* role providers");
  for (const id of roles) {
    const enabled = policy.isPaseoToolPolicyEnabled(policy.resolvePaseoToolPolicy(id, providers));
    if (enabled !== !id.endsWith("-peer")) {
      throw new Error(`Paseo tool policy gives ${id} ${enabled ? "tools" : "no tools"}`);
    }
  }
}

const FAKE_PI = String.raw`
const { appendFileSync, readFileSync } = require("node:fs");
const argv = process.argv.slice(2);
const read = (flag) => argv.flatMap((arg, index) => (arg === flag ? [readFileSync(argv[index + 1], "utf8")] : []));
appendFileSync(process.env.ROOM_CONTRACT_LOG, JSON.stringify({ argv, mcpConfig: read("--mcp-config")[0] ?? null, extensions: read("--extension") }) + "\n");
const state = { thinkingLevel: "off", isStreaming: false, isCompacting: false, sessionId: "room-contract", messageCount: 0, pendingMessageCount: 0 };
const commands = [
  { name: "mcp:1", source: "extension", sourceInfo: { path: "/room/pi-mcp-adapter.mjs", source: "cli", scope: "temporary", origin: "top-level" } },
  { name: "mcp", source: "extension", sourceInfo: { path: "builtin:mcp", source: "builtin", scope: "temporary", origin: "top-level" } },
];
let buffer = "";
process.stdin.on("data", (chunk) => {
  buffer += chunk;
  let index;
  while ((index = buffer.indexOf("\n")) >= 0) {
    const line = buffer.slice(0, index);
    buffer = buffer.slice(index + 1);
    if (!line.trim()) continue;
    const request = JSON.parse(line);
    if (request.id === undefined) continue;
    const data = request.type === "get_commands" ? { commands } : request.type === "get_state" ? state : {};
    process.stdout.write(JSON.stringify({ type: "response", id: request.id, command: request.type, success: true, data }) + "\n");
  }
});
process.stdin.on("end", () => process.exit(0));
`;

function delivered(launch) {
  if (launch.mcpConfig) {
    const server = JSON.parse(launch.mcpConfig).mcpServers?.paseo;
    return Boolean(server?.url?.includes(`callerAgentId=${CALLER}`) && server.headers?.Authorization === `Bearer ${TOKEN}`);
  }
  // Paseo's own builtin-MCP path registers the server from its session extension.
  return launch.extensions.some((text) => text.includes("registerMcpServer") && text.includes(`callerAgentId=${CALLER}`) && text.includes(TOKEN));
}

async function checkDelivery(modules) {
  const [{ PiRpcAgentClient }, { PiCliRuntime }, { withRuntimePaseoMcpServer }] = modules;
  const work = mkdtempSync(join(tmpdir(), "room-pi-contract-"));
  const log = join(work, "launches.jsonl");
  const fake = join(work, "fake-pi.cjs");
  writeFileSync(fake, FAKE_PI);
  process.env.ROOM_CONTRACT_LOG = log;
  const silent = () => {};
  const logger = { trace: silent, debug: silent, info: silent, warn: silent, error: silent, fatal: silent, child: () => logger };
  let session;
  try {
    const client = new PiRpcAgentClient({ logger, runtime: new PiCliRuntime({ logger, command: [process.execPath, fake], requestTimeoutMs: 15000 }) });
    const config = withRuntimePaseoMcpServer({ config: { provider: "pi-lead", cwd: work }, agentId: CALLER, mcpBaseUrl: BASE_URL, mcpAuthToken: TOKEN });
    session = await client.createSession(config);
    const launches = readFileSync(log, "utf8").trim().split("\n").map((line) => JSON.parse(line));
    if (!launches.some(delivered)) {
      throw new Error("Paseo Pi provider did not deliver the paseo MCP server (caller and bearer) to Room's adapter signature");
    }
    return launches.length;
  } finally {
    await session?.close().catch(() => {});
    rmSync(work, { recursive: true, force: true });
  }
}

try {
  const config = JSON.parse(readFileSync(configPath, "utf8"));
  checkPolicy(
    config,
    await load("agent/paseo-tool-policy.js", ["resolvePaseoToolPolicy", "isPaseoToolPolicyEnabled"]),
    await load("persisted-config.js", ["PersistedConfigSchema"]),
  );
  const launches = await checkDelivery([
    await load("agent/providers/pi/agent.js", ["PiRpcAgentClient"]),
    await load("agent/providers/pi/cli-runtime.js", ["PiCliRuntime"]),
    await load("agent/runtime-mcp-config.js", ["withRuntimePaseoMcpServer"]),
  ]);
  console.log(`PI_CONTRACT_OK policy=exact-id delivery=paseo-mcp launches=${launches}`);
} catch (error) {
  console.error(`PI_CONTRACT_BROKEN ${error.message}`);
  process.exit(1);
}
