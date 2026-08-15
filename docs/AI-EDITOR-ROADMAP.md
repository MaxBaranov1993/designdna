# AI-first Editor Roadmap

## Product position

Figma now combines an in-canvas agent, Make/Sites, reusable AI skills and MCP;
pen.dev combines an IDE canvas, MCP, code/design sync, CLI and script nodes. The
winning position for DesignDNA is therefore not “more manual tools”. It is a
source-aware composition system in which a designer states intent, AI prepares
an explainable reversible patch, and deterministic checks protect the result.

Current reference material:

- https://www.figma.com/ai/
- https://www.figma.com/blog/the-figma-agent-is-here/
- https://docs.pen.dev/getting-started/ai-integration
- https://docs.pen.dev/core-concepts/code-on-canvas

## Ten differentiators, in implementation order

| # | Capability | One simple user action | Complexity delegated to AI | Success metric |
|---|---|---|---|---|
| 1 | Source-aware Harmonizer | “Сделать цельно” | Detect visual seams, choose dominant tokens, preserve intentional exceptions, propose a reversible facet patch | 80% fewer cross-source inconsistencies after one action |
| 2 | Goal-based responsive autopilot | “Адаптировать все экраны” | Infer breakpoint constraints, reflow, wrapping, crop and type scale; show only risky decisions | No horizontal overflow across three target widths |
| 3 | Continuous Quality Copilot | “Проверить” | Run grid, overflow, contrast, hierarchy and schema checks; prepare safe fixes | Export-blocking defects reach zero before handoff |
| 4 | Intent locks | “Не меняй бренд/контент/геометрию” | Translate plain language into granular facet locks observed by every agent action | Zero edits outside locked facets |
| 5 | Semantic selection | “Все CTA из источника B” | Resolve visual/semantic/source queries into a live selection set | Multi-layer edits without Layers-panel hunting |
| 6 | State and edge-case generator | “Добавь loading/error/empty” | Generate realistic component states without duplicating frames manually | State coverage visible per component |
| 7 | Content realism agent | “Сделай данные правдоподобными” | Replace placeholder lengths, names, prices and images while respecting layout budgets | Fewer late layout breaks from real content |
| 8 | Bidirectional component contract | “Связать с кодом” | Map IR nodes to real components/props/tokens and surface drift as a patch | Design/code drift detected before PR merge |
| 9 | Taste memory, not prompt memory | “Как в прошлых одобренных экранах” | Learn project-level accepted decisions, exclusions and density preferences | Higher first-pass acceptance over time |
| 10 | Outcome branches | “Дай три стратегии” | Produce isolated semantic branches, score them against the brief and merge selected facets | Compare meaningful alternatives without copy-paste |

## Delivery sequence

1. **Foundation — shipped:** Design IR 2.0 composition contract, Parser v2
   provenance/layout evidence, multi-source Edit and Source Lens.
2. **Safe AI editing — shipped:** Smart Axis preview/apply/undo through a
   `SemanticChangeSet`.
3. **Quality Copilot — shipped foundation:** editor-native deterministic gate;
   visual/accessibility judges and export blocking follow.
4. **Harmonizer — shipped foundation:** source-aware Style DNA preview/apply/undo
   for colors, typography, radius and shadows; facet controls follow.
5. **Responsive Autopilot — shipped foundation:** tablet/mobile constraints,
   safe reflow, overflow protection and Quality Gate preview.
6. **Intent Locks — shipped foundation:** document/selection locks for brand,
   content, geometry, appearance, responsive behavior and source linkage.
7. **Semantic Selection — shipped foundation:** natural-language selection by
   element role, content and source provenance.
8. **Intent layer:** generated component states.
9. **Production loop:** code contracts, taste memory and outcome branches.

## Non-negotiable interaction rule

AI never makes a broad design mutation invisibly. Every operation has intent,
scope, provenance, preview, validation, inverse operations and one-click Undo.
