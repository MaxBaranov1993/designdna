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

## Composition and rhythm

- Vary section density: alternate tight and airy sections; not every section
  is a 3-column card grid. Use asymmetry, offset grids, full-bleed media or
  horizontal bands where the content allows.
- Structural devices (eyebrows, numbering, dividers, labels) must encode real
  information about the content — no decorative "01/02/03" unless the content
  truly is a sequence.
- Cards in one row share height; media dominates over text in product cards.

## Color and tokens discipline

- Every color comes from `tokens` — never invent hex values in props.
- `primary` is the brand voice: CTAs, key accents, active states must use it.
  A page where nothing uses `primary`/`accent` reads as an unstyled wireframe.
- Alternate section backgrounds (`background` vs `surface`) to build rhythm;
  keep text/muted roles consistent on each surface.

## Typography

- Display font carries the personality: large, tight-tracked headlines;
  body stays quiet and readable. Never more than the given families.
- Headlines say something concrete (no "Welcome to our platform");
  body copy is realistic, specific, in the brief's language.

## Imagery

- Every image gets `imagePrompt` with real art direction: subject, material,
  lighting, palette, camera feel. No "business team smiling" stock clichés.

## Banned (AI slop)

- Purple-blue page-wide gradients, glow blobs, glassmorphism without reason.
- Emoji as icons; icon-in-a-circle × 3 with filler text.
- Same padding everywhere; everything centered; everything in cards.
