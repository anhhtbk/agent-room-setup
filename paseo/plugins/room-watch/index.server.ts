import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import path from "node:path";
import { z } from "zod";
import { defineAgentTool, type PluginServerContext } from "@getpaseo/plugin/server";
import type { PaseoApi } from "@getpaseo/client";
import { RoomWatch, isSupervisorProvider, parseState, parseThresholds, type Probe, type Thresholds } from "./server/core";

const STATE_FILE = path.join(homedir(), ".local/state/codex-room/room-watch.json");
const CONFIG_FILE = path.join(homedir(), ".config/codex-room/room-watch.json");
const TICK_MS = 60_000;
const PARENT_LABEL = "paseo.parent-agent-id";

export default function contribute(server: PluginServerContext) {
  let watch: RoomWatch | null = null;
  // The SDK is only handed to hooks and tools; keep the latest for the timer.
  let paseo: PaseoApi | null = null;
  let stopped = false;
  let ticking = false;

  const ready: Promise<RoomWatch> = readFile(STATE_FILE, "utf8")
    .then((text) => new RoomWatch(parseState(JSON.parse(text))))
    .catch(() => new RoomWatch(parseState(null)))
    .then((loaded) => (watch = loaded));

  // Hooks overlap; chain writes so two saves never race on the temp file.
  let saving: Promise<void> = Promise.resolve();
  function save(w: RoomWatch): Promise<void> {
    const text = JSON.stringify(w.state, null, 2);
    saving = saving.catch(() => undefined).then(async () => {
      await mkdir(path.dirname(STATE_FILE), { recursive: true });
      const tmp = `${STATE_FILE}.tmp`;
      await writeFile(tmp, text);
      await rename(tmp, STATE_FILE);
    });
    return saving;
  }

  async function thresholds(): Promise<Thresholds> {
    try {
      return parseThresholds(JSON.parse(await readFile(CONFIG_FILE, "utf8")));
    } catch {
      return parseThresholds(null);
    }
  }

  /** Deliver each due owner's digest while that Supervisor is idle. */
  async function flush(api: PaseoApi, w: RoomWatch, t: Thresholds): Promise<void> {
    const now = Date.now();
    for (const owner of w.owners()) {
      if (!w.due(owner, now, t)) continue;
      const result = await api.agents.ref(owner).refresh();
      const snapshot = result?.agent ?? null;
      if (!snapshot || snapshot.archivedAt) {
        console.log(`room-watch: owner ${owner} gone; dropping its room`);
        w.unwatchOwner(owner);
        continue;
      }
      if (snapshot.status === "running" || snapshot.status === "initializing") continue;
      const message = w.drain(owner);
      if (!message) continue;
      await api.agents.ref(owner).send(message, { activeTurnBehavior: "steer" });
      console.log(`room-watch: woke ${owner}`);
    }
  }

  async function probe(api: PaseoApi, agentId: string): Promise<Probe> {
    try {
      const page = await api.agents.ref(agentId).timeline.refetch({ direction: "tail", limit: 1 });
      return {
        agentId,
        status: page.agent?.status ?? null,
        // A new timeline entry is progress; updates to the same entry (a tool
        // polling a background job) only bump seqEnd/maxSeq.
        seq: page.entries.at(-1)?.seqStart ?? null,
        archived: Boolean(page.agent?.archivedAt),
      };
    } catch (error) {
      console.error(`room-watch: probe ${agentId} failed`, error);
      return { agentId, status: null, seq: null, archived: false };
    }
  }

  async function tick(): Promise<void> {
    if (ticking || stopped || !paseo || !watch) return;
    ticking = true;
    try {
      const api = paseo;
      const t = await thresholds();
      const probes = await Promise.all(watch.probeTargets().map((id) => probe(api, id)));
      watch.tick(probes, Date.now(), t);
      await flush(api, watch, t);
      await save(watch);
    } catch (error) {
      console.error("room-watch: tick failed", error);
    } finally {
      ticking = false;
    }
  }

  const timer = setInterval(() => void tick(), TICK_MS);

  /** Run a hook mutation, persist, and try to deliver right away. */
  async function apply(api: PaseoApi, mutate: (w: RoomWatch) => boolean | void | Promise<boolean | void>): Promise<void> {
    paseo = api;
    const w = await ready;
    const changed = await mutate(w);
    if (changed === false) return;
    await save(w);
    await flush(api, w, await thresholds());
  }

  /** Watch an agent and every existing descendant, found through the parent label. */
  async function adopt(api: PaseoApi, w: RoomWatch, owner: string, agentId: string, root: boolean): Promise<number> {
    const result = await api.agents.ref(agentId).refresh();
    const snapshot = result?.agent;
    if (!snapshot || snapshot.archivedAt || isSupervisorProvider(snapshot.provider)) return 0;
    let count = w.watch(agentId, owner, root, { title: snapshot.title, provider: snapshot.provider }, Date.now()) ? 1 : 0;
    if (snapshot.status === "running") w.onTurnStarted(agentId, Date.now());
    const children = await api.agents.list({ filter: { labels: { [PARENT_LABEL]: agentId } } });
    for (const entry of children.entries) count += await adopt(api, w, owner, entry.agent.id, false);
    return count;
  }

  const watchAdd = defineAgentTool({
    name: "room_watch_add",
    description:
      "Watch an existing Lead (and its descendants) so turn ends, pending permissions, archives, and stalls wake you. Agents you create are watched automatically.",
    input: z.object({ agentId: z.string().min(1).describe("Lead agent ID to watch") }),
    async execute({ agentId }, { agent, paseo: api }) {
      let added = 0;
      await apply(api, async (w) => {
        added = await adopt(api, w, agent.id, agentId, true);
      });
      return { text: `Watching ${added} new agent(s) under ${agentId}.` };
    },
  });

  const watchRemove = defineAgentTool({
    name: "room_watch_remove",
    description: "Stop watching one agent, or your whole room when agentId is omitted.",
    input: z.object({ agentId: z.string().optional().describe("Agent to stop watching; omit to stop all") }),
    async execute({ agentId }, { agent, paseo: api }) {
      await apply(api, (w) => {
        if (agentId) w.unwatch(agentId);
        else w.unwatchOwner(agent.id);
      });
      return { text: agentId ? `Stopped watching ${agentId}.` : "Stopped watching your room." };
    },
  });

  const watchList = defineAgentTool({
    name: "room_watch_list",
    description: "List the agents room-watch is watching for you and their in-flight turns.",
    input: z.object({}),
    async execute(_input, { agent, paseo: api }) {
      paseo = api;
      const w = await ready;
      const now = Date.now();
      const rows = w.agentsOf(agent.id).map(([id, a]) => {
        const turn = a.turnStartedAt === null ? "idle" : `in a turn for ${Math.floor((now - a.turnStartedAt) / 60_000)} min`;
        return `- ${w.label(id)}${a.root ? " [root]" : ""}: ${turn}`;
      });
      return { text: rows.length ? rows.join("\n") : "Nothing watched." };
    },
  });

  server.addHook("agent.open.before", async ({ request }) => {
    if (!isSupervisorProvider(request.provider)) return;
    return { ...request, tools: [...request.tools, watchAdd, watchRemove, watchList] };
  });

  server.addHook("agent.create.after", async ({ agent }, { paseo: api }) => {
    await apply(api, async (w) => {
      if (!agent.parentAgentId) return false;
      let parentIsSupervisor = false;
      if (!w.watched(agent.parentAgentId)) {
        const parent = await api.agents.ref(agent.parentAgentId).refresh();
        parentIsSupervisor = isSupervisorProvider(parent?.agent?.provider ?? "");
      }
      return w.onCreated(agent, parentIsSupervisor, Date.now());
    });
  });

  server.addHook("agent.turn.before", async ({ agent }, { paseo: api }) => {
    await apply(api, (w) => {
      if (!w.watched(agent.id)) return false;
      w.onTurnStarted(agent.id, Date.now());
    });
  });

  server.addHook("agent.turn.after", async ({ agent, outcome }, { paseo: api }) => {
    await apply(api, (w) => {
      // A Supervisor going idle is the moment to deliver its queued digest.
      if (w.owners().includes(agent.id)) return;
      if (!w.watched(agent.id)) return false;
      w.onTurnEnded(agent.id, outcome, Date.now());
    });
  });

  server.addHook("agent.permission.before", async ({ agent, request }, { paseo: api }) => {
    await apply(api, (w) => {
      if (!w.watched(agent.id)) return false;
      w.onPermission(agent.id, `${request.kind}: ${request.title ?? request.name ?? ""}`.trim(), Date.now());
    });
  });

  server.addHook("agent.archive.after", async ({ agent }, { paseo: api }) => {
    await apply(api, (w) => {
      if (w.owners().includes(agent.id)) {
        w.unwatchOwner(agent.id);
        return;
      }
      if (!w.watched(agent.id)) return false;
      w.onArchived(agent.id, Date.now());
    });
  });

  return () => {
    stopped = true;
    clearInterval(timer);
  };
}
