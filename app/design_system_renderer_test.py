"""The desktop DS renderer releases its context before the browser on every exit."""
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from design_system import desktop_ai


@pytest.mark.parametrize("failure", [None, "page", "render", "context-close"])
def test_renderer_drains_context_before_browser(monkeypatch, failure):
    events = []
    page = object()

    def new_page():
        events.append("page")
        if failure == "page":
            raise RuntimeError(failure)
        return page

    def close_context():
        events.append("context-close")
        if failure == "context-close":
            raise RuntimeError(failure)

    def new_context(**kwargs):
        assert kwargs == {"viewport": {"width": 1440, "height": 900}, "device_scale_factor": 1}
        events.append("context")
        return SimpleNamespace(new_page=new_page, close=close_context)

    browser = SimpleNamespace(new_context=new_context, close=lambda: events.append("browser-close"))

    @contextmanager
    def managed_playwright():
        try:
            yield object()
        finally:
            events.append("playwright-stop")

    import scraper
    import playwright.sync_api
    monkeypatch.setattr(scraper, "launch_chromium", lambda _: browser)
    monkeypatch.setattr(playwright.sync_api, "sync_playwright", managed_playwright)

    def run():
        with desktop_ai._renderer() as (actual_page, render):
            assert actual_page is page
            assert render is desktop_ai.master_review.render_master_png
            if failure == "render":
                raise RuntimeError(failure)

    if failure:
        with pytest.raises(RuntimeError, match=failure):
            run()
    else:
        run()
    assert events == ["context", "page", "context-close", "browser-close", "playwright-stop"]
