import { readFileSync, writeSync } from "node:fs";
import { join } from "node:path";
import { getAgentDir, VERSION } from "@earendil-works/pi-coding-agent";

// Pi catches extension errors and can continue without tools. This protocol must
// instead stop the session: a warning is not successful Paseo tool delivery.
function fail(message) {
  writeSync(2, `agent-room Pi MCP adapter: ${message}\n`);
  process.exit(1);
}

function isRecord(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function readServers(path, optional = false) {
  let text;
  try {
    text = readFileSync(path, "utf8");
  } catch (error) {
    if (optional && error.code === "ENOENT") return {};
    fail("cannot read MCP configuration; check the supplied config file and permissions");
  }
  let document;
  try {
    document = JSON.parse(text);
  } catch {
    // JSON parse errors can include bearer tokens from the input.
    fail("MCP configuration is not valid JSON");
  }
  if (!isRecord(document) || (document.mcpServers !== undefined && !isRecord(document.mcpServers))) {
    fail("MCP configuration must contain an mcpServers object");
  }
  return document.mcpServers ?? {};
}

function namespace(name) {
  return name.replace(/-/g, "_");
}

function isInjectedPaseo(name, config) {
  if (name !== "paseo" || typeof config.url !== "string") return false;
  try {
    const url = new URL(config.url);
    return url.pathname === "/mcp/agents" && url.searchParams.has("callerAgentId");
  } catch {
    return false;
  }
}

export default function piMcpAdapter(pi) {
  const version = /^(\d+)\.(\d+)\.(\d+)(?:$|[-+])/.exec(VERSION ?? "");
  if (!version || Number(version[1]) < 1 || (Number(version[1]) === 1 && Number(version[2]) < 3)
      || typeof pi.registerMcpServer !== "function" || typeof pi.getMcpServers !== "function") {
    fail("Pi 1.3.0 or newer with native MCP registration is required for Room sessions");
  }

  pi.registerFlag("mcp-config", {
    type: "string",
    description: "Session MCP configuration supplied by Paseo (Room adapter)",
  });

  let registered = new Set();
  // Exact /mcp would replace Pi's builtin, which is the actual MCP transport.
  pi.registerCommand("mcp:1", {
    description: "Show Room adapter session MCP registrations (builtin /mcp manages connections)",
    handler: async (_args, ctx) => {
      const tools = pi.getAllTools().filter((tool) =>
        [...registered].some((name) => tool.name.startsWith(`mcp__${namespace(name)}__`)));
      ctx.ui.notify(`Room MCP adapter: ${registered.size} session registrations, ${tools.length} registered tools. Registration is not connection readiness.`, "info");
    },
  });

  pi.on("session_start", (_event, ctx) => {
    const builtin = pi.getCommands().some((command) => command.sourceInfo?.path === "builtin:mcp");
    if (!builtin) {
      fail("native builtin:mcp is disabled or replaced; enable it and remove extensions registering /mcp");
    }
    const path = pi.getFlag("mcp-config");
    if (path === undefined) return; // Paseo capability probe or a standalone Room session.
    if (typeof path !== "string" || !path) fail("--mcp-config requires a file path");

    const servers = readServers(path);
    const entries = Object.entries(servers);
    if (entries.some(([, config]) => !isRecord(config))) fail("MCP server entries must be objects");
    const injected = entries.filter(([name, config]) => isInjectedPaseo(name, config));
    if (injected.length) {
      const nativeFiles = [join(getAgentDir(), "mcp.json")];
      if (ctx.isProjectTrusted()) nativeFiles.push(join(ctx.cwd, ".pi", "mcp.json"));
      for (const nativeFile of nativeFiles) {
        const nativeNames = Object.keys(readServers(nativeFile, true));
        if (injected.some(([name]) => nativeNames.some((native) => namespace(native) === namespace(name)))) {
          fail("native mcp.json shadows the session Paseo server; resolve the conflicting native entry before launching");
        }
      }
    }

    // Read anew on resume/reload/new sessions; never retain another session's URL
    // or token. Native mcp.json precedence remains unchanged for operator servers.
    for (const name of registered) pi.unregisterMcpServer(name);
    registered = new Set();
    for (const [name, original] of entries) {
      const config = { ...original };
      if (config.auth === false) delete config.auth;
      if (config.oauth === false) delete config.oauth;
      if (isInjectedPaseo(name, config)) config.exposure = "direct";
      try {
        pi.registerMcpServer(name, config);
      } catch {
        fail("session MCP server registration failed; check server configuration and extension namespace conflicts");
      }
      registered.add(name);
    }
  });
}
