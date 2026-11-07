// Pure room-watch state machine: no Paseo or filesystem access, so it can be
// tested with node:test. index.server.ts feeds it hook events and tick probes
// and performs the I/O it asks for.

export interface Thresholds {
  /** Room with a running agent and no timeline progress this long → one stall alert. */
  stallMinutes: number;
  /** A watched root (the Lead) in one turn this long → one checkpoint per interval. */
  checkpointMinutes: number;
  /** Coalesce events this long before waking the Supervisor (permissions skip it). */
  debounceSeconds: number;
}

export const DEFAULT_THRESHOLDS: Thresholds = {
  stallMinutes: 8,
  checkpointMinutes: 30,
  debounceSeconds: 30,
};

export interface WatchedAgent {
  owner: string;
  /** True for an agent the Supervisor created or adopted; false for descendants. */
  root: boolean;
  title: string | null;
  role: string;
  turnStartedAt: number | null;
  lastSeq: number | null;
  lastProgressAt: number;
  lastCheckpointAt: number | null;
}

export interface PersistedState {
  version: 1;
  watched: Record<string, WatchedAgent>;
}

export type WatchEventKind =
  | "turn_completed"
  | "turn_failed"
  | "turn_canceled"
  | "permission"
  | "created"
  | "archived"
  | "stall"
  | "checkpoint";

export interface WatchEvent {
  at: number;
  kind: WatchEventKind;
  agentId: string;
  detail: string;
  /** Agent label frozen at enqueue time, so archived agents keep their title. */
  who: string;
}

export interface Probe {
  agentId: string;
  status: string | null;
  seq: number | null;
  archived: boolean;
}

export function emptyState(): PersistedState {
  return { version: 1, watched: {} };
}

export function roleOf(provider: string): string {
  const match = /-(supervisor|lead|peer)$/.exec(provider);
  return match ? match[1] : provider;
}

export function isSupervisorProvider(provider: string): boolean {
  return roleOf(provider) === "supervisor";
}

export class RoomWatch {
  readonly state: PersistedState;
  private readonly queues = new Map<string, WatchEvent[]>();
  private readonly stallAlerted = new Set<string>();

  constructor(state: PersistedState) {
    this.state = state;
  }

  watched(agentId: string): WatchedAgent | undefined {
    return this.state.watched[agentId];
  }

  owners(): string[] {
    return [...new Set(Object.values(this.state.watched).map((w) => w.owner))];
  }

  agentsOf(owner: string): [string, WatchedAgent][] {
    return Object.entries(this.state.watched).filter(([, w]) => w.owner === owner);
  }

  pending(owner: string): WatchEvent[] {
    return this.queues.get(owner) ?? [];
  }

  /** Returns true when the agent was newly added. */
  watch(
    agentId: string,
    owner: string,
    root: boolean,
    info: { title: string | null; provider: string },
    now: number,
  ): boolean {
    if (agentId === owner || this.state.watched[agentId]) return false;
    this.state.watched[agentId] = {
      owner,
      root,
      title: info.title,
      role: roleOf(info.provider),
      turnStartedAt: null,
      lastSeq: null,
      lastProgressAt: now,
      lastCheckpointAt: null,
    };
    return true;
  }

  unwatchOwner(owner: string): void {
    for (const [id] of this.agentsOf(owner)) delete this.state.watched[id];
    this.queues.delete(owner);
    this.stallAlerted.delete(owner);
  }

  unwatch(agentId: string): void {
    const w = this.state.watched[agentId];
    if (!w) return;
    delete this.state.watched[agentId];
    if (this.agentsOf(w.owner).length === 0) {
      this.queues.delete(w.owner);
      this.stallAlerted.delete(w.owner);
    }
  }

  /**
   * A new agent appeared. A Supervisor is never watched: it owns its own room.
   * An agent created by a Supervisor becomes a root of that Supervisor's room;
   * an agent created by a watched agent inherits the owner.
   */
  onCreated(
    agent: { id: string; parentAgentId: string | null; title: string | null; provider: string },
    parentIsSupervisor: boolean,
    now: number,
  ): boolean {
    const parent = agent.parentAgentId;
    if (!parent || isSupervisorProvider(agent.provider)) return false;
    const parentWatch = parentIsSupervisor ? null : this.state.watched[parent];
    if (!parentIsSupervisor && !parentWatch) return false;
    const added = this.watch(agent.id, parentWatch?.owner ?? parent, parentIsSupervisor, agent, now);
    if (!added) return false;
    // The first turn.before can fire before create.after; assume the initial
    // prompt is running and let the first probe correct it.
    this.onTurnStarted(agent.id, now);
    if (parentWatch) this.enqueue(parentWatch.owner, { at: now, kind: "created", agentId: agent.id, detail: `created by ${this.label(parent)}` });
    return true;
  }

  onTurnStarted(agentId: string, now: number): void {
    const w = this.state.watched[agentId];
    if (!w) return;
    w.turnStartedAt = now;
    w.lastCheckpointAt = now;
    this.progress(w, now);
  }

  onTurnEnded(agentId: string, outcome: { kind: string; error?: { message: string }; reason?: string }, now: number): void {
    const w = this.state.watched[agentId];
    if (!w) return;
    w.turnStartedAt = null;
    this.progress(w, now);
    const kind: WatchEventKind = outcome.kind === "failed" ? "turn_failed" : outcome.kind === "canceled" ? "turn_canceled" : "turn_completed";
    const detail = outcome.kind === "failed" ? `error: ${outcome.error?.message ?? "unknown"}` : outcome.kind === "canceled" ? `reason: ${outcome.reason ?? "unknown"}` : "";
    this.enqueue(w.owner, { at: now, kind, agentId, detail });
  }

  onPermission(agentId: string, summary: string, now: number): void {
    const w = this.state.watched[agentId];
    if (!w) return;
    this.enqueue(w.owner, { at: now, kind: "permission", agentId, detail: summary });
  }

  onArchived(agentId: string, now: number): void {
    const w = this.state.watched[agentId];
    if (!w) return;
    this.enqueue(w.owner, { at: now, kind: "archived", agentId, detail: "" });
    this.unwatch(agentId);
  }

  /** Agents whose turn is in flight; only these need a tick probe. */
  probeTargets(): string[] {
    return Object.entries(this.state.watched)
      .filter(([, w]) => w.turnStartedAt !== null)
      .map(([id]) => id);
  }

  /** Apply probe results, then raise stall and checkpoint events. */
  tick(probes: Probe[], now: number, t: Thresholds): void {
    for (const p of probes) {
      const w = this.state.watched[p.agentId];
      if (!w) continue;
      if (p.archived) {
        this.onArchived(p.agentId, now);
        continue;
      }
      if (p.seq !== null && p.seq !== w.lastSeq) {
        if (w.lastSeq !== null) this.progress(w, now);
        w.lastSeq = p.seq;
      }
      if (p.status !== null && p.status !== "running" && p.status !== "initializing") {
        // A turn ended without a hook (e.g. daemon restart); stop probing it.
        w.turnStartedAt = null;
      }
    }

    for (const owner of this.owners()) {
      const agents = this.agentsOf(owner);
      const running = agents.filter(([, w]) => w.turnStartedAt !== null);
      if (running.length > 0 && !this.stallAlerted.has(owner)) {
        const lastProgress = Math.max(...agents.map(([, w]) => w.lastProgressAt));
        const idleMinutes = (now - lastProgress) / 60_000;
        if (idleMinutes >= t.stallMinutes) {
          this.stallAlerted.add(owner);
          const who = running
            .map(([id, w]) => `${this.label(id)} in a turn for ${minutes(now - (w.turnStartedAt ?? now))} min`)
            .join("; ");
          this.enqueue(owner, { at: now, kind: "stall", agentId: running[0][0], detail: `no timeline progress in this room for ${Math.floor(idleMinutes)} min; running: ${who}` });
        }
      }
      for (const [id, w] of agents) {
        if (!w.root || w.turnStartedAt === null || w.lastCheckpointAt === null) continue;
        if (now - w.lastCheckpointAt >= t.checkpointMinutes * 60_000) {
          w.lastCheckpointAt = now;
          this.enqueue(owner, { at: now, kind: "checkpoint", agentId: id, detail: `in one turn for ${minutes(now - w.turnStartedAt)} min` });
        }
      }
    }
  }

  /** Whether the owner's queue is ready to deliver (owner idleness is checked by the caller). */
  due(owner: string, now: number, t: Thresholds): boolean {
    const queue = this.queues.get(owner);
    if (!queue || queue.length === 0) return false;
    if (queue.some((e) => e.kind === "permission" || e.kind === "stall")) return true;
    return now - queue[0].at >= t.debounceSeconds * 1000;
  }

  /** Remove and render the owner's queue as one wake-up message. */
  drain(owner: string): string | null {
    const queue = this.queues.get(owner);
    if (!queue || queue.length === 0) return null;
    this.queues.delete(owner);
    const lines = queue.map((e) => `- ${new Date(e.at).toISOString().slice(11, 16)}Z ${e.who}: ${describe(e)}`);
    const remaining = this.agentsOf(owner).length;
    return [
      "<room-watch>",
      `Events in your supervised room since the last wake (${remaining} agent(s) still watched):`,
      ...lines,
      "Inspect only what these events touch, reconcile intent and workflow, and contact Lead only for a new actionable deviation. If nothing needs action, reply with one line.",
      "</room-watch>",
    ].join("\n");
  }

  label(agentId: string): string {
    const w = this.state.watched[agentId];
    const title = w?.title ? ` "${w.title}"` : "";
    const role = w ? w.role.charAt(0).toUpperCase() + w.role.slice(1) : "Agent";
    return `${role}${title} (${agentId.slice(0, 8)})`;
  }

  private progress(w: WatchedAgent, now: number): void {
    w.lastProgressAt = now;
    this.stallAlerted.delete(w.owner);
  }

  private enqueue(owner: string, event: Omit<WatchEvent, "who">): void {
    const queue = this.queues.get(owner) ?? [];
    queue.push({ ...event, who: this.label(event.agentId) });
    this.queues.set(owner, queue);
  }
}

function describe(e: WatchEvent): string {
  const base: Record<WatchEventKind, string> = {
    turn_completed: "turn completed",
    turn_failed: "turn FAILED",
    turn_canceled: "turn canceled",
    permission: "waiting on a permission/question",
    created: "new agent",
    archived: "archived (no longer watched)",
    stall: "STALL",
    checkpoint: "checkpoint",
  };
  return e.detail ? `${base[e.kind]} (${e.detail})` : base[e.kind];
}

function minutes(ms: number): number {
  return Math.floor(ms / 60_000);
}

export function parseThresholds(raw: unknown): Thresholds {
  const out = { ...DEFAULT_THRESHOLDS };
  if (raw && typeof raw === "object") {
    for (const key of Object.keys(out) as (keyof Thresholds)[]) {
      const value = (raw as Record<string, unknown>)[key];
      if (typeof value === "number" && Number.isFinite(value) && value > 0) out[key] = value;
    }
  }
  return out;
}

export function parseState(raw: unknown): PersistedState {
  if (raw && typeof raw === "object" && (raw as PersistedState).version === 1 && typeof (raw as PersistedState).watched === "object") {
    return raw as PersistedState;
  }
  return emptyState();
}
