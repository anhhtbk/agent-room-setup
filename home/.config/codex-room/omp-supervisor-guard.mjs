// Loaded by agent-room with `omp --extension` for the Supervisor role only.
// Supervisor does not edit project work: block omp's file-changing tools and
// route the change to a Lead. omp blocks the call when this handler throws.
// Shell and eval are not covered; the role prompt carries that rule.

const REASON =
  "Room Supervisor does not edit project files. Route this change to the project's Lead " +
  "(send it to the Lead agent) instead of making it yourself.";

// Tools whose only effect is changing files. `apply_patch` is `edit`'s wire
// name in that edit mode; `rewind` restores files from a checkpoint.
const FILE_TOOLS = new Set(["edit", "apply_patch", "ast_edit", "rewind"]);

// `write` targets that are coordination or session state, not files. A device
// write (`xd://...`) reaches this handler again under the device's own tool name.
const WRITABLE_SCHEMES = ["xd://", "agent://", "proc://", "local://"];

// lsp actions that change no file; previews stay available.
const LSP_READ_ONLY = new Set([
  "diagnostics", "definition", "type_definition", "implementation", "references",
  "hover", "symbols", "status", "capabilities", "reload",
]);

function lspChangesFiles(input) {
  const action = input?.action;
  if (LSP_READ_ONLY.has(action)) return false;
  if (action === "code_actions") return input.apply === true;
  if (action === "rename" || action === "rename_file") return input.apply !== false;
  return true;
}

export function blockedReason(toolName, input) {
  if (FILE_TOOLS.has(toolName)) return REASON;
  if (toolName === "write") {
    const path = typeof input?.path === "string" ? input.path.trim() : "";
    return WRITABLE_SCHEMES.some((scheme) => path.startsWith(scheme)) ? undefined : REASON;
  }
  if (toolName === "lsp" && lspChangesFiles(input)) return REASON;
  return undefined;
}

export default function ompSupervisorGuard(pi) {
  pi.on("tool_call", async (event) => {
    const reason = blockedReason(event.toolName, event.input);
    return reason ? { block: true, reason } : undefined;
  });
}
