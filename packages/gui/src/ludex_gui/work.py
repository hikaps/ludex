"""Run blocking core calls off the UI thread; the result comes back on the UI thread."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from ludex.errors import LudexError


class _Done(QObject):
    finished = Signal(object, object)  # result, error message


class _Task(QRunnable):
    def __init__(self, call: Callable[[], Any], done: _Done) -> None:
        super().__init__()
        self._call = call
        self._done = done

    def run(self) -> None:
        result, error = None, None
        try:
            result = self._call()
        except LudexError as exc:
            error = exc.message
        except Exception as exc:  # a worker must always report back, or the page stays busy
            error = f"failed ({type(exc).__name__})"
        self._done.finished.emit(result, error)


_live: set[_Done] = set()


def run_async(call: Callable[[], Any], on_done: Callable[[Any, str | None], None]) -> None:
    """Call ``call()`` on a pool thread, then ``on_done(result, error)`` on the UI thread (``error`` is a message or None)."""
    done = _Done()
    _live.add(done)

    def finish(result: object, error: object) -> None:
        _live.discard(done)
        on_done(result, error)  # type: ignore[arg-type]

    done.finished.connect(finish)
    QThreadPool.globalInstance().start(_Task(call, done))
