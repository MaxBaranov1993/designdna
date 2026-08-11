# Product

## One sentence

DesignAI Web is **Figma + controlled AI**: a node-based web-design tool where AI generates and transforms editable Design IR, while the user controls style, layout, structure, parameters, memory and quality.

## Positioning

The product should feel like:

- **Figma** for visual editing;
- **ComfyUI** for graph workflows and reusable AI pipelines;
- **Houdini/Substance Designer** for procedural parameters, locks, variations and assets;
- **Pen.dev / Claude Design / Figma Make**, but with stronger control, repeatability and project style memory.

The product should not feel like:

- “one prompt → random landing page”;
- a chat-only design toy;
- a black box that overwrites layout and structure;
- a Figma clone with AI sprinkled on top.

## Primary users

### Vibe coder / AI-builder

They want to ship interfaces fast. They accept AI, but they hate when a model silently changes structure, spacing or content.

They use DesignAI Web to:

- generate a first website/component;
- import references;
- create variants;
- lock structure/layout;
- export or hand off a controlled design artifact later.

### Freelance web designer

They want speed without losing taste.

They use DesignAI Web to:

- collect inspiration from sites/screenshots;
- extract style DNA;
- generate related blocks in the same style;
- manually edit the final result;
- create multiple client-ready variants quickly.

## Secondary users

### Design studio

Needs repeatability, project memory, reusable assets, client variants, review history and quality gates.

### General designer

Needs a softer entry than ComfyUI/Houdini, but still wants control over AI output.

## Core promise

Controlled AI means:

1. **Everything is editable** — AI output becomes Design IR, not a flat image.
2. **Everything is composable** — results can be wired into other nodes.
3. **Everything can be locked** — structure, layout, colors, fonts, spacing, content and images can be protected.
4. **Everything can be inspected** — tokens, blocks, style, score and diff should be visible.
5. **Everything can be learned per project** — chosen blocks and manual edits become project style memory.

## Killer workflows

### 1. Reference to editable block

```text
URL / screenshot
  → Source Import
  → select block
  → Edit in DNA Editor
  → save as project asset
```

Outcome: “I found a block I like and now it is editable and reusable.”

### 2. Header to footer in same style

```text
Header IR + Style DNA + prompt "make footer"
  → Derive
  → Quality Pass
  → Edit
```

Outcome: “AI understands my project style and creates a related component.”

### 3. Keep layout, change style

```text
IR + Style DNA + Reskin mask
  → Reskin
  → merge-back restores locked structure/layout
```

Outcome: “The model can redesign the look without destroying the composition.”

### 4. Mix variants like Substance

```text
Variant A + Variant B + weights
  → Mix
  → inspect tokens/tree
  → Quality Pass
```

Outcome: “I can blend decisions instead of regenerating from scratch.”

### 5. Project style memory

```text
selected imports + accepted generations + manual edits
  → Project DNA
  → every future generation follows it
```

Outcome: “This project gets smarter as I work.”

## Why it can beat competitors

### Against Figma

Figma is an excellent canvas, but not a procedural AI graph. DesignAI Web can win where a designer wants AI workflows, reusable transformations, style memory and generated variants.

### Against Pen.dev

Pen.dev is strong for AI design/editing, but the user still needs deeper graph control, explicit locks, reusable node pipelines and project-specific memory.

### Against Claude Design / chat design tools

Chat tools are fast but drift. DesignAI Web should win through deterministic layers: schema, constraints, merge-back, quality gates, diff and reusable graph assets.

### Against ComfyUI

ComfyUI is powerful but intimidating. DesignAI Web should keep graph power while making the common web-design paths obvious and visually polished.

## Product principles

- AI is a collaborator, not the owner.
- The graph is the source of process truth.
- Design IR is the source of design truth.
- Manual edits are first-class training signals for the current project.
- Locks and constraints are not advanced settings; they are the product.
- Quality is visible before the user spends more tokens.
