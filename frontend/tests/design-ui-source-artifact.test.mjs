import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(path, import.meta.url), "utf-8");

test("Source Artifact keeps its typed measured contract", async () => {
  const [types, ports, dataflow] = await Promise.all([
    read("../src/flow/types.ts"),
    read("../src/flow/ports.ts"),
    read("../src/flow/dataflow.ts"),
  ]);
  assert.match(types, /version: "source-artifact\/1\.0"/);
  assert.match(types, /screens\?: SourceArtifactScreen\[\]/);
  assert.match(types, /library\?: SourceArtifactLibrary/);
  assert.match(types, /components: SourceArtifactComponent\[\]/);
  assert.match(ports, /name: "artifact", label: "Source Artifact", kind: "artifact"/);
  assert.match(dataflow, /if \(port === "artifact"\) return n\.data\.sourceArtifact \|\| null/);
});

test("Design System is the single new canvas surface for Source UI", async () => {
  const [node, panel, sourcePanel, catalogPreview, ports, store, serialize, canvas] = await Promise.all([
    read("../src/nodes/DesignSystemNode.svelte"),
    read("../src/editor/DesignSystemPanel.svelte"),
    read("../src/editor/SourceArtifactPanel.svelte"),
    read("../src/editor/ComponentCatalogPreview.svelte"),
    read("../src/flow/ports.ts"),
    read("../src/flow/store.ts"),
    read("../src/flow/serialize.ts"),
    read("../src/FlowCanvas.svelte"),
  ]);

  assert.match(node, /Source detected/);
  assert.match(node, /System accepted/);
  assert.match(node, /<InPorts type="designsystem"/);
  assert.match(panel, /data-ds-tab="source"/);
  assert.match(panel, /<SourceArtifactPanel/);
  for (const label of ["Foundations", "Screens", "Component Library", "exact masters", "needs review"]) {
    assert.match(sourcePanel.toLowerCase(), new RegExp(label.toLowerCase()));
  }
  assert.match(sourcePanel, /screen\.hierarchy/);
  assert.match(sourcePanel, /data-source-component-catalog/);
  assert.match(sourcePanel, /ComponentCatalogPreview/);
  assert.match(sourcePanel, /comp\.variants/);
  assert.match(catalogPreview, /IRRenderer\.renderIR/);
  assert.match(catalogPreview, /normalizedPreview/);
  assert.match(panel, /doc\.reviewComponents/);
  assert.match(panel, /catalogEntries/);

  const contextMenu = ports.slice(ports.indexOf("export const CTX_ITEMS"));
  assert.doesNotMatch(contextMenu, /type: "designui"/);
  // Design System принял на себя роль удалённой ноды Style DNA: вход —
  // Source Artifact, выход — токены системы проводом.
  assert.match(ports, /designsystem: \{[\s\S]*?name: "artifact"[\s\S]*?name: "tokens"/);
  assert.doesNotMatch(ports, /styledna/);
  assert.match(store, /connect\(\{ node: sourceId, port: "artifact" \}, \{ node: dsId, port: "artifact" \}\)/);
  assert.match(store, /cons\.type === "designsystem"/);
  assert.match(store, /sourceUpdate: true/);
  assert.match(serialize, /One-way visual migration/);
  assert.match(serialize, /node\.type === "designui"/);

  // Unpaired saved Design UI nodes remain renderable during the compatibility window.
  assert.match(canvas, /designui: DesignUiNode/);
});

test("Design System catalog exposes guarded Sol semantic organization", async () => {
  const [panel, sourcePanel] = await Promise.all([
    read("../src/editor/DesignSystemPanel.svelte"),
    read("../src/editor/SourceArtifactPanel.svelte"),
  ]);
  assert.match(panel, /data-ds-action="organize"/);
  assert.match(panel, /\/api\/design-system\/organize/);
  assert.match(panel, /gpt-5\.6-sol/);
  for (const effort of ["medium", "high", "max"]) {
    assert.match(panel, new RegExp(`value="${effort}"`));
  }
  assert.match(panel, /catalog\.sections/);
  assert.match(sourcePanel, /catalog\.sections/);
  assert.match(panel, /Exact masters stay locked/);
});
