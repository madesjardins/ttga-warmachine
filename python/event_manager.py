"""Game event manager for routing player input events to active handlers.

This module provides the GameEventManager class which acts as a central
event bus for all player interactions (speech recognition, QR code detection,
etc.), routing them to whichever game component is currently listening.
"""

from __future__ import annotations

from typing import Callable, Optional

from PySide6 import QtCore


class GameEventManager(QtCore.QObject):
    """Central event router for all player input events.

    Uses a LIFO handler stack so the most recently registered handler takes
    exclusive priority (e.g., an open dialog waiting for a name takes
    precedence over background game logic).  Passive listeners can also
    connect to the re-emitted signals without joining the handler stack.

    Usage::

        # Exclusive modal handler (e.g. recording a name)
        manager.push_speech_handler(my_callback)
        # … later …
        manager.pop_speech_handler(my_callback)

        # Passive listener
        manager.speech_received.connect(my_slot)
    """

    speech_received = QtCore.Signal(str)

    def __init__(self, parent: Optional[QtCore.QObject] = None) -> None:
        super().__init__(parent)
        self._speech_handlers: list[Callable[[str], None]] = []

    # ------------------------------------------------------------------
    # Speech
    # ------------------------------------------------------------------

    def push_speech_handler(self, handler: Callable[[str], None]) -> None:
        """Push a speech handler onto the top of the stack.

        Args:
            handler: Callable that accepts a single ``str`` argument.
        """
        if handler not in self._speech_handlers:
            self._speech_handlers.append(handler)

    def pop_speech_handler(self, handler: Callable[[str], None]) -> None:
        """Remove a speech handler from the stack.

        Args:
            handler: The callable to remove.  No-op if not registered.
        """
        try:
            self._speech_handlers.remove(handler)
        except ValueError:
            pass

    @QtCore.Slot(str)
    def route_speech(self, text: str) -> None:
        """Route a speech result to the top-of-stack handler.

        The topmost handler (most recently registered) receives the text
        exclusively.  The :attr:`speech_received` signal is always emitted
        regardless, so passive listeners always see every result.

        Args:
            text: Recognised speech text.
        """
        self.speech_received.emit(text)
        if self._speech_handlers:
            self._speech_handlers[-1](text)
