"""Capture an explicit, measured document crop without Chromium negative clips."""
import math


def capture_source_png(page, locator, item: dict) -> bytes:
    root = item.get('root') or {}
    clip = root.get('captureRect')
    if not isinstance(clip, dict):
        return locator.screenshot(type='png')
    if any(not isinstance(clip.get(k), (int, float)) or not math.isfinite(clip[k])
           for k in ('x', 'y', 'width', 'height')):
        raise ValueError('Invalid measured Source capture rectangle')
    if clip['x'] < 0 or clip['y'] < 0 or clip['width'] <= 0 or clip['height'] <= 0:
        raise ValueError('Source capture rectangle extends before the document')
    original = root.get('originalBounds')
    if original:
        current = locator.evaluate('''el => {const r=el.getBoundingClientRect();
          return {x:r.x+scrollX,y:r.y+scrollY,width:r.width,height:r.height}}''')
        if any(abs(current[k] - original[k]) > 0.5 for k in ('x', 'y', 'width', 'height')):
            raise ValueError('Source geometry changed after compilation')
    # Unlike locator.screenshot, this never scrolls the element. The compiler
    # recorded this exact crop and offset; no padding, rescaling or guessed paint.
    return page.screenshot(type='png', full_page=True, clip=clip)
