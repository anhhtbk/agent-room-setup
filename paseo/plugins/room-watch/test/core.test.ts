import assert from "node:assert/strict";
import { test } from "node:test";
import { RoomWatch, emptyState, parseThresholds } from "../server/core.ts";

const T = parseThresholds({ stallMinutes: 8, checkpointMinutes: 30, debounceSeconds: 30 });
const MIN = 60_000;

function room(): RoomWatch {
  const w = new RoomWatch(emptyState());
  w.onCreated({ id: "lead", parentAgentId: "sup", title: "Lead A", provider: "omp-lead" }, true, 0);
  w.onCreated({ id: "peer", parentAgentId: "lead", title: "Peer B", provider: "omp-peer" }, false, 0);
  // Both initial prompts have finished before each test starts.
  w.tick([{ agentId: "lead", status: "idle", seq: 5, archived: false }, { agentId: "peer", status: "idle", seq: 9, archived: false }], 0, T);
  w.drain("sup");
  return w;
}

test("agents created by a Supervisor and their descendants share that owner; others are ignored", () => {
  const w = room();
  assert.equal(w.watched("lead")?.owner, "sup");
  assert.equal(w.watched("peer")?.owner, "sup");
  assert.equal(w.watched("lead")?.root, true);
  assert.equal(w.watched("peer")?.root, false);
  assert.equal(w.onCreated({ id: "x", parentAgentId: "human-lead", title: null, provider: "omp-peer" }, false, 0), false);
  assert.equal(w.watched("x"), undefined);
});

test("a Supervisor is never watched, and a Supervisor's own agents form its own room", () => {
  const w = room();
  assert.equal(w.onCreated({ id: "sub", parentAgentId: "sup", title: null, provider: "omp-supervisor" }, true, 0), false);
  assert.equal(w.onCreated({ id: "subpeer", parentAgentId: "sub", title: null, provider: "omp-peer" }, true, 0), true);
  assert.equal(w.watched("subpeer")?.owner, "sub");
});

test("a new agent is probed even when its first turn started before it was watched", () => {
  const w = new RoomWatch(emptyState());
  w.onTurnStarted("lead", 0); // turn.before arrives first and is ignored
  w.onCreated({ id: "lead", parentAgentId: "sup", title: null, provider: "omp-lead" }, true, 0);
  assert.deepEqual(w.probeTargets(), ["lead"]);
  w.tick([{ agentId: "lead", status: "running", seq: 1, archived: false }], MIN, T);
  w.tick([{ agentId: "lead", status: "running", seq: 1, archived: false }], 9 * MIN, T);
  assert.deepEqual(w.pending("sup").map((e) => e.kind), ["stall"]);
});

test("turn ends wait for the debounce; permissions are due at once", () => {
  const w = room();
  w.onTurnEnded("lead", { kind: "completed" }, 0);
  assert.equal(w.due("sup", 29_000, T), false);
  assert.equal(w.due("sup", 30_000, T), true);
  w.drain("sup");
  w.onPermission("peer", "tool: Bash", 0);
  assert.equal(w.due("sup", 0, T), true);
});

test("routine Peer events never wake the Supervisor alone and ride along with the next active one", () => {
  const w = room();
  w.onCreated({ id: "peer2", parentAgentId: "lead", title: "Peer C", provider: "omp-peer" }, false, 0);
  w.onTurnEnded("peer", { kind: "completed" }, 0);
  w.onTurnEnded("peer2", { kind: "canceled", reason: "stop" }, 0);
  w.onArchived("peer2", 0);
  assert.equal(w.due("sup", 60 * MIN, T), false);
  w.onTurnEnded("lead", { kind: "completed" }, 60 * MIN);
  assert.equal(w.due("sup", 60 * MIN + 29_000, T), false);
  assert.equal(w.due("sup", 60 * MIN + 30_000, T), true);
  const message = w.drain("sup") ?? "";
  assert.match(message, /Peer "Peer B" \(peer\): turn completed/);
  assert.match(message, /Peer "Peer C" \(peer2\): archived/);
  assert.match(message, /Lead "Lead A" \(lead\): turn completed/);
});

test("a failed Peer turn and an archived Lead still wake the Supervisor", () => {
  const w = room();
  w.onTurnEnded("peer", { kind: "failed", error: { message: "boom" } }, 0);
  assert.equal(w.due("sup", 30_000, T), true);
  w.drain("sup");
  w.onArchived("lead", 0);
  assert.equal(w.due("sup", 30_000, T), true);
});

test("labels carry the full agent id, usable with get_agent_activity", () => {
  const w = new RoomWatch(emptyState());
  const id = "85ef70b5-9974-47f3-9cd7-67dd579c746e";
  w.onCreated({ id, parentAgentId: "sup", title: "Lead A", provider: "omp-lead" }, true, 0);
  assert.equal(w.label(id), `Lead "Lead A" (${id})`);
});

test("one digest carries every queued event and empties the queue", () => {
  const w = room();
  w.onTurnEnded("peer", { kind: "failed", error: { message: "boom" } }, 0);
  w.onTurnEnded("lead", { kind: "completed" }, 1000);
  const message = w.drain("sup") ?? "";
  assert.match(message, /Peer "Peer B" \(peer\): turn FAILED \(error: boom\)/);
  assert.match(message, /Lead "Lead A" \(lead\): turn completed/);
  assert.equal(w.drain("sup"), null);
});

test("an archived agent keeps its label in the digest and is no longer watched", () => {
  const w = room();
  w.onArchived("peer", 0);
  assert.match(w.drain("sup") ?? "", /Peer "Peer B" \(peer\): archived/);
  assert.equal(w.watched("peer"), undefined);
});

test("stall fires once per episode when no running agent advances, and re-arms after progress", () => {
  const w = room();
  w.onTurnStarted("lead", 0);
  w.onTurnStarted("peer", 0);
  w.tick([{ agentId: "lead", status: "running", seq: 5, archived: false }, { agentId: "peer", status: "running", seq: 9, archived: false }], MIN, T);
  w.tick([{ agentId: "lead", status: "running", seq: 5, archived: false }, { agentId: "peer", status: "running", seq: 9, archived: false }], 7 * MIN, T);
  assert.equal(w.pending("sup").length, 0);
  w.tick([{ agentId: "lead", status: "running", seq: 5, archived: false }, { agentId: "peer", status: "running", seq: 9, archived: false }], 8 * MIN, T);
  assert.deepEqual(w.pending("sup").map((e) => e.kind), ["stall"]);
  assert.equal(w.due("sup", 8 * MIN, T), true);
  w.tick([{ agentId: "lead", status: "running", seq: 5, archived: false }, { agentId: "peer", status: "running", seq: 9, archived: false }], 12 * MIN, T);
  assert.equal(w.pending("sup").length, 1);
  w.drain("sup");
  // Peer advances: the episode ends, and a new silence can alert again.
  w.tick([{ agentId: "lead", status: "running", seq: 5, archived: false }, { agentId: "peer", status: "running", seq: 10, archived: false }], 13 * MIN, T);
  w.tick([{ agentId: "lead", status: "running", seq: 5, archived: false }, { agentId: "peer", status: "running", seq: 10, archived: false }], 21 * MIN, T);
  assert.deepEqual(w.pending("sup").map((e) => e.kind), ["stall"]);
});

test("a Lead waiting while its Peer progresses is not a stall", () => {
  const w = room();
  w.onTurnStarted("lead", 0);
  w.onTurnStarted("peer", 0);
  for (let m = 1; m <= 20; m++) {
    w.tick([{ agentId: "lead", status: "running", seq: 5, archived: false }, { agentId: "peer", status: "running", seq: m, archived: false }], m * MIN, T);
  }
  assert.equal(w.pending("sup").filter((e) => e.kind === "stall").length, 0);
});

test("a long root turn yields a checkpoint per interval; Peers never do", () => {
  const w = room();
  w.onTurnStarted("lead", 0);
  w.onTurnStarted("peer", 0);
  for (let m = 1; m <= 61; m++) {
    w.tick([{ agentId: "lead", status: "running", seq: m, archived: false }, { agentId: "peer", status: "running", seq: m, archived: false }], m * MIN, T);
  }
  const checkpoints = w.pending("sup").filter((e) => e.kind === "checkpoint");
  assert.deepEqual(checkpoints.map((e) => e.agentId), ["lead", "lead"]);
});

test("a probe showing an idle agent stops probing it", () => {
  const w = room();
  w.onTurnStarted("peer", 0);
  assert.deepEqual(w.probeTargets(), ["peer"]);
  w.tick([{ agentId: "peer", status: "idle", seq: 3, archived: false }], MIN, T);
  assert.deepEqual(w.probeTargets(), []);
});

test("invalid threshold overrides fall back to defaults", () => {
  assert.deepEqual(parseThresholds({ stallMinutes: -1, checkpointMinutes: "x", debounceSeconds: 5 }), {
    stallMinutes: 8,
    checkpointMinutes: 30,
    debounceSeconds: 5,
  });
});
