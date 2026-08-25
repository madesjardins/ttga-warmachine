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

"""Deployment phase for the Warmachine game.

:class:`Deployment` is a voice- and AR-driven state machine that walks both
players through placing their models on the table.  It uses projector overlays
to draw deployment zones and QR code detections to track each model's position
in real time, validating that models are inside their assigned zone.

It follows the same architectural pattern as :class:`ArmyCreation`:
``QtCore.QObject`` with ``start()``/``stop()``, ``narrate``/``status_changed``
signals, ``_say`` helper, speech handling via
``event_manager.push_speech_handler``, detection handling via
``event_manager.push_detection_handler``, and LLM intent maps with
deterministic fallback parsing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING, Any, Optional

import cv2
import numpy as np
from PySide6 import QtCore

from .model_stat_card import ModelAdvantage, ModelStatCard

if TYPE_CHECKING:
    from ttga.narration_engine import NarrationEngine
    from ttga.narration_service import NarrationService
    from ttga.qr_detection import QRDetection
    from ttga.zone import Zone

    from .event_manager import GameEventManager
    from .game_log import GameLog


_NEGATIVE = {"no", "nope", "cancel", "stop", "abort", "quit"}
_COMPLETE_KEYWORDS = {"deployment complete", "deploy complete", "done", "finished", "complete"}

_ADVANCE_DEPLOY_BONUS = 3.0

# Overlay colours (BGRA).
_P1_ZONE_COLOR = (255, 100, 100, 40)       # translucent blue
_P1_BORDER_COLOR = (255, 80, 80, 200)      # solid blue
_P2_ZONE_COLOR = (100, 100, 255, 40)       # translucent red
_P2_BORDER_COLOR = (80, 80, 255, 200)      # solid red
_MARKER_IN_ZONE = (100, 255, 100, 220)     # green
_MARKER_OUT_ZONE = (100, 100, 255, 220)    # red
_MARKER_RADIUS = 6


class DeploymentState(Enum):
    """Discrete states of the deployment phase."""

    IDLE = auto()
    ANNOUNCE = auto()
    TRACKING = auto()
    DONE = auto()


@dataclass
class ModelDeploymentStatus:
    """Tracks the deployment state of a single model/unit entry.

    Attributes:
        card: The model's stat card.
        qr_codes: QR code messages assigned to this entry.
        position_in: Latest position in inches (game coords), or None.
        in_zone: Whether the model is currently inside its deployment zone.
        advance_deploy: Whether this model has Advance Deployment.
    """

    card: ModelStatCard
    qr_codes: list[str]
    position_in: Optional[tuple[float, float]] = None
    in_zone: bool = False
    advance_deploy: bool = False


class Deployment(QtCore.QObject):
    """AR-assisted deployment phase for two players.

    Signals:
        model_position_updated(int, str, tuple, bool):
            ``(player_index, model_name, (x_in, y_in), in_zone)`` – a model's
            position was updated from a QR detection.
        all_placed_changed(int, bool):
            ``(player, all_models_in_zone)`` – the overall placement status
            for a player changed.
        phase_completed(): Both players have finished deploying.
        deployment_cancelled(): The deployment was cancelled.
        narrate(str): Text the narrator should speak aloud.
        status_changed(str): Short status string for the UI.
    """

    model_position_updated = QtCore.Signal(int, str, object, bool)
    all_placed_changed = QtCore.Signal(int, bool)
    phase_completed = QtCore.Signal()
    deployment_cancelled = QtCore.Signal()
    narrate = QtCore.Signal(str)
    status_changed = QtCore.Signal(str)

    _COMPLETE_INTENTS = {
        "deployment_complete": "the player has finished deploying and wants to complete",
        "cancel": "cancel and abandon deployment",
    }

    def __init__(
        self,
        armies: list[list[ModelStatCard]],
        qr_codes: list[list[list[str]]],
        sides: dict[int, str],
        first_player: int,
        deployment_depth_in: float,
        zone: Zone,
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
        self._sides = sides
        self._first_player = first_player
        self._deployment_depth = deployment_depth_in
        self._zone = zone

        self._state: DeploymentState = DeploymentState.IDLE
        self._current_player: int = first_player
        self._active: bool = False

        # Build per-player model deployment statuses.
        self._statuses: list[list[ModelDeploymentStatus]] = []
        for p_idx, army in enumerate(armies):
            player_statuses = []
            for m_idx, card in enumerate(army):
                codes = (
                    qr_codes[p_idx][m_idx]
                    if p_idx < len(qr_codes) and m_idx < len(qr_codes[p_idx])
                    else []
                )
                advance = ModelAdvantage.ADVANCE_DEPLOYMENT in card.advantages
                player_statuses.append(
                    ModelDeploymentStatus(
                        card=card,
                        qr_codes=list(codes),
                        advance_deploy=advance,
                    )
                )
            self._statuses.append(player_statuses)

        # Build a QR-code → (player, model_index) lookup for fast detection matching.
        self._qr_lookup: dict[str, tuple[int, int]] = {}
        for p_idx, player_statuses in enumerate(self._statuses):
            for m_idx, status in enumerate(player_statuses):
                for code in status.qr_codes:
                    self._qr_lookup[code] = (p_idx, m_idx)

        # Overlay cache.
        self._overlay_cache: Optional[np.ndarray] = None
        self._overlay_dirty: bool = True

        # Async intent-parsing state.
        self._awaiting_intent: bool = False
        self._pending_text: str = ""
        self._intent_req_id: int = -1
        self._service_connected: bool = False

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def statuses(self) -> list[list[ModelDeploymentStatus]]:
        """Per-player list of model deployment statuses."""
        return self._statuses

    @property
    def current_player(self) -> int:
        """Index (0 or 1) of the player currently deploying."""
        return self._current_player

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Begin the deployment phase."""
        self._active = True
        self._current_player = self._first_player
        self._awaiting_intent = False
        if self._service is not None:
            self._service.narrated.connect(self._on_narrated)
            self._service.intent_parsed.connect(self._on_intent_parsed)
            self._service_connected = True
        self._event_manager.push_speech_handler(self._on_speech)
        self._event_manager.push_detection_handler(self._on_detection)
        self._announce_player(self._current_player)

    def stop(self) -> None:
        """Abort the deployment phase early."""
        self._active = False
        self._event_manager.pop_detection_handler(self._on_detection)
        if self._service is not None and self._service_connected:
            try:
                self._service.narrated.disconnect(self._on_narrated)
                self._service.intent_parsed.disconnect(self._on_intent_parsed)
            except (RuntimeError, TypeError):
                pass
            self._service_connected = False
        self._event_manager.pop_speech_handler(self._on_speech)

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
    # Zone geometry
    # ------------------------------------------------------------------

    def _zone_rect_in(self, player: int) -> tuple[float, float, float, float]:
        """Return (x_min, y_min, x_max, y_max) in inches for *player*'s zone.

        The rectangle spans the full board height.  Depth (from the player's
        board edge) is the base deployment depth; per-model Advance Deployment
        bonus is handled in :meth:`_is_in_zone`.
        """
        side = self._sides.get(player, "left")
        board_w = self._zone.width
        board_h = self._zone.height
        depth = self._deployment_depth

        if side == "left":
            return (0.0, 0.0, depth, board_h)
        else:
            return (board_w - depth, 0.0, board_w, board_h)

    def _is_in_zone(self, player: int, status: ModelDeploymentStatus) -> bool:
        """Check if *status*'s position is inside the player's deployment zone.

        Uses per-model depth: ``deployment_depth_in`` + 3" if the model has
        Advance Deployment.
        """
        if status.position_in is None:
            return False

        x, y = status.position_in
        side = self._sides.get(player, "left")
        depth = self._deployment_depth + (
            _ADVANCE_DEPLOY_BONUS if status.advance_deploy else 0.0
        )
        board_w = self._zone.width
        board_h = self._zone.height

        # Check board bounds.
        if not (0.0 <= x <= board_w and 0.0 <= y <= board_h):
            return False

        if side == "left":
            return x <= depth
        else:
            return x >= (board_w - depth)

    # ------------------------------------------------------------------
    # Detection handling
    # ------------------------------------------------------------------

    def _on_detection(self, detections: list, zone_name: str) -> None:
        """Process QR detections: update positions and zone validity."""
        if not self._active:
            return

        for det in detections:
            msg = (getattr(det, "message", "") or "").strip()
            if not msg or msg not in self._qr_lookup:
                continue

            p_idx, m_idx = self._qr_lookup[msg]
            status = self._statuses[p_idx][m_idx]

            # Compute center from bounds (x, y, w, h).
            bounds = getattr(det, "bounds", None)
            if bounds is None:
                corners = getattr(det, "corners", None)
                if corners and len(corners) > 0:
                    cx = sum(c[0] for c in corners) / len(corners)
                    cy = sum(c[1] for c in corners) / len(corners)
                else:
                    continue
            else:
                bx, by, bw, bh = bounds
                cx = bx + bw / 2.0
                cy = by + bh / 2.0

            # Convert camera-ROI pixels → game pixels → inches.
            try:
                game_px = self._zone.camera_to_game((cx, cy))
            except (ValueError, RuntimeError):
                # Zone not calibrated — skip this detection.
                continue

            res = self._zone.resolution
            if res <= 0:
                continue
            x_in = game_px[0] / res
            y_in = game_px[1] / res

            # For multi-code units, aggregate: store the latest position
            # and check all sub-codes are in-zone.  For simplicity (v1),
            # we update position_in to the latest detected code's position
            # and re-check in_zone.  A model is in_zone only if all its
            # codes have been seen and are within the rectangle.
            status.position_in = (x_in, y_in)
            status.in_zone = self._is_in_zone(p_idx, status)

            self._overlay_dirty = True
            self.model_position_updated.emit(
                p_idx, status.card.name, (x_in, y_in), status.in_zone
            )

        # Check all-placed status for current player.
        self._check_all_placed(self._current_player)

    def _check_all_placed(self, player: int) -> None:
        """Emit all_placed_changed if the overall status changed."""
        statuses = self._statuses[player]
        if not statuses:
            all_in = True
        else:
            all_in = all(s.in_zone for s in statuses)
        self.all_placed_changed.emit(player, all_in)

    # ------------------------------------------------------------------
    # Speech handling
    # ------------------------------------------------------------------

    def _on_speech(self, text: str) -> None:
        if not self._active:
            return

        player_label = f"Player {self._current_player + 1}"
        self._log.player_said(player_label, text)

        if self._service is not None:
            if self._awaiting_intent:
                return
            self._awaiting_intent = True
            self._pending_text = text
            self._intent_req_id = self._service.parse_intent_async(
                text.strip(), self._COMPLETE_INTENTS
            )
            return

        intent, value = self._parse_sync(text, self._COMPLETE_INTENTS)
        self._handle_tracking(text, intent, value)

    @QtCore.Slot(int, object)
    def _on_intent_parsed(self, req_id: int, intent: Any) -> None:
        """Continue handling once an async intent parse completes."""
        if self._service is None or req_id != self._intent_req_id:
            return
        self._awaiting_intent = False
        if not self._active:
            return
        name = None if intent.is_unknown else intent.intent
        value = None if intent.is_unknown else intent.value
        self._handle_tracking(self._pending_text, name, value)

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

    def _handle_tracking(
        self, text: str, intent: Optional[str], value: Optional[str]
    ) -> None:
        """Handle speech during the TRACKING state."""
        lower = text.strip().lower()

        if intent == "cancel" or lower in _NEGATIVE:
            self._cancel()
            return

        is_complete = intent == "deployment_complete" or any(
            kw in lower for kw in _COMPLETE_KEYWORDS
        )

        if not is_complete:
            self._say(
                "Say 'deployment complete' when you have finished placing "
                "your models, or 'cancel' to abort."
            )
            return

        # Check all models for current player are in-zone.
        statuses = self._statuses[self._current_player]
        not_placed = [
            s for s in statuses if not s.in_zone
        ]

        if not_placed:
            names = ", ".join(s.card.name for s in not_placed)
            self._say(
                f"The following models are not yet placed in the deployment "
                f"zone: {names}. Please place them before completing.",
            )
            return

        self._advance_or_finish()

    # ------------------------------------------------------------------
    # Player flow
    # ------------------------------------------------------------------

    def _advance_or_finish(self) -> None:
        """Move to the next player or finish the phase."""
        if self._current_player == self._first_player:
            other = 1 if self._current_player == 0 else 0
            self._current_player = other
            self._announce_player(other)
        else:
            self._finish()

    def _announce_player(self, player: int) -> None:
        """Announce a player's deployment turn and enter TRACKING."""
        self._state = DeploymentState.ANNOUNCE
        player_label = f"Player {player + 1}"
        side = self._sides.get(player, "left")
        side_label = "left" if side == "left" else "right"
        depth = self._deployment_depth
        model_count = len(self._statuses[player])

        self._say(
            f"{player_label}, deploy your army on the {side_label} edge. "
            f"Your deployment zone extends {depth:.0f} inches from the edge"
            + (
                f", plus three inches for models with Advance Deployment."
                if any(s.advance_deploy for s in self._statuses[player])
                else "."
            )
            + (
                f" You have {model_count} "
                f"{'model' if model_count == 1 else 'models'} to deploy. "
                "Say 'deployment complete' when finished."
                if model_count > 0
                else " You have no models to deploy. Say 'deployment complete'."
            ),
        )
        self.status_changed.emit(
            f"Deployment: {player_label} placing models…"
        )
        self._state = DeploymentState.TRACKING

    # ------------------------------------------------------------------
    # Projector overlay
    # ------------------------------------------------------------------

    def projector_overlay(self, zone: Zone) -> np.ndarray:
        """Generate a BGRA overlay image showing deployment zones and markers.

        Args:
            zone: The zone to generate the overlay for.

        Returns:
            BGRA numpy array sized to ``zone.get_game_dimensions()``.
        """
        if not self._overlay_dirty and self._overlay_cache is not None:
            return self._overlay_cache

        width_px, height_px = zone.get_game_dimensions()
        res = zone.resolution
        overlay = np.zeros((height_px, width_px, 4), dtype=np.uint8)

        # Draw both players' zone rectangles.
        for p_idx in (0, 1):
            side = self._sides.get(p_idx, "left")
            depth = self._deployment_depth
            depth_px = int(depth * res)

            if side == "left":
                x1 = 0
                x2 = depth_px
            else:
                x2 = width_px
                x1 = width_px - depth_px

            y1 = 0
            y2 = height_px

            fill_color = _P1_ZONE_COLOR if p_idx == 0 else _P2_ZONE_COLOR
            border_color = _P1_BORDER_COLOR if p_idx == 0 else _P2_BORDER_COLOR

            # Translucent fill.
            cv2.rectangle(overlay, (x1, y1), (x2, y2), fill_color, -1)
            # Solid border.
            cv2.rectangle(overlay, (x1, y1), (x2, y2), border_color, 2)

        # Draw model position markers.
        for p_idx, player_statuses in enumerate(self._statuses):
            for status in player_statuses:
                if status.position_in is None:
                    continue
                x_px = int(status.position_in[0] * res)
                y_px = int(status.position_in[1] * res)
                color = _MARKER_IN_ZONE if status.in_zone else _MARKER_OUT_ZONE
                cv2.circle(overlay, (x_px, y_px), _MARKER_RADIUS, color, -1)

        self._overlay_cache = overlay
        self._overlay_dirty = False
        return overlay

    # ------------------------------------------------------------------
    # Completion
    # ------------------------------------------------------------------

    def _finish(self) -> None:
        self._active = False
        self._event_manager.pop_detection_handler(self._on_detection)
        self._event_manager.pop_speech_handler(self._on_speech)
        self._disconnect_service()
        self._state = DeploymentState.DONE
        self._log.system("Deployment phase is complete for both players.")
        self._say(
            "Both armies are deployed. Deployment is complete.",
            use_persona=False,
        )
        self.phase_completed.emit()

    def _cancel(self) -> None:
        self._active = False
        self._event_manager.pop_detection_handler(self._on_detection)
        self._event_manager.pop_speech_handler(self._on_speech)
        self._disconnect_service()
        self._state = DeploymentState.DONE
        self._say("Deployment cancelled.")
        self.deployment_cancelled.emit()

    def _disconnect_service(self) -> None:
        if self._service is not None and self._service_connected:
            try:
                self._service.narrated.disconnect(self._on_narrated)
                self._service.intent_parsed.disconnect(self._on_intent_parsed)
            except (RuntimeError, TypeError):
                pass
            self._service_connected = False
