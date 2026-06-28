# Copyright 2026 Marc-Antoine Desjardins
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Conversational new-game setup for the Warmachine game.

:class:`SetupFlow` is a deterministic state machine that walks the player
through configuring a new match by voice (game mode -> points -> confirm),
before army creation begins. It uses the core ``NarrationEngine`` for both
roles: :meth:`~ttga.narration_engine.NarrationEngine.phrase` to ask questions
in-character and ``parse_intent`` to interpret answers.

It is LLM-optional: when the engine is inactive, ``parse_intent`` returns
``unknown`` and the flow falls back to deterministic keyword / number parsing,
so setup works identically without an LLM.
"""

from __future__ import annotations

import re
from enum import Enum, auto
from typing import TYPE_CHECKING, Any, Optional

from PySide6 import QtCore

if TYPE_CHECKING:
    from ttga.narration_engine import NarrationEngine
    from ttga.narration_service import NarrationService

    from .event_manager import GameEventManager
    from .game_log import GameLog


# Supported game modes: canonical key -> spoken keywords that select it.
_GAME_MODES: dict[str, list[str]] = {
    "single_match": ["single match", "single", "one match", "match", "standard"],
}

# Sensible bounds for a points value (Warmachine army sizes).
_MIN_POINTS = 1
_MAX_POINTS = 500

# Words for deterministic number parsing (no-LLM fallback).
_NUMBER_WORDS: dict[str, int] = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
_TENS_WORDS: dict[str, int] = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
    "seventy": 70, "eighty": 80, "ninety": 90,
}

_AFFIRMATIVE = {"yes", "yeah", "yep", "confirm", "correct", "start", "go", "begin", "ok", "okay"}
_NEGATIVE = {"no", "nope", "cancel", "stop", "abort", "quit"}
_RESTART = {"restart", "redo", "start over", "again", "change"}


class SetupState(Enum):
    """Discrete states of the setup conversation."""

    IDLE = auto()
    GAME_MODE = auto()
    POINTS = auto()
    CONFIRM = auto()
    DONE = auto()


def words_to_int(text: str) -> Optional[int]:
    """Parse an integer from digits or spelled-out English number words.

    Handles digits ("75"), simple words ("fifty"), and tens+units
    ("seventy five", "seventy-five"). Returns the first value found.

    Args:
        text: Free text possibly containing a number.

    Returns:
        The parsed integer, or ``None`` if no number was found.
    """
    # Prefer explicit digits.
    digit_match = re.search(r"\d+", text)
    if digit_match:
        return int(digit_match.group(0))

    tokens = re.split(r"[\s-]+", text.lower())
    total: Optional[int] = None
    for tok in tokens:
        if tok in _TENS_WORDS:
            total = (total or 0) + _TENS_WORDS[tok]
        elif tok in _NUMBER_WORDS:
            total = (total or 0) + _NUMBER_WORDS[tok]
    return total


class SetupFlow(QtCore.QObject):
    """Voice-driven new-game setup state machine.

    Signals:
        setup_complete(dict): Emitted with the final config
            ``{"game_mode": str, "points": int}`` when setup finishes.
        setup_cancelled(): Emitted when the player cancels setup.
        narrate(str): Text the narrator should speak aloud.
        status_changed(str): Short status string for the UI.
    """

    setup_complete = QtCore.Signal(dict)
    setup_cancelled = QtCore.Signal()
    narrate = QtCore.Signal(str)
    status_changed = QtCore.Signal(str)

    # Allowed intents per step (name -> description) for NLU.
    _MODE_INTENTS = {
        "set_game_mode": "the game mode to play (value = the mode name spoken)",
        "cancel": "cancel and abandon setup",
    }
    _POINTS_INTENTS = {
        "set_points": "the army points size for the match (value = the number)",
        "cancel": "cancel and abandon setup",
    }
    _CONFIRM_INTENTS = {
        "confirm": "the player confirms the settings and wants to start",
        "restart": "the player wants to change the settings and start over",
        "cancel": "cancel and abandon setup",
    }

    def __init__(
        self,
        event_manager: GameEventManager,
        game_log: GameLog,
        narrator: Any = None,
        narration_engine: Optional[NarrationEngine] = None,
        narration_service: Optional[NarrationService] = None,
        *,
        default_points: int = 75,
        parent: Optional[QtCore.QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._event_manager = event_manager
        self._log = game_log
        self._narrator = narrator
        self._narration = narration_engine
        self._service = narration_service
        self._default_points = default_points

        self._state: SetupState = SetupState.IDLE
        self._game_mode: Optional[str] = None
        self._points: Optional[int] = None
        # Async intent-parsing state (used only when a service is present).
        self._awaiting_intent: bool = False
        self._pending_text: str = ""
        self._intent_req_id: int = -1
        self._service_connected: bool = False

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def state(self) -> SetupState:
        """Current state of the setup conversation."""
        return self._state

    @property
    def config(self) -> dict:
        """The setup config gathered so far."""
        return {"game_mode": self._game_mode, "points": self._points}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Begin the setup conversation."""
        self._state = SetupState.GAME_MODE
        self._game_mode = None
        self._points = None
        self._awaiting_intent = False
        if self._service is not None:
            self._service.narrated.connect(self._on_narrated)
            self._service.intent_parsed.connect(self._on_intent_parsed)
            self._service_connected = True
        self._event_manager.push_speech_handler(self._on_speech)
        self._say(
            "Let us prepare for battle. Which game mode shall we play? "
            "You can say single match.",
            use_persona=True,
        )
        self.status_changed.emit("Setup: choose a game mode…")

    def stop(self) -> None:
        """Abort the setup flow early without emitting completion."""
        if self._state not in (SetupState.IDLE, SetupState.DONE):
            self._event_manager.pop_speech_handler(self._on_speech)
        self._disconnect_service()
        self._state = SetupState.DONE

    def _disconnect_service(self) -> None:
        if self._service is not None and self._service_connected:
            try:
                self._service.narrated.disconnect(self._on_narrated)
                self._service.intent_parsed.disconnect(self._on_intent_parsed)
            except (RuntimeError, TypeError):
                pass
            self._service_connected = False

    # ------------------------------------------------------------------
    # Narrator helper
    # ------------------------------------------------------------------

    def _say(self, text: str, *, use_persona: bool = False) -> None:
        """Speak *text*, rephrasing in-character when *use_persona* is True.

        With a :class:`NarrationService`, phrasing and TTS run off the main
        thread and logging happens when ``narrated`` fires. Otherwise this is
        the synchronous phrase/log/play path with ``text`` as the fallback.

        Args:
            text: The text to speak.
            use_persona: When True, rephrase via the LLM persona. When False
                (default), speak the text verbatim.
        """
        if self._service is not None:
            self._service.speak(text, use_persona=use_persona)
            return
        spoken = text
        if use_persona and self._narration is not None:
            spoken = self._narration.phrase(text)
        self._log.narrate(spoken)
        if self._narrator is not None:
            try:
                self._narrator.synthesize_and_play(spoken)
            except Exception:
                pass
        self.narrate.emit(spoken)

    @QtCore.Slot(str)
    def _on_narrated(self, text: str) -> None:
        """Log and re-emit narration produced asynchronously by the service."""
        self._log.narrate(text)
        self.narrate.emit(text)

    # ------------------------------------------------------------------
    # Speech handling
    # ------------------------------------------------------------------

    def _on_speech(self, text: str) -> None:
        if self._state in (SetupState.IDLE, SetupState.DONE):
            return
        self._log.player_said("Setup", text)

        allowed = self._allowed_for_state()
        if allowed is None:
            return

        if self._service is not None:
            if self._awaiting_intent:
                return  # Ignore overlapping speech while a parse is in flight.
            self._awaiting_intent = True
            self._pending_text = text
            self._intent_req_id = self._service.parse_intent_async(
                text.strip(), allowed
            )
            return

        intent, value = self._parse_sync(text, allowed)
        self._dispatch(text, intent, value)

    @QtCore.Slot(int, object)
    def _on_intent_parsed(self, req_id: int, intent: Any) -> None:
        """Continue handling once an async intent parse completes."""
        if self._service is None or req_id != self._intent_req_id:
            return
        self._awaiting_intent = False
        if self._state in (SetupState.IDLE, SetupState.DONE):
            return
        name = None if intent.is_unknown else intent.intent
        value = None if intent.is_unknown else intent.value
        self._dispatch(self._pending_text, name, value)

    def _allowed_for_state(self) -> Optional[dict]:
        """Return the allowed-intent map for the current state, or ``None``."""
        if self._state == SetupState.GAME_MODE:
            return self._MODE_INTENTS
        if self._state == SetupState.POINTS:
            return self._POINTS_INTENTS
        if self._state == SetupState.CONFIRM:
            return self._CONFIRM_INTENTS
        return None

    def _dispatch(self, text: str, intent: Optional[str], value: Optional[str]) -> None:
        """Route a parsed (or fallback) intent to the current state handler."""
        if self._state == SetupState.GAME_MODE:
            self._handle_game_mode(text, intent, value)
        elif self._state == SetupState.POINTS:
            self._handle_points(text, intent, value)
        elif self._state == SetupState.CONFIRM:
            self._handle_confirm(text, intent, value)

    def _parse_sync(self, text: str, allowed: dict) -> tuple[Optional[str], Optional[str]]:
        """Run NLU synchronously when the engine is active; ``(intent, value)``.

        Returns ``(None, None)`` when no engine is configured or the result is
        unknown, signalling the caller to use deterministic parsing.
        """
        if self._narration is None:
            return None, None
        parsed = self._narration.parse_intent(text.strip(), allowed)
        if parsed.is_unknown:
            return None, None
        return parsed.intent, parsed.value

    # ------------------------------------------------------------------
    # State handlers
    # ------------------------------------------------------------------

    def _handle_game_mode(
        self, text: str, intent: Optional[str], value: Optional[str]
    ) -> None:
        if intent == "cancel" or text.strip().lower() in _NEGATIVE:
            self._cancel()
            return

        # Prefer the LLM-extracted value, then the raw utterance; the mode is
        # always validated deterministically against the known modes.
        mode = None
        if intent == "set_game_mode" and value:
            mode = self._resolve_game_mode(value)
        if mode is None:
            mode = self._resolve_game_mode(text)

        if mode is None:
            self._say(
                "I did not catch the game mode. Please say single match."
            )
            return

        self._game_mode = mode
        self._state = SetupState.POINTS
        self._say(
            f"Single match it is. How many points shall each army field? "
            f"For example, fifty or seventy five.",
            use_persona=True,
        )
        self.status_changed.emit("Setup: choose army points…")

    def _handle_points(
        self, text: str, intent: Optional[str], value: Optional[str]
    ) -> None:
        if intent == "cancel" or text.strip().lower() in _NEGATIVE:
            self._cancel()
            return

        points = None
        if intent == "set_points" and value:
            points = words_to_int(value)
        if points is None:
            points = words_to_int(text)

        if points is None or not (_MIN_POINTS <= points <= _MAX_POINTS):
            self._say(
                "I need a points value between one and five hundred. "
                "Please say a number, like seventy five."
            )
            return

        self._points = points
        self._state = SetupState.CONFIRM
        self._say(
            f"A single match at {points} points. Shall we begin? "
            f"Say yes to start, or restart to change the settings.",
            use_persona=True,
        )
        self.status_changed.emit("Setup: confirm to begin…")

    def _handle_confirm(
        self, text: str, intent: Optional[str], value: Optional[str]
    ) -> None:
        lower = text.strip().lower()

        is_restart = intent == "restart" or any(w in lower for w in _RESTART)
        is_cancel = intent == "cancel" or lower in _NEGATIVE
        is_confirm = intent == "confirm" or lower in _AFFIRMATIVE

        # Restart and cancel take precedence over a stray affirmative match.
        if is_restart:
            self._state = SetupState.GAME_MODE
            self._game_mode = None
            self._points = None
            self._say(
                "Very well, let us start over. Which game mode shall we play? "
                "You can say single match.",
                use_persona=True,
            )
            self.status_changed.emit("Setup: choose a game mode…")
            return
        if is_cancel:
            self._cancel()
            return
        if is_confirm:
            self._finish()
            return

        self._say("Please say yes to begin, restart to change, or cancel.")

    # ------------------------------------------------------------------
    # Resolution helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_game_mode(text: str) -> Optional[str]:
        """Map spoken text to a known game-mode key, or ``None``."""
        lower = text.strip().lower()
        for key, keywords in _GAME_MODES.items():
            if lower == key:
                return key
            for kw in keywords:
                if kw in lower:
                    return key
        return None

    # ------------------------------------------------------------------
    # Completion
    # ------------------------------------------------------------------

    def _finish(self) -> None:
        self._event_manager.pop_speech_handler(self._on_speech)
        self._disconnect_service()
        self._state = SetupState.DONE
        config = {"game_mode": self._game_mode, "points": self._points}
        self._log.system(
            f"Setup complete: mode={self._game_mode}, points={self._points}."
        )
        self.setup_complete.emit(config)

    def _cancel(self) -> None:
        self._say("Setup cancelled.")
        self._event_manager.pop_speech_handler(self._on_speech)
        self._disconnect_service()
        self._state = SetupState.DONE
        self.setup_cancelled.emit()
