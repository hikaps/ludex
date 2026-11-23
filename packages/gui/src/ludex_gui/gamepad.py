"""Controller input: turns gamepad buttons into key presses on the launcher window.

Keys are only sent while the launcher window has focus, so a running game's input
never drives ludex. The SDL2 backend is the optional ``ludex-gui[gamepad]`` extra.
"""

from __future__ import annotations

from typing import Protocol

from PySide6.QtCore import Q_ARG, QEvent, QMetaObject, QObject, QPointF, QRectF, QSizeF, Qt, QTimer
from PySide6.QtGui import QGuiApplication, QKeyEvent
from PySide6.QtQuick import QQuickItem, QQuickWindow

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
    "y": ("focusSearch", None),
    "start": ("openMenu", None),
    "leftshoulder": ("cycle", -1),
    "rightshoulder": ("cycle", 1),
}
DIRECTIONS = frozenset({"dpup", "dpdown", "dpleft", "dpright"})
_ARROWS = frozenset({Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_Left, Qt.Key.Key_Right})
_FORWARD = frozenset({Qt.Key.Key_Down, Qt.Key.Key_Right})
_ARROW_CLASSES = frozenset({
    "QQuickItemView", "QQuickTextInput", "QQuickTextEdit", "QQuickComboBox", "QQuickSlider", "QQuickSpinBox", "QQuickTumbler",
})
_SIDEWAYS_ONLY = frozenset({"QQuickTextInput"})  # a one-line field moves its cursor with Left and Right, not Up and Down
_VERTICAL = frozenset({Qt.Key.Key_Up, Qt.Key.Key_Down})
REPEAT_DELAY_MS = 400
REPEAT_INTERVAL_MS = 90
POLL_MS = 16
_STICK_PRESS = 16000
_STICK_RELEASE = 8000


class Source(Protocol):
    def poll(self) -> list[tuple[str, bool]]:
        """Return ``(control, pressed)`` events since the last call, in arrival order."""

    def close(self) -> None: ...


def _focusables(root: QQuickItem, found: list[QQuickItem]) -> list[QQuickItem]:
    for child in root.childItems():
        if not child.isVisible():
            continue
        if child.property("activeFocusOnTab") and child.isEnabled() and child.width() > 0:
            found.append(child)
        _focusables(child, found)
    return found


def _scene_rect(item: QQuickItem) -> QRectF:
    return QRectF(item.mapToScene(QPointF(0, 0)), QSizeF(item.width(), item.height()))


def _gap(lo_a: float, hi_a: float, lo_b: float, hi_b: float) -> float:
    return max(lo_a - hi_b, lo_b - hi_a, 0.0)


def _scope(item: QQuickItem, content: QQuickItem) -> QQuickItem:
    """The popup the focus is in (its direct child of the overlay), else the whole window."""
    node = item
    while node is not None and node.parentItem() is not None:
        if node.parentItem().metaObject().className().startswith("QQuickOverlay"):
            return node
        node = node.parentItem()
    return content


def _form(item: QQuickItem | None) -> QQuickItem | None:
    """The enclosing form (an item with ``padForm: true``), whose controls Up and Down walk in order."""
    while item is not None:
        if item.property("padForm") is True:
            return item
        item = item.parentItem()
    return None


def _walk_form(current: QQuickItem, key: Qt.Key) -> bool:
    """Up and Down in a form go to the previous or next control in reading order, so none is skipped."""
    form = _form(current)
    if form is None:
        return False
    forward = key == Qt.Key.Key_Down
    nxt = current.nextItemInFocusChain(forward)
    node = nxt
    while node is not None and node is not form:
        node = node.parentItem()
    if nxt is None or nxt is current or node is None:  # the end of the form: leave it by position
        return False
    nxt.forceActiveFocus(Qt.FocusReason.TabFocusReason if forward else Qt.FocusReason.BacktabFocusReason)
    return True


def move_focus(window: QQuickWindow, key: Qt.Key) -> bool:
    """Focus the nearest control in the pressed direction; False when there is none."""
    current = window.activeFocusItem()
    content = window.contentItem()
    if current is None:
        return False
    if key in _VERTICAL and _walk_form(current, key):
        return True
    here = _scene_rect(current)
    scope = _scope(current, content)
    best: tuple[float, QQuickItem] | None = None
    for item in _focusables(scope, []):
        if item is current:
            continue
        there = _scene_rect(item)
        if current is scope:  # a dialog that has no control focused yet: start at its top left
            along, across = there.top() - here.top(), there.left() - here.left()
        elif key == Qt.Key.Key_Right:
            along, across = there.left() - here.right(), _gap(here.top(), here.bottom(), there.top(), there.bottom())
        elif key == Qt.Key.Key_Left:
            along, across = here.left() - there.right(), _gap(here.top(), here.bottom(), there.top(), there.bottom())
        elif key == Qt.Key.Key_Down:
            along, across = there.top() - here.bottom(), _gap(here.left(), here.right(), there.left(), there.right())
        else:
            along, across = here.top() - there.bottom(), _gap(here.left(), here.right(), there.left(), there.right())
        if along < -1:
            continue
        score = max(along, 0.0) + 3 * across
        if best is None or score < best[0]:
            best = (score, item)
    if best is None:
        return False
    forward = key in _FORWARD
    best[1].forceActiveFocus(Qt.FocusReason.TabFocusReason if forward else Qt.FocusReason.BacktabFocusReason)
    return True


def _handles_arrows(item: QQuickItem | None, key: Qt.Key) -> bool:
    """True when the focused item, or a list or grid around it, moves something with the arrows itself.

    A modal popup accepts every key that reaches it, so acceptance alone cannot tell a control from a popup.
    """
    while item is not None:
        meta = item.metaObject()
        while meta is not None:
            name = meta.className()
            if name in _ARROW_CLASSES and not (name in _SIDEWAYS_ONLY and key in _VERTICAL):
                return True
            meta = meta.superClass()
        item = item.parentItem()
    return False


def send_key(window: QQuickWindow, key: Qt.Key, modifiers: Qt.KeyboardModifier) -> bool:
    """Deliver a key press and release to the window; True when something used it.

    An arrow no item uses moves focus to the nearest control in that direction.
    """
    text = "\r" if key == Qt.Key.Key_Return else ""
    press = QKeyEvent(QEvent.Type.KeyPress, key, modifiers, text)
    press.setAccepted(False)
    before = window.activeFocusItem()
    QGuiApplication.sendEvent(window, press)
    QGuiApplication.sendEvent(window, QKeyEvent(QEvent.Type.KeyRelease, key, modifiers, text))
    if key in _ARROWS and not (press.isAccepted() and (window.activeFocusItem() is not before or _handles_arrows(before, key))):
        return move_focus(window, key)
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
        if control == "a" and self._editing():
            QMetaObject.invokeMethod(self._window, "openKeyboard", Qt.ConnectionType.DirectConnection)
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

    def _editing(self) -> bool:
        """True while a writable text field has focus: A then opens the on-screen keyboard instead of pressing Return."""
        item = self._window.activeFocusItem()
        return item is not None and item.property("cursorPosition") is not None and not item.property("readOnly")

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
        self._stick: dict[tuple[int, int], str | None] = {}
        self._held: dict[str, set[int]] = {}  # control -> the devices holding it
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
                which = ev.cdevice.which
                pad = self._pads.pop(which, None)
                if pad:
                    sdl.SDL_GameControllerClose(pad)
                for control in list(self._held):  # nothing stays pressed that the unplugged pad was holding
                    self._hold(which, control, False, out)
                for key in [k for k in self._stick if k[0] == which]:
                    del self._stick[key]
            elif kind in (sdl.SDL_CONTROLLERBUTTONDOWN, sdl.SDL_CONTROLLERBUTTONUP):
                name = sdl.SDL_GameControllerGetStringForButton(ev.cbutton.button)
                self._hold(ev.cbutton.which, name.decode(), kind == sdl.SDL_CONTROLLERBUTTONDOWN, out)
            elif kind == sdl.SDL_CONTROLLERAXISMOTION:
                self._axis(ev.caxis.which, ev.caxis.axis, ev.caxis.value, out)
        return out

    def _hold(self, which: int, control: str, pressed: bool, out: list[tuple[str, bool]]) -> None:
        """Press or release ``control`` for one device. Steam shows a pad twice (the real one and its virtual copy), so a
        control counts as pressed while any device holds it, and is reported once."""
        holders = self._held.setdefault(control, set())
        was = bool(holders)
        holders.add(which) if pressed else holders.discard(which)
        if bool(holders) != was:
            out.append((control, bool(holders)))
        if not holders:
            del self._held[control]

    def _axis(self, which: int, axis: int, value: int, out: list[tuple[str, bool]]) -> None:
        sdl = self._sdl
        names = {
            sdl.SDL_CONTROLLER_AXIS_LEFTX: ("dpleft", "dpright"),
            sdl.SDL_CONTROLLER_AXIS_LEFTY: ("dpup", "dpdown"),
        }.get(axis)
        if names is None:
            return
        key = (which, axis)
        current = self._stick.get(key)
        new = current
        if value <= -_STICK_PRESS:
            new = names[0]
        elif value >= _STICK_PRESS:
            new = names[1]
        elif current == names[0] and value > -_STICK_RELEASE:
            new = None
        elif current == names[1] and value < _STICK_RELEASE:
            new = None
        if new != current:
            if current is not None:
                self._hold(which, current, False, out)
            if new is not None:
                self._hold(which, new, True, out)
            self._stick[key] = new

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
