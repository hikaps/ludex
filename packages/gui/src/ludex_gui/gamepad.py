"""Controller input: turns gamepad buttons into key presses on the launcher window.

Keys are only sent while the launcher window has focus, so a running game's input
never drives ludex. The SDL2 backend is the optional ``ludex-gui[gamepad]`` extra.
"""

from __future__ import annotations

from typing import Protocol

from PySide6.QtCore import Q_ARG, QEvent, QMetaObject, QObject, Qt, QTimer
from PySide6.QtGui import QGuiApplication, QKeyEvent
from PySide6.QtQuick import QQuickWindow

_NONE = Qt.KeyboardModifier.NoModifier

KEYS: dict[str, tuple[Qt.Key, Qt.KeyboardModifier]] = {
    "dpup": (Qt.Key.Key_Up, _NONE),
    "dpdown": (Qt.Key.Key_Down, _NONE),
    "dpleft": (Qt.Key.Key_Left, _NONE),
    "dpright": (Qt.Key.Key_Right, _NONE),
    "a": (Qt.Key.Key_Return, _NONE),
    "b": (Qt.Key.Key_Escape, _NONE),
}
# Controls that call a function of the window: shortcuts only fire for real key input, not synthetic events.
ACTIONS: dict[str, tuple[str, int | None]] = {
    "x": ("playCurrent", None),
    "leftshoulder": ("cycle", -1),
    "rightshoulder": ("cycle", 1),
}
DIRECTIONS = frozenset({"dpup", "dpdown", "dpleft", "dpright"})
_ARROWS = frozenset({Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_Left, Qt.Key.Key_Right})
_FORWARD = frozenset({Qt.Key.Key_Down, Qt.Key.Key_Right})
REPEAT_DELAY_MS = 400
REPEAT_INTERVAL_MS = 90
POLL_MS = 16
_STICK_PRESS = 16000
_STICK_RELEASE = 8000


class Source(Protocol):
    def poll(self) -> list[tuple[str, bool]]:
        """Return ``(control, pressed)`` events since the last call, in arrival order."""

    def close(self) -> None: ...


def send_key(window: QQuickWindow, key: Qt.Key, modifiers: Qt.KeyboardModifier) -> bool:
    """Deliver a key press and release to the window; True when an item used it or focus moved.

    An arrow no item uses moves focus to the next or previous control.
    """
    text = "\r" if key == Qt.Key.Key_Return else ""
    press = QKeyEvent(QEvent.Type.KeyPress, key, modifiers, text)
    press.setAccepted(False)
    QGuiApplication.sendEvent(window, press)
    QGuiApplication.sendEvent(window, QKeyEvent(QEvent.Type.KeyRelease, key, modifiers, text))
    if key in _ARROWS and not press.isAccepted():
        forward = key in _FORWARD
        item = window.activeFocusItem() or window.contentItem()
        target = item.nextItemInFocusChain(forward)
        if target is not None and target is not item:
            reason = Qt.FocusReason.TabFocusReason if forward else Qt.FocusReason.BacktabFocusReason
            target.forceActiveFocus(reason)
            return True
    return press.isAccepted()


class Gamepad(QObject):
    """Polls a :class:`Source` and presses keys on the window, repeating held directions."""

    def __init__(self, window: QQuickWindow, source: Source) -> None:
        super().__init__(window)
        self._window = window
        self._source = source
        self._held: str | None = None
        self._poll = QTimer(self)
        self._poll.setInterval(POLL_MS)
        self._poll.timeout.connect(self._drain)
        self._repeat = QTimer(self)
        self._repeat.setSingleShot(True)
        self._repeat.timeout.connect(self._again)

    def start(self) -> None:
        self._poll.start()

    def close(self) -> None:
        self._poll.stop()
        self._repeat.stop()
        self._source.close()

    def press(self, control: str) -> None:
        if control not in KEYS and control not in ACTIONS:
            return
        if QGuiApplication.focusWindow() is not self._window:
            self._repeat.stop()
            self._held = None
            return
        if control in ACTIONS:
            name, step = ACTIONS[control]
            args = [] if step is None else [Q_ARG("QVariant", step)]
            QMetaObject.invokeMethod(self._window, name, Qt.ConnectionType.DirectConnection, *args)
            return
        if not send_key(self._window, *KEYS[control]) and control == "b":
            QMetaObject.invokeMethod(self._window, "goBack", Qt.ConnectionType.DirectConnection)
        if control in DIRECTIONS:
            self._held = control
            self._repeat.start(REPEAT_DELAY_MS)

    def release(self, control: str) -> None:
        if control == self._held:
            self._repeat.stop()
            self._held = None

    def _drain(self) -> None:
        for control, pressed in self._source.poll():
            (self.press if pressed else self.release)(control)

    def _again(self) -> None:
        if self._held is None:
            return
        if QGuiApplication.focusWindow() is not self._window:
            self._held = None
            return
        send_key(self._window, *KEYS[self._held])
        self._repeat.start(REPEAT_INTERVAL_MS)


class _SdlSource:
    def __init__(self, sdl2) -> None:  # noqa: ANN001 - optional module
        import ctypes

        self._sdl = sdl2
        self._ctypes = ctypes
        self._pads: dict[int, object] = {}
        self._stick: dict[int, str | None] = {}
        self._event = sdl2.SDL_Event()

    def poll(self) -> list[tuple[str, bool]]:
        sdl, out = self._sdl, []
        ev = self._event
        while sdl.SDL_PollEvent(self._ctypes.byref(ev)):
            kind = ev.type
            if kind == sdl.SDL_CONTROLLERDEVICEADDED:
                pad = sdl.SDL_GameControllerOpen(ev.cdevice.which)
                if pad:
                    joy = sdl.SDL_GameControllerGetJoystick(pad)
                    self._pads[sdl.SDL_JoystickInstanceID(joy)] = pad
            elif kind == sdl.SDL_CONTROLLERDEVICEREMOVED:
                pad = self._pads.pop(ev.cdevice.which, None)
                if pad:
                    sdl.SDL_GameControllerClose(pad)
            elif kind in (sdl.SDL_CONTROLLERBUTTONDOWN, sdl.SDL_CONTROLLERBUTTONUP):
                name = sdl.SDL_GameControllerGetStringForButton(ev.cbutton.button)
                out.append((name.decode(), kind == sdl.SDL_CONTROLLERBUTTONDOWN))
            elif kind == sdl.SDL_CONTROLLERAXISMOTION:
                self._axis(ev.caxis.axis, ev.caxis.value, out)
        return out

    def _axis(self, axis: int, value: int, out: list[tuple[str, bool]]) -> None:
        sdl = self._sdl
        names = {
            sdl.SDL_CONTROLLER_AXIS_LEFTX: ("dpleft", "dpright"),
            sdl.SDL_CONTROLLER_AXIS_LEFTY: ("dpup", "dpdown"),
        }.get(axis)
        if names is None:
            return
        current = self._stick.get(axis)
        if value <= -_STICK_PRESS:
            new = names[0]
        elif value >= _STICK_PRESS:
            new = names[1]
        elif abs(value) < _STICK_RELEASE:
            new = None
        else:
            return
        if new != current:
            if current is not None:
                out.append((current, False))
            if new is not None:
                out.append((new, True))
            self._stick[axis] = new

    def close(self) -> None:
        for pad in self._pads.values():
            self._sdl.SDL_GameControllerClose(pad)
        self._pads.clear()
        self._sdl.SDL_QuitSubSystem(self._sdl.SDL_INIT_GAMECONTROLLER)


def open_sdl_source() -> Source | None:
    """Open the SDL2 controller source, or ``None`` when the extra is missing or SDL fails."""
    try:
        import sdl2
    except ImportError:
        return None
    sdl2.SDL_SetHint(sdl2.SDL_HINT_JOYSTICK_ALLOW_BACKGROUND_EVENTS, b"1")
    if sdl2.SDL_Init(sdl2.SDL_INIT_GAMECONTROLLER) != 0:
        return None
    return _SdlSource(sdl2)
