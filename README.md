# DesignDNA

**A local AI design studio that learns a live website and designs in its language.**

Import any site as pixel-exact, editable layers. Extract a verified UI Kit. Generate new sections that fit the existing page. Reassemble the page. Direct a motion video of it, with a cursor that fills forms and a logo end card. All of this runs on a desktop node graph with GPT or Claude, through the Codex / Claude Code subscriptions you already have.

[![Desktop runtime](https://github.com/MaxBaranov1993/designdna/actions/workflows/desktop.yml/badge.svg?branch=main)](https://github.com/MaxBaranov1993/designdna/actions/workflows/desktop.yml)
![Status: public beta](https://img.shields.io/badge/status-public%20beta-orange)
![Desktop: Windows · macOS · Linux](https://img.shields.io/badge/desktop-Windows%20%C2%B7%20macOS%20%C2%B7%20Linux-555)

![Video director: a cursor fills the contact form, clicks, and the page zooms into the logo end card](docs/media/video-demo.gif)

*The video above was produced end to end in DesignDNA from [slsbmb.com](https://slsbmb.com/) by Claude Opus. The source was imported, a UI Kit was built, a contact form was generated in the site's style and inserted into the page, and the video was directed and rendered.*

> **Русская версия:** [README.ru.md](README.ru.md) · **Beta testers:** start at [Beta testing](#beta-testing).

---

## What makes it different

### 1. Pixel-exact import of a live site
Paste a URL and get the page as **editable absolute layers** in about 30 seconds, much like html.to.design does for Figma. The import:
- loads the page once and pre-scrolls lazy content;
- activates web fonts the browser skipped, so text is measured in the real font;
- splits the page into sections by geometry;
- keeps page-level screenshots as evidence.

Tablet and mobile captures are added on demand. On our fidelity bench the rendered import matches the live page at **0.99** visual similarity on slsbmb.com and rsale.net, and at **0.91** on the animation-heavy glebkudr.com.

### 2. A design system extracted from the site and checked against it
The UI Kit node turns the captured sections into **masters**, the reusable components of the kit. An AI vision reviewer compares each master with the source crop before it is accepted. Published kits are **immutable revisions**. The kit also measures the page's **section shell**: column, rhythm, eyebrow, heading and body styles, surfaces and buttons.

### 3. Generation that fits the existing page
Connect the UI Kit to the Generator, and new sections land in **the site's column, spacing, fonts, colors and surfaces**, not in a generic template. A **Quality Pass** loop judges each result with a vision model and repairs it in rounds.

### 4. The original page, reassembled
The **Page** node rebuilds the source page section by section, at the original positions and over the site's own background. Generated sections can be inserted **between any two blocks**.

### 5. A motion director for product videos
The **Video** node turns a page into a video, directed by your model of choice:
- camera pans and reveals synced to the camera;
- a cursor that types into form fields and clicks;
- page transitions: `zoom`, `slide`, `motion`;
- end cards and blur, clip and focus effects.

Rendering is **deterministic and offline**, with parallel workers, straight to MP4. Every AI edit is a reversible change set.

### 6. GPT and Claude on your subscriptions, no API keys
Every AI node lets you choose between two model families:
- **GPT** (GPT‑5.6 Sol, GPT‑6 Astra) through your **Codex** sign-in;
- **Claude** (Claude Opus) through your **Claude Code** sign-in.

The app runs the CLIs you are already signed in to, in an isolated working directory, with tools disabled and your personal agent settings never loaded. The only API key is optional: Seedance video generation through OpenRouter.

### 7. Local first
Projects live in a local SQLite database. Images are content-addressed files on your disk. Nothing leaves your machine except the model calls you start. External agents can drive the studio through the bundled **MCP server** ([skill](skills/designdna/SKILL.md)).

## How it compares

A fair, high-level comparison with the typical workflows of adjacent tools as of September 2026. These products change quickly, so treat it as orientation, not a spec sheet.

| | DesignDNA | Site-to-Figma importers (e.g. html.to.design) | AI UI / app generators (e.g. v0, Lovable, Bolt, Stitch) | Screen-recording video tools |
| --- | :---: | :---: | :---: | :---: |
| Starts from **your live website** | ✓ | ✓ | partial (screenshots, prompts) | ✓ (recording) |
| **Editable layers** of the captured page | ✓ | ✓ | — | — |
| **Design system** extracted and **verified** against the source | ✓ | — | — | — |
| New sections **in the site's own style and grid** | ✓ | manual | prompt-dependent | — |
| **Reassembles the page** with generated sections inserted | ✓ | manual | — | — |
| **Directed motion video** from the design (camera, typing, clicks, end card) | ✓ | — | — | manual recording |
| **Local desktop app**, projects stay on your disk | ✓ | Figma cloud | cloud | varies |
| Runs **GPT and Claude** on the Codex / Claude Code subscriptions you already pay for | ✓ | — | own credits | — |

## Screenshots

| Node graph | DNA Editor |
| --- | --- |
| ![Source → UI Kit → Generator (Claude Opus) → Page graph](docs/media/graph.jpg) | ![DNA Editor with source layers and AI tools](docs/media/dna-editor.jpg) |

| slsbmb.com: live page (left) and DesignDNA Page with a generated contact form (right) | glebkudr.com: live page (left) and DesignDNA Page (right) |
| --- | --- |
| ![slsbmb comparison](docs/media/slsbmb-source-vs-page.jpg) | ![glebkudr comparison](docs/media/glebkudr-source-vs-page.jpg) |

Storyboard of the 24‑second product video: page scroll, form filling, click, zoom transition, logo.

![Video storyboard](docs/media/video-storyboard.jpg)

## Beta testing

DesignDNA is in **public beta (desktop 0.5.4)**. Thank you for testing! The most valuable feedback is a real site, the node where things went wrong, and a screenshot.

### Requirements

- **Windows 10/11** (primary test platform). macOS and Linux pass CI but get less manual testing.
- **Node.js 24**, **Python 3.12+**, **Git**.
- At least one signed-in AI CLI:
  - [Claude Code](https://docs.anthropic.com/en/docs/claude-code) with a Claude Pro or Max plan, and/or
  - [Codex CLI](https://github.com/openai/codex) with a ChatGPT plan.
- Optional: an OpenRouter key for Seedance video generation.

### Install and run from source

There are no packaged installers yet, so run the app from source:

```bash
git clone https://github.com/MaxBaranov1993/designdna.git
cd designdna
python -m venv .venv
```

Windows:

```bash
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m playwright install chromium
```

macOS / Linux:

```bash
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m playwright install chromium
```

Then:

```bash
npm ci --prefix frontend
npm ci --prefix desktop
npm run desktop:start
```

On the first launch, open **Agents → Connections** and check that Claude Code and/or Codex show as connected.

### A 15-minute test run

1. **Source Import**: paste a URL you own or may copy, tick *I own this site / have permission*, and run. Add Tablet or Mobile if you want them.
2. **UI Kit**: create it from the Source node. The AI review verifies masters and publishes a revision.
3. **Generator**: connect the UI Kit and a Prompt such as *"Contact form section for this site"*. Pick GPT or Claude in the node.
4. **Page**: connect the Source blocks and the generated section in any order, then run.
5. **Video**: connect the Page, open **Editor** and describe the video. For example: *"Scroll to the form, type a name and email, click the button, then zoom to the logo."* Then press **Render MP4**.

### What we would love to hear

- Sites that import badly: missing elements, wrong fonts, shifted sections. Please include the URL.
- Generated sections that do not look like the rest of the site.
- Videos with blank frames, jumpy camera or wrong targets.
- Anything confusing in the interface.

Please open an issue with the **Bug report** or **Beta feedback** template. Useful attachments:
- a screenshot;
- the provider and model you used;
- the model-call trace at `%APPDATA%\@designdna\desktop\data\traces\llm-calls.electron.jsonl`. It holds metadata only, never prompts or keys.

### Known limitations

- Sites with aggressive bot protection or constant animation may import partially. Decorative animated layers can show up frozen.
- Some accent text effects, such as gradient-highlighted words, may import as plain text.
- An unreachable site currently shows the slow 12‑minute import timeout instead of an immediate error.
- Very long pages are directed into videos of up to 20 seconds.
- AI steps run on your subscription and count against your plan's limits.

### Privacy

- Projects, captures, UI Kits and renders stay in `%APPDATA%\@designdna\desktop\data` (Windows) or the platform equivalent.
- The content of AI steps is sent only to the provider you choose in the node, through your own Claude Code / Codex CLI.

## Documentation

| Topic | Document |
| --- | --- |
| Repository map, commands, invariants (for contributors and agents) | [AGENTS.md](AGENTS.md) |
| Nodes, execution, Source Import, project storage | [docs/node-execution.md](docs/node-execution.md) |
| How the design system reaches the generator prompt | [docs/design-system-prompt-2026-09-09.md](docs/design-system-prompt-2026-09-09.md) |
| Video: motion director, story scenarios, rendering | [docs/video-motion-director.md](docs/video-motion-director.md) |
| How the app talks to Claude Code and Codex | [docs/AGENT-CONTRACT.md](docs/AGENT-CONTRACT.md) |
| Generator design policy | [docs/generator-design-playbook/README.md](docs/generator-design-playbook/README.md) |
| MCP tools for external agents | [skills/designdna/SKILL.md](skills/designdna/SKILL.md) |

## Development

```bash
npm --prefix desktop test
node --test frontend/tests/*.test.mjs
.venv/Scripts/python -m pytest app -q --ignore-glob="app/ui_*" --ignore-glob="*_live_test.py"
```

Details, conventions and the full CI matrix are in [AGENTS.md](AGENTS.md) and [.github/workflows/desktop.yml](.github/workflows/desktop.yml).
