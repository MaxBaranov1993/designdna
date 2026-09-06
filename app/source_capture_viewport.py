"""Place Source blocks between external sticky bars before measuring or painting.

Scrolling down moves document content UP. A positive header-height adjustment
therefore pushed RSALE blocks behind its header, contaminating both reference
and inherited-backdrop PNGs. Only scroll here: never hide source content, move
DOM nodes, change the responsive viewport, or mutate source styles.
"""

_PREPARE_VIEWPORT_JS = """async (root) => {
  const settle = () => new Promise(resolve =>
    requestAnimationFrame(() => requestAnimationFrame(resolve)));
  const measure = () => {
    const rect = root.getBoundingClientRect();
    let top = 0, bottom = innerHeight;
    const overlaps = [];
    for (const el of document.querySelectorAll('*')) {
      // A captured header and sticky containers owning this block are source
      // content themselves, not external overlays to scroll away from.
      if (el === root || root.contains(el) || el.contains(root)) continue;
      const cs = getComputedStyle(el);
      if (!['fixed', 'sticky'].includes(cs.position)) continue;
      if (cs.display === 'none' || cs.visibility === 'hidden' || Number(cs.opacity) === 0) continue;
      const r = el.getBoundingClientRect();
      if (r.width <= 0 || r.height <= 0 || r.bottom <= 0 || r.top >= innerHeight) continue;
      if (r.right <= rect.left || r.left >= rect.right) continue;
      const topInset = Number.parseFloat(cs.top), bottomInset = Number.parseFloat(cs.bottom);
      if (cs.position === 'sticky' &&
          !(Number.isFinite(topInset) && r.top <= Math.max(0, topInset) + 1) &&
          !(Number.isFinite(bottomInset) && r.bottom >= innerHeight - bottomInset - 1)) continue;
      // Chromium resolves computed top even for bottom-anchored fixed nodes.
      // Classify by the nearest viewport edge, not by computed top being numeric.
      // Full-height overlays cannot be avoided by scrolling into another band.
      if (r.height >= innerHeight) continue;
      if (r.top <= innerHeight - r.bottom) top = Math.max(top, r.bottom);
      else bottom = Math.min(bottom, r.top);
      if (r.bottom > rect.top + 0.5 && r.top < rect.bottom - 0.5) overlaps.push(el.tagName);
    }
    return {rect, top, bottom, overlaps};
  };
  let attempts = 0;
  for (; attempts < 3; attempts++) {
    const {rect, top, bottom, overlaps} = measure();
    if (!overlaps.length) break;
    // Keep a fitting block wholly visible, so later locator screenshots do
    // not auto-scroll it back under the header. Prefer 16px of breathing room.
    const gap = Math.max(0, Math.min(16, (bottom - top - rect.height) / 2));
    const lower = top + gap, upper = bottom - gap - rect.height;
    const desired = upper >= lower ? Math.max(lower, Math.min(rect.top, upper)) : top;
    const delta = rect.top - desired;
    const previous = scrollY;
    window.scrollBy({top: delta, left: 0, behavior: 'instant'});
    await settle();
    if (Math.abs(scrollY - previous) < 0.5) break;
  }
  await settle();
  const {rect, top, bottom, overlaps} = measure();
  return {
    clear: overlaps.length === 0,
    fullyVisible: rect.top >= 0 && rect.bottom <= innerHeight + 0.5,
    top: rect.top, bottom: rect.bottom, obstructionBottom: top,
    bottomObstructionTop: bottom, overlappingElements: overlaps,
    scrollY, attempts,
  };
}"""


def prepare_capture_viewport(page, locator) -> dict:
    """Call after lazy-image settling, BEFORE compilation/backdrop/reference.

    The caller owns initial scroll-into-view. Return measured placement so an
    unavoidable overlap (e.g. a fixed target) remains explicit. This helper
    cannot make tall/covered content fit by hiding overlays or changing layout.
    """
    return locator.evaluate(_PREPARE_VIEWPORT_JS)
