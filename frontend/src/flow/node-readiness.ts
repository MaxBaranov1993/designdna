import { pullInput } from "./dataflow";
import type { FlowEdge, FlowNode } from "./types";

/** Explain missing inputs without treating a connected but empty output as data. */
export function nodeInputHint(nodes: FlowNode[], edges: FlowEdge[], node: FlowNode | null): string {
  if (!node) return "Node unavailable";
  if (node.type === "generator") {
    const prompt = String(pullInput(nodes, edges, node, "prompt") || node.data.ownPrompt || "").trim();
    return prompt ? "" : "Connect a Prompt node or enter a prompt in Task and direction.";
  }
  if (node.type === "mix" || node.type === "page") {
    const ready = node.data.inputs.filter(name => Boolean(pullInput(nodes, edges, node, name))).length;
    const required = node.type === "mix" ? 2 : 1;
    return ready >= required ? "" : node.type === "mix"
      ? "Connect at least two IR inputs with completed results."
      : "Connect at least one IR input with a completed result.";
  }
  return "";
}
