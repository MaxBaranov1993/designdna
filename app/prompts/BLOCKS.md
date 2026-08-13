# Blocks

This file is used by `app/llm_client.py` inside the generation system prompt. Keep it concise, current and model-friendly.

The model must generate valid Design IR using known semantic blocks. It may combine blocks, but should not invent unknown top-level block types unless the schema and renderer support them.

## Top-level sections

### `source-block`

Rendered Source Import section. It keeps a compact semantic DOM tree and carries `semantic` metadata (`role`, `label`, `selector`, optional repeat count/kind). Flex and grid containers compile to nested auto-layout frames; only real overlays, positioned elements, or a child explicitly detached by the user use absolute positioning. Stable `sourceKey` values connect desktop, tablet and mobile overrides without duplicating the tree.

### navbar

Use for site navigation.

Common props:

- `logoText`
- `links: [{label, href}]`
- `cta: {text, variant, href?, icon?}`
- `sticky`
- `transparent`

Variants:

- `classic`
- `centered`
- `split`

### hero

Use for the primary first screen.

Common props:

- `badge`
- `heading`
- `subheading`
- `ctaPrimary`
- `ctaSecondary`
- `media`
- `align`

Variants:

- `split`
- `centered`
- `media-bg`

### feature-grid

Use for feature cards.

Common props:

- `heading`
- `subheading`

Children:

- `card`
- `heading`
- `text`

Variants:

- `grid-3`
- `grid-4`
- `bento`

### feature-alternating

Use for alternating image/text rows.

Variants:

- `2-rows`
- `image-left`
- `image-right`

### stats

Use for metrics.

Common props:

- `heading`
- `items: [{value, label}]`

Variants:

- `grid`
- `with-heading`

### gallery

Use for screenshots, work samples, visual grids.

Variants:

- `grid-uniform`
- `masonry`
- `carousel`

### logo-cloud

Use for client/platform logos.

Variants:

- `row`
- `grid`

### testimonials

Use for quotes/reviews.

Variants:

- `grid-2`
- `grid-3`
- `carousel`

### pricing

Use for pricing plans.

Common props:

- `heading`
- `subheading`
- `tiers`

Variants:

- `cards`
- `comparison`

### faq

Use for questions and answers.

Common props:

- `heading`
- `items: [{question, answer}]`

Variants:

- `accordion`
- `grid`

### steps

Use for “how it works”.

Variants:

- `horizontal`
- `vertical`

### team

Use for people/team sections.

Variants:

- `grid-4`
- `cards`

### newsletter

Use for email capture.

Common props:

- `heading`
- `subheading`
- `placeholder`
- `submitText`

Variants:

- `boxed`
- `inline`

### cta

Use for conversion sections.

Common props:

- `heading`
- `subheading`
- `ctaPrimary`
- `ctaSecondary`

Variants:

- `centered`
- `split`

### footer

Use for footer navigation.

Common props:

- `logoText`
- `tagline`
- `columns`
- `copyright`

Variants:

- `columns`
- `minimal`

## Child elements

Allowed child elements:

- `heading`
- `text`
- `button`
- `image`
- `card`
- `avatar`
- `rating`
- `rect`
- `frame`

## Token guidance

Always include useful tokens:

- `color.primary`
- `color.secondary`
- `color.accent`
- `color.background`
- `color.surface`
- `color.text`
- `color.textMuted`
- `color.border`
- `font.display`
- `font.body`
- `radius`
- `spacing`
- `shadow`

## Controlled generation rules

When reference IR or Style DNA is provided:

- preserve structure unless asked otherwise;
- preserve layout if lock/layout language is present;
- use tokens from Style DNA;
- avoid adding random sections;
- keep copy realistic and concise;
- return only valid JSON IR.

When asked to derive a related component:

- reuse visual rhythm;
- reuse typography scale;
- reuse radius and spacing logic;
- create the requested block type only;
- do not recreate the entire page unless asked.
