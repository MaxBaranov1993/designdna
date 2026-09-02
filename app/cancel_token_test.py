"""cancel_token: привязка к контексту, флаг отмены, распространение в потоки."""
from __future__ import annotations

import contextvars
import threading

import pytest

import cancel_token


@pytest.fixture(autouse=True)
def _clean():
    cancel_token.reset()
    cancel_token.set_current(None)
    yield
    cancel_token.reset()
    cancel_token.set_current(None)


def test_no_binding_is_never_cancelled():
    assert cancel_token.current() is None
    assert cancel_token.is_cancelled() is False
    cancel_token.check()  # не бросает


def test_cancel_sets_flag_for_bound_request():
    cancel_token.set_current("req-1")
    assert cancel_token.is_cancelled() is False
    assert cancel_token.cancel("req-1") is True  # известный запрос
    assert cancel_token.is_cancelled() is True
    assert cancel_token.is_cancelled("req-1") is True
    with pytest.raises(cancel_token.Cancelled) as raised:
        cancel_token.check()
    assert raised.value.request_id == "req-1"
    assert raised.value.cancelled is True


def test_cancel_before_binding_is_not_lost():
    # отмена пришла, пока фрейм ждал свободный поток пула
    assert cancel_token.cancel("early") is False
    cancel_token.set_current("early")
    assert cancel_token.is_cancelled() is True


def test_clear_drops_token_and_binding():
    cancel_token.set_current("req-2")
    cancel_token.cancel("req-2")
    cancel_token.clear("req-2")
    assert cancel_token.current() is None
    assert cancel_token.is_cancelled("req-2") is False


def test_other_requests_unaffected():
    cancel_token.set_current("a")
    cancel_token.cancel("b")
    assert cancel_token.is_cancelled() is False
    assert cancel_token.is_cancelled("b") is True


def test_context_copy_propagates_into_thread():
    # anyio.to_thread.run_sync копирует контекст — эмулируем copy_context().run
    cancel_token.set_current("threaded")
    seen: dict[str, bool] = {}

    def work() -> None:
        seen["before"] = cancel_token.is_cancelled()
        cancel_token.cancel("threaded")
        seen["after"] = cancel_token.is_cancelled()

    thread = threading.Thread(target=contextvars.copy_context().run, args=(work,))
    thread.start()
    thread.join()
    assert seen == {"before": False, "after": True}
    # поток без копии контекста ничего не видит
    plain: dict[str, bool] = {}
    thread = threading.Thread(target=lambda: plain.setdefault("v", cancel_token.is_cancelled()))
    thread.start()
    thread.join()
    assert plain["v"] is False
