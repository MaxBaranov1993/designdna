# Design craft (generate mode)

Distilled from the project's design skills (frontend-design, taste-design,
web-design-guidelines). Applies to free-form generation; locked Style DNA
tokens still win over everything below.

## Point of view

- Pick ONE strong visual direction for the brief's subject and commit fully.
  A footer/hero/cards set that "could belong to any product" is a failure.
- Ground choices in the subject's own world: its materials, objects,
  vocabulary. A furniture store, a fintech app and a coffee roaster must not
  share the same layout skeleton with swapped colors.
- Take one deliberate, justifiable aesthetic risk per page (an oversized
  display headline, an asymmetric hero, an unusual section order) — one, not five.

## Hero is a thesis

- Open with the most characteristic thing about the subject: a statement
  headline, a product image, a number that matters — never a generic
  "badge + heading + two buttons + dashboard mockup" template by default.
- One primary CTA. Secondary action, if any, is visually quieter (ghost/link).

## First screen (what the pixel judge checks first)

- The thesis, the primary CTA and one proof must all sit inside the first
  900px of a 1440px artboard. No decorative empty band between the navbar and
  the hero: hero top padding is at most one section step (≤ 96px).
- The hero headline uses the `display` role — visibly larger than any section
  heading; section headings use `h2`. A hero whose headline looks like a
  section heading fails hierarchy.
- The first screen is dense with useful content: headline, one paragraph, CTA,
  a proof line or number, and one media/placeholder — not one paragraph
  floating in white space.

## Desktop width discipline (1440px artboard, 1120px content rail)

- Every section uses the whole content rail. A single 560–650px column with
  1000px of empty canvas beside it is a mobile layout, not a desktop one.
- Compose sections as rows: `layout: "row"` with two or three children whose
  numeric widths plus gaps add up to the rail (e.g. 640 + 64 + 416, or three
  of 352 with gap 32). Children that carry no width (`heading`, `text`,
  `image`) share the remaining width of the row automatically.
- Lists of steps, features or FAQ stay short: 3–5 items, each with unique
  copy. A row of three empty "Step 1 / Step 2 / Step 3" cards is filler.
- The whole page fits 6–8 sections and stays under ~5500px tall at 1440px;
  longer pages are read as padding.

## Free layout discipline

- Prefer auto-layout frames (`layout: row|column` with `gap`) for groups.
  Use `layout: "free"` with x/y only for deliberate overlaps of at most two
  elements (a card breaking a media edge by ≤ 24px).
- In a free parent every child must fit inside the parent's width/height and
  must not cover another child by more than a quarter of its area — the
  deterministic quality gate rejects such compositions.
- An image placeholder with `imagePrompt` is a finished element: never redraw a
  "product UI" from rectangles and text instead of it.

## Composition and rhythm

- Vary section density: alternate tight and airy sections; not every section
  is a 3-column card grid. Use asymmetry, offset grids, full-bleed media or
  horizontal bands where the content allows.
- Structural devices (eyebrows, numbering, dividers, labels) must encode real
  information about the content — no decorative "01/02/03" unless the content
  truly is a sequence.
- Cards in one row share height; media dominates over text in product cards.
- Product / pricing cards: the price and the CTA never share a cramped row.
  Put the price on its own line (`nowrap`, display role) and the CTA below it
  full-width, or give the row ≥ 2 lines of room; card padding is uniform
  (≥ 16px on every side, never `[16, 4]`); titles get a fixed 2-line box so
  card bottoms align across the row.

## Color and tokens discipline

- Every color comes from `tokens` — never invent hex values in props.
- `primary` is the brand voice: CTAs, key accents, active states must use it.
  A page where nothing uses `primary`/`accent` reads as an unstyled wireframe.
- Alternate section backgrounds (`background` vs `surface`) to build rhythm;
  keep text/muted roles consistent on each surface.

## Текстовые стили

- Display font carries the personality: large, tight-tracked headlines;
  body stays quiet and readable. Never more than the given families.
- Headlines say something concrete (no "Welcome to our platform");
  body copy is realistic, specific, in the brief's language.
- Every `heading` and `text` element declares a semantic `typeRole`: use
  `display` for the hero thesis, `h1`/`h2`/`h3` for the matching hierarchy,
  `lead` for an introductory paragraph, `body` for ordinary copy, `small` for
  captions and metadata, and `eyebrow` for a short overline label.
- When `typeRole` is present, never set `style.fontSize`, `style.lineHeight`,
  `style.fontWeight`, or `style.letterSpacing` on that element. The role is the
  single source of truth, so changing a text style updates every matching use.

## Imagery

- Every image gets `imagePrompt` with real art direction: subject, material,
  lighting, palette, camera feel. No "business team smiling" stock clichés.

## Banned (AI slop)

- Purple-blue page-wide gradients, glow blobs, glassmorphism without reason.
- Emoji as icons; icon-in-a-circle × 3 with filler text.
- Same padding everywhere; everything centered; everything in cards.
