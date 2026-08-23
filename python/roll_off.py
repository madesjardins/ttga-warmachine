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

"""First-player roll-off phase for the Warmachine game.

:class:`RollOff` is a voice-driven state machine that walks both players
through a physical dice roll-off: each player rolls a die and reports the
result by voice.  The winner chooses whether to pick table side or turn
order, and the loser gets the complementary choice.

It follows the same architectural pattern as :class:`SetupFlow`:
``QtCore.QObject`` with ``start()``/``stop()``, ``narrate``/``status_changed``
signals, ``_say`` helper (NarrationService-aware with sync fallback), speech
handling via ``event_manager.push_speech_handler``, and LLM intent maps with
deterministic fallback parsing.
"""

from __future__ import annotations

from enum import Enum, auto
from typing import TYPE_CHECKING, Any, Optional

from PySide6 import QtCore

from .setup_flow import words_to_int

if TYPE_CHECKING:
    from ttga.narration_engine import NarrationEngine
    from ttga.narration_service import NarrationService

    from .event_manager import GameEventManager
    from .game_log import GameLog


_NEGATIVE = {"no", "nope", "cancel", "stop", "abort", "quit"}
_FIRST_TURN_KEYWORDS = {"first turn", "go first", "first", "turn order"}
_SIDE_KEYWORDS = {"side", "table side", "table edge", "edge"}
_NORTH_KEYWORDS = {"north", "top"}
_SOUTH_KEYWORDS = {"south", "bottom"}


class RollOffState(Enum):
    """Discrete states of the roll-off conversation."""

    IDLE = auto()
    P1_ROLL = auto()
    P2_ROLL = auto()
    CHOICE_PICK = auto()
    CHOICE_SIDE = auto()
    CHOICE_TURN = auto()
    DONE = auto()


class RollOff(QtCore.QObject):
    """Voice-driven first-player roll-off state machine.

    Signals:
        roll_off_complete(dict): Emitted with
            ``{"first_player": int, "sides": {0: str, 1: str}}`` when the
            roll-off finishes.  ``sides`` maps player index to "north" or
            "south".
        roll_off_cancelled(): Emitted when the player cancels.
        narrate(str): Text the narrator should speak aloud.
        status_changed(str): Short status string for the UI.
    """

    roll_off_complete = QtCore.Signal(dict)
    roll_off_cancelled = QtCore.Signal()
    narrate = QtCore.Signal(str)
    status_changed = QtCore.Signal(str)

    _ROLL_INTENTS = {
        "report_roll": "the player reports the result of their die roll (value = the number rolled)",
        "cancel": "cancel and abandon the roll-off",
    }
    _CHOICE_INTENTS = {
        "choose_turn_order": "the winner wants to choose whether to go first or second",
        "choose_side": "the winner wants to choose their table side",
        "cancel": "cancel and abandon the roll-off",
    }
    _SIDE_INTENTS = {
        "choose_side_north": "the player chooses the north side of the table",
        "choose_side_south": "the player chooses the south side of the table",
        "cancel": "cancel and abandon the roll-off",
    }

    def __init__(
        self,
        event_manager: GameEventManager,
        game_log: GameLog,
        narrator: Any = None,
        narration_engine: Optional[NarrationEngine] = None,
        narration_service: Optional[NarrationService] = None,
        *,
        parent: Optional[QtCore.QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._event_manager = event_manager
        self._log = game_log
        self._narrator = narrator
        self._narration = narration_engine
        self._service = narration_service

        self._state: RollOffState = RollOffState.IDLE
        self._p1_roll: Optional[int] = None
        self._p2_roll: Optional[int] = None
        self._winner: Optional[int] = None
        self._first_player: Optional[int] = None
        self._sides: dict[int, str] = {}
        # Async intent-parsing state (used only when a service is present).
        self._awaiting_intent: bool = False
        self._pending_text: str = ""
        self._intent_req_id: int = -1
        self._service_connected: bool = False

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def state(self) -> RollOffState:
        """Current state of the roll-off conversation."""
        return self._state

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Begin the roll-off conversation."""
        self._state = RollOffState.P1_ROLL
        self._p1_roll = None
        self._p2_roll = None
        self._winner = None
        self._first_player = None
        self._sides = {}
        self._awaiting_intent = False
        if self._service is not None:
            self._service.narrated.connect(self._on_narrated)
            self._service.intent_parsed.connect(self._on_intent_parsed)
            self._service_connected = True
        self._event_manager.push_speech_handler(self._on_speech)
        self._say(
            "The roll-off determines who deploys first. "
            "Player 1, roll a die and report the result.",
        )
        self.status_changed.emit("Roll-off: Player 1 rolls…")

    def stop(self) -> None:
        """Abort the roll-off early without emitting completion."""
        if self._state not in (RollOffState.IDLE, RollOffState.DONE):
            self._event_manager.pop_speech_handler(self._on_speech)
        self._disconnect_service()
        self._state = RollOffState.DONE

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
        """Speak *text*, rephrasing in-character when *use_persona* is True."""
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
        if self._state in (RollOffState.IDLE, RollOffState.DONE):
            return

        player_label = self._current_player_label()
        self._log.player_said(player_label, text)

        allowed = self._allowed_for_state()
        if allowed is None:
            return

        if self._service is not None:
            if self._awaiting_intent:
                return
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
        if self._state in (RollOffState.IDLE, RollOffState.DONE):
            return
        name = None if intent.is_unknown else intent.intent
        value = None if intent.is_unknown else intent.value
        self._dispatch(self._pending_text, name, value)

    def _current_player_label(self) -> str:
        if self._state in (RollOffState.P1_ROLL,):
            return "Player 1"
        if self._state in (RollOffState.P2_ROLL,):
            return "Player 2"
        if self._winner is not None:
            return f"Player {self._winner + 1}"
        return "Player"

    def _allowed_for_state(self) -> Optional[dict]:
        if self._state in (RollOffState.P1_ROLL, RollOffState.P2_ROLL):
            return self._ROLL_INTENTS
        if self._state == RollOffState.CHOICE_PICK:
            return self._CHOICE_INTENTS
        if self._state in (RollOffState.CHOICE_SIDE, RollOffState.CHOICE_TURN):
            return self._SIDE_INTENTS
        return None

    def _dispatch(
        self, text: str, intent: Optional[str], value: Optional[str]
    ) -> None:
        """Route a parsed (or fallback) intent to the current state handler."""
        if self._state == RollOffState.P1_ROLL:
            self._handle_p1_roll(text, intent, value)
        elif self._state == RollOffState.P2_ROLL:
            self._handle_p2_roll(text, intent, value)
        elif self._state == RollOffState.CHOICE_PICK:
            self._handle_choice_pick(text, intent, value)
        elif self._state == RollOffState.CHOICE_SIDE:
            self._handle_choice_side(text, intent, value)
        elif self._state == RollOffState.CHOICE_TURN:
            self._handle_choice_turn(text, intent, value)

    def _parse_sync(
        self, text: str, allowed: dict
    ) -> tuple[Optional[str], Optional[str]]:
        """Run NLU synchronously when the engine is active."""
        if self._narration is None:
            return None, None
        parsed = self._narration.parse_intent(text.strip(), allowed)
        if parsed.is_unknown:
            return None, None
        return parsed.intent, parsed.value

    # ------------------------------------------------------------------
    # State handlers
    # ------------------------------------------------------------------

    def _handle_p1_roll(
        self, text: str, intent: Optional[str], value: Optional[str]
    ) -> None:
        if intent == "cancel" or text.strip().lower() in _NEGATIVE:
            self._cancel()
            return

        roll = None
        if intent == "report_roll" and value:
            roll = words_to_int(value)
        if roll is None:
            roll = words_to_int(text)

        if roll is None or not (1 <= roll <= 6):
            self._say(
                "Please report a die result between one and six."
            )
            return

        self._p1_roll = roll
        self._log.system(f"Player 1 rolled a {roll}.")
        self._state = RollOffState.P2_ROLL
        self._say(
            f"Player 1 rolled a {roll}. Player 2, roll a die and report the result.",
        )
        self.status_changed.emit("Roll-off: Player 2 rolls…")

    def _handle_p2_roll(
        self, text: str, intent: Optional[str], value: Optional[str]
    ) -> None:
        if intent == "cancel" or text.strip().lower() in _NEGATIVE:
            self._cancel()
            return

        roll = None
        if intent == "report_roll" and value:
            roll = words_to_int(value)
        if roll is None:
            roll = words_to_int(text)

        if roll is None or not (1 <= roll <= 6):
            self._say(
                "Please report a die result between one and six."
            )
            return

        self._p2_roll = roll
        self._log.system(f"Player 2 rolled a {roll}.")
        self._compare_rolls()

    def _compare_rolls(self) -> None:
        """Compare rolls: tie re-rolls, winner enters CHOICE_PICK."""
        p1 = self._p1_roll
        p2 = self._p2_roll
        assert p1 is not None and p2 is not None

        if p1 == p2:
            self._log.system("Tie! Rolling again.")
            self._say(
                f"Both players rolled a {p1}. It is a tie. "
                "Roll again. Player 1, roll a die and report the result.",
            )
            self._p1_roll = None
            self._p2_roll = None
            self._state = RollOffState.P1_ROLL
            self.status_changed.emit("Roll-off: tie — re-roll…")
            return

        self._winner = 0 if p1 > p2 else 1
        loser = 1 if self._winner == 0 else 0
        winner_roll = p1 if self._winner == 0 else p2
        loser_roll = p2 if self._winner == 0 else p1
        self._log.system(
            f"Player {self._winner + 1} wins the roll-off "
            f"({winner_roll} vs {loser_roll})."
        )
        self._state = RollOffState.CHOICE_PICK
        self._say(
            f"Player {self._winner + 1} wins the roll-off with {winner_roll} "
            f"against {loser_roll}. Do you wish to choose your table side, "
            f"or choose to go first?",
        )
        self.status_changed.emit(
            f"Roll-off: Player {self._winner + 1} chooses…"
        )

    def _handle_choice_pick(
        self, text: str, intent: Optional[str], value: Optional[str]
    ) -> None:
        if intent == "cancel" or text.strip().lower() in _NEGATIVE:
            self._cancel()
            return

        lower = text.strip().lower()
        winner = self._winner
        loser = 1 if winner == 0 else 0

        chose_side = intent == "choose_side" or any(
            kw in lower for kw in _SIDE_KEYWORDS
        )
        chose_turn = intent == "choose_turn_order" or any(
            kw in lower for kw in _FIRST_TURN_KEYWORDS
        )

        if chose_side and not chose_turn:
            # Winner picks a side; loser gets first turn.
            self._first_player = loser
            self._state = RollOffState.CHOICE_SIDE
            self._say(
                f"Player {winner + 1}, which side of the table do you prefer? "
                "North or south?",
            )
            self.status_changed.emit(
                f"Roll-off: Player {winner + 1} picks a side…"
            )
        elif chose_turn and not chose_side:
            # Winner picks turn order; loser picks a side.
            self._state = RollOffState.CHOICE_TURN
            self._say(
                f"Player {winner + 1}, do you wish to deploy first or second?",
            )
            self.status_changed.emit(
                f"Roll-off: Player {winner + 1} picks turn order…"
            )
        else:
            self._say(
                "Please say 'side' to choose a table side, "
                "or 'first turn' to choose turn order."
            )

    def _handle_choice_side(
        self, text: str, intent: Optional[str], value: Optional[str]
    ) -> None:
        if intent == "cancel" or text.strip().lower() in _NEGATIVE:
            self._cancel()
            return

        lower = text.strip().lower()
        winner = self._winner
        loser = 1 if winner == 0 else 0

        chose_north = intent == "choose_side_north" or any(
            kw in lower for kw in _NORTH_KEYWORDS
        )
        chose_south = intent == "choose_side_south" or any(
            kw in lower for kw in _SOUTH_KEYWORDS
        )

        if chose_north and not chose_south:
            self._sides[winner] = "north"
            self._sides[loser] = "south"
        elif chose_south and not chose_north:
            self._sides[winner] = "south"
            self._sides[loser] = "north"
        else:
            self._say("Please say 'north' or 'south'.")
            return

        self._finish()

    def _handle_choice_turn(
        self, text: str, intent: Optional[str], value: Optional[str]
    ) -> None:
        if intent == "cancel" or text.strip().lower() in _NEGATIVE:
            self._cancel()
            return

        lower = text.strip().lower()
        winner = self._winner
        loser = 1 if winner == 0 else 0

        # Determine if winner wants to go first or second.
        wants_first = "first" in lower and "second" not in lower
        wants_second = "second" in lower

        if not wants_first and not wants_second:
            # Also accept affirmative/negative as first/second.
            if lower in {"yes", "yeah", "yep", "ok", "okay", "confirm"}:
                wants_first = True
            elif lower in {"no", "nope"}:
                wants_second = True
            else:
                self._say("Please say 'first' or 'second'.")
                return

        if wants_first:
            self._first_player = winner
        else:
            self._first_player = loser

        # Loser picks a side.
        self._state = RollOffState.CHOICE_SIDE
        self._say(
            f"Player {loser + 1}, which side of the table do you prefer? "
            "North or south?",
        )
        self.status_changed.emit(
            f"Roll-off: Player {loser + 1} picks a side…"
        )

    # ------------------------------------------------------------------
    # Completion
    # ------------------------------------------------------------------

    def _finish(self) -> None:
        self._event_manager.pop_speech_handler(self._on_speech)
        self._disconnect_service()
        self._state = RollOffState.DONE
        result = {
            "first_player": self._first_player,
            "sides": dict(self._sides),
        }
        self._log.system(
            f"Roll-off complete: first_player={result['first_player']}, "
            f"sides={result['sides']}."
        )
        self.roll_off_complete.emit(result)

    def _cancel(self) -> None:
        self._say("Roll-off cancelled.")
        self._event_manager.pop_speech_handler(self._on_speech)
        self._disconnect_service()
        self._state = RollOffState.DONE
        self.roll_off_cancelled.emit()
