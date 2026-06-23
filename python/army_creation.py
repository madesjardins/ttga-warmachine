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

"""Army creation phase for the Warmachine game.

This module defines :class:`ArmyCreation`, a reusable object that walks two
players through selecting models from the database by voice.  It is designed
to be used inside a :class:`Match` but can also be invoked standalone.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from PySide6 import QtCore

if TYPE_CHECKING:
    from ttga.narration_engine import NarrationEngine
    from ttga.narration_service import NarrationService

    from .event_manager import GameEventManager
    from .game_log import GameLog
    from .model_database import ModelDatabase
    from .model_stat_card import ModelStatCard


class ArmyCreation(QtCore.QObject):
    """Manages the army-building phase for two players.

    Signals:
        model_added(int, str, int): ``(player_index, model_name,
            required_qr)`` – a model/unit was added and is awaiting QR
            registration.
        qr_progress(int, list, int): ``(player_index, codes, required)`` – QR
            registration progress (collected code values) for the current
            model/unit.
        model_cancelled(int): ``(player_index)`` – the in-progress model/unit
            was cancelled and should be removed from the list.
        phase_completed(): Both armies are complete.
        narrate(str): Text the narrator should speak aloud.
        status_changed(str): Short status string for the UI.
    """

    model_added = QtCore.Signal(int, str, int)
    qr_progress = QtCore.Signal(int, list, int)
    model_cancelled = QtCore.Signal(int)
    phase_completed = QtCore.Signal()
    narrate = QtCore.Signal(str)
    status_changed = QtCore.Signal(str)

    # Allowed intents (name -> description) for the model-adding step, supplied
    # to the NarrationEngine for NLU. Python remains authoritative: an extracted
    # model name is always validated against the database via ``_find_model``.
    _ADD_MODEL_INTENTS = {
        "add_model": (
            "the player named a model or unit to add to their army "
            "(value = the spoken model or unit name)"
        ),
        "army_completed": (
            "the player is finished and wants to complete their army"
        ),
    }

    def __init__(
        self,
        db: ModelDatabase,
        event_manager: GameEventManager,
        game_log: GameLog,
        narrator: Any = None,
        narration_engine: Optional[NarrationEngine] = None,
        narration_service: Optional[NarrationService] = None,
        parent: Optional[QtCore.QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._db = db
        self._event_manager = event_manager
        self._log = game_log
        self._narrator = narrator
        self._narration = narration_engine
        self._service = narration_service
        # Async intent-parsing state (used only when a service is present).
        self._awaiting_intent: bool = False
        self._pending_text: str = ""
        self._intent_req_id: int = -1
        self._armies: list[list[ModelStatCard]] = [[], []]
        # QR codes assigned to each army entry, parallel to ``_armies``.
        self._qr_codes: list[list[list[str]]] = [[], []]
        self._current_player: int = 0
        self._active: bool = False

        # QR-collection state for the model currently being added.
        self._collecting: bool = False
        self._pending_card: Optional[ModelStatCard] = None
        self._required_qr: int = 0
        self._collected_qr: list[str] = []
        # QR codes already assigned anywhere in the match (prevents reuse).
        self._used_qr: set[str] = set()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def armies(self) -> list[list[ModelStatCard]]:
        """The two army lists built so far."""
        return self._armies

    @property
    def qr_codes(self) -> list[list[list[str]]]:
        """QR codes assigned to each army entry, parallel to :attr:`armies`."""
        return self._qr_codes

    @property
    def current_player(self) -> int:
        """Index (0 or 1) of the player currently adding models."""
        return self._current_player

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Begin the army creation phase for Player 1."""
        self._active = True
        self._current_player = 0
        self._collecting = False
        self._pending_card = None
        self._collected_qr = []
        self._used_qr = set()
        self._awaiting_intent = False
        if self._service is not None:
            self._service.narrated.connect(self._on_narrated)
            self._service.intent_parsed.connect(self._on_intent_parsed)
        self._event_manager.push_speech_handler(self._on_speech)
        self._say("Army creation begins.")
        self._prompt_next_model()

    def stop(self) -> None:
        """Abort the army creation phase early."""
        self._active = False
        if self._collecting:
            self._event_manager.pop_detection_handler(self._on_detection)
            self._collecting = False
        if self._service is not None:
            try:
                self._service.narrated.disconnect(self._on_narrated)
                self._service.intent_parsed.disconnect(self._on_intent_parsed)
            except (RuntimeError, TypeError):
                pass
        self._event_manager.pop_speech_handler(self._on_speech)

    # ------------------------------------------------------------------
    # Narrator helper
    # ------------------------------------------------------------------

    def _say(self, text: str) -> None:
        """Speak *text*, rephrasing in-character when an LLM is available.

        With a :class:`NarrationService`, phrasing and TTS run off the main
        thread (streamed sentence by sentence) and logging happens when the
        :attr:`NarrationService.narrated` signal fires. Otherwise this performs
        the synchronous phrase/log/play path, with the scripted ``text`` as the
        fallback.
        """
        if self._service is not None:
            self._service.speak(text)
            return

        spoken = text
        if self._narration is not None:
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
    # Prompting
    # ------------------------------------------------------------------

    def _prompt_next_model(self) -> None:
        player_label = f"Player {self._current_player + 1}"
        has_models = len(self._armies[self._current_player]) > 0
        if has_models:
            text = (
                f"{player_label}, speak the name of the next model or unit, "
                "or say 'army completed' when the army is completed."
            )
        else:
            text = (
                f"{player_label}, speak the name of the next model or unit."
            )
        self._say(text)
        self.status_changed.emit(f"Waiting for {player_label}…")

    # ------------------------------------------------------------------
    # Speech handler
    # ------------------------------------------------------------------

    def _on_speech(self, text: str) -> None:
        if not self._active:
            return

        player_label = f"Player {self._current_player + 1}"
        self._log.player_said(player_label, text)

        lower = text.strip().lower()

        # --- While collecting QR codes a new model cannot be added ---
        if self._collecting:
            if lower == "cancel":
                self._cancel_qr_collection()
            else:
                self._say(
                    "Please complete current model or unit QR registration "
                    "before adding another model or unit."
                )
            return

        # --- Intent parsing (NLU) with deterministic fallback ---
        # With a service, parse off the main thread and continue when the
        # result arrives. Otherwise parse synchronously (or fall back to the
        # exact-string logic when no LLM is available).
        context = {
            "player": player_label,
            "models_added": len(self._armies[self._current_player]),
        }
        if self._service is not None:
            if self._awaiting_intent:
                return  # Ignore overlapping speech while a parse is in flight.
            self._awaiting_intent = True
            self._pending_text = text
            self._intent_req_id = self._service.parse_intent_async(
                text.strip(), self._ADD_MODEL_INTENTS, context=context
            )
            return

        intent_name: Optional[str] = None
        intent_value: Optional[str] = None
        if self._narration is not None:
            parsed = self._narration.parse_intent(
                text.strip(), self._ADD_MODEL_INTENTS, context=context
            )
            if not parsed.is_unknown:
                intent_name = parsed.intent
                intent_value = parsed.value

        self._apply_add_model_intent(text, intent_name, intent_value)

    @QtCore.Slot(int, object)
    def _on_intent_parsed(self, req_id: int, intent: Any) -> None:
        """Continue the speech handling once an async intent parse completes."""
        if self._service is None or req_id != self._intent_req_id:
            return
        self._awaiting_intent = False
        if not self._active or self._collecting:
            return
        intent_name = None if intent.is_unknown else intent.intent
        intent_value = None if intent.is_unknown else intent.value
        self._apply_add_model_intent(self._pending_text, intent_name, intent_value)

    def _apply_add_model_intent(
        self, text: str, intent_name: Optional[str], intent_value: Optional[str]
    ) -> None:
        """Act on a parsed (or fallback) add-model / army-completed intent."""
        lower = text.strip().lower()

        # --- "army completed" (LLM intent or exact-string fallback) ---
        if intent_name == "army_completed" or (
            intent_name is None and lower == "army completed"
        ):
            self._on_army_completed()
            return

        # --- Model lookup (Python stays authoritative over the LLM's value) ---
        card = None
        if intent_name == "add_model" and intent_value:
            card = self._find_model(intent_value.strip())
        if card is None:
            card = self._find_model(text.strip())
        if card is None:
            self._say(
                f"Model '{text}' was not found in the database. "
                "Please try again."
            )
            return

        self._begin_qr_collection(card)

    # ------------------------------------------------------------------
    # QR code collection
    # ------------------------------------------------------------------

    def _begin_qr_collection(self, card: ModelStatCard) -> None:
        """Add *card* to the army and start collecting its QR codes."""
        player_label = f"Player {self._current_player + 1}"
        trooper_count = (
            sum(max(1, t.quantity) for t in card.troopers)
            if card.troopers else 0
        )
        required = trooper_count if trooper_count > 0 else 1

        self._pending_card = card
        self._required_qr = required
        self._collected_qr = []
        self._collecting = True

        # Add the model/unit immediately so it shows in the army list, with
        # its QR registration starting at 0/required.
        self._armies[self._current_player].append(card)
        self._qr_codes[self._current_player].append([])
        self.model_added.emit(self._current_player, card.name, required)

        self._event_manager.push_detection_handler(self._on_detection)

        if trooper_count > 0:
            self._say(
                f"Found {card.name}. Please present {required} QR codes for "
                "the troopers in this unit, one at a time."
            )
        else:
            self._say(
                f"Found {card.name}. Please present the QR code for this "
                "model."
            )
        self.status_changed.emit(
            f"{player_label}: {card.name} 0/{required} QRs."
        )

    @staticmethod
    def _qr_sort_key(code: str):
        """Sort key that orders numeric QR codes by value, others by text."""
        try:
            return (0, int(code))
        except (TypeError, ValueError):
            return (1, code)

    def _on_detection(self, detections: list, zone_name: str) -> None:
        """Accumulate newly seen, unused QR codes for the pending model.

        Never collects more than ``required`` codes; when more are presented
        at once, the numerically smallest are kept.
        """
        if not self._collecting:
            return

        remaining = self._required_qr - len(self._collected_qr)
        if remaining <= 0:
            self._finish_qr_collection()
            return

        # Gather unique, unused candidate codes from this frame.
        candidates: list[str] = []
        seen: set[str] = set()
        for det in detections:
            msg = (getattr(det, "message", "") or "").strip()
            if not msg:
                continue
            if (
                msg in self._used_qr
                or msg in self._collected_qr
                or msg in seen
            ):
                continue
            seen.add(msg)
            candidates.append(msg)

        if not candidates:
            return

        # When more are presented than needed, keep the smallest numerically.
        candidates.sort(key=self._qr_sort_key)
        accepted = candidates[:remaining]
        if not accepted:
            return

        self._collected_qr.extend(accepted)
        # Keep the army entry's code list in sync with what was collected.
        self._qr_codes[self._current_player][-1] = list(self._collected_qr)

        player_label = f"Player {self._current_player + 1}"
        count = len(self._collected_qr)
        pending_name = self._pending_card.name if self._pending_card else "?"
        self.qr_progress.emit(
            self._current_player, list(self._collected_qr), self._required_qr
        )
        self.status_changed.emit(
            f"{player_label}: {pending_name} {count}/{self._required_qr} QRs."
        )
        self._log.system(
            f"Registered QR code {count} of {self._required_qr} "
            f"for {pending_name}."
        )

        if count >= self._required_qr:
            self._finish_qr_collection()

    def _finish_qr_collection(self) -> None:
        """Finalise QR registration for the fully-registered model/unit."""
        if not self._collecting:
            return
        self._event_manager.pop_detection_handler(self._on_detection)
        self._collecting = False

        card = self._pending_card
        codes = list(self._collected_qr)
        self._pending_card = None
        self._collected_qr = []
        if card is None:
            return

        self._used_qr.update(codes)
        self._qr_codes[self._current_player][-1] = codes

        n = len(codes)
        self._say(
            f"{card.name} is fully registered with {n} "
            f"QR {'code' if n == 1 else 'codes'}."
        )

        QtCore.QTimer.singleShot(500, self._prompt_next_model)

    def _cancel_qr_collection(self) -> None:
        """Remove the in-progress model/unit without registering it."""
        if not self._collecting:
            return
        self._event_manager.pop_detection_handler(self._on_detection)
        self._collecting = False

        card = self._pending_card
        self._pending_card = None
        self._collected_qr = []

        # Roll back the entry that was added in _begin_qr_collection.
        if self._armies[self._current_player]:
            self._armies[self._current_player].pop()
        if self._qr_codes[self._current_player]:
            self._qr_codes[self._current_player].pop()
        self.model_cancelled.emit(self._current_player)

        name = card.name if card is not None else "the model"
        self._say(f"Cancelled adding {name}.")
        QtCore.QTimer.singleShot(500, self._prompt_next_model)

    # ------------------------------------------------------------------
    # Army completed
    # ------------------------------------------------------------------

    def _on_army_completed(self) -> None:
        player_label = f"Player {self._current_player + 1}"
        count = len(self._armies[self._current_player])
        self._say(
            f"{player_label}'s army is complete with {count} "
            f"{'entry' if count == 1 else 'entries'}."
        )

        if self._current_player == 0:
            self._current_player = 1
            self._prompt_next_model()
        else:
            self._say(
                "Both armies are now complete. Army creation is finished."
            )
            self._active = False
            self._event_manager.pop_speech_handler(self._on_speech)
            self.phase_completed.emit()

    # ------------------------------------------------------------------
    # Model lookup
    # ------------------------------------------------------------------

    @staticmethod
    def _match_name(spoken: str, candidate: str) -> bool:
        return spoken.lower() == candidate.lower()

    def _find_model(self, spoken_text: str) -> Optional[ModelStatCard]:
        """Find a model whose name or vocal_names match *spoken_text*."""
        for model in self._db.all_models():
            if self._match_name(spoken_text, model.name):
                return model
            for vn in model.vocal_names:
                if self._match_name(spoken_text, vn):
                    return model
        return None
