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

from .game_objects import InGameArmy, InGameModel
from .model_stat_card import BASE_SIZES, ModelAdvantage, ModelStatCard
from .nemesis_deployment import get_strategy

if TYPE_CHECKING:
    from ttga.narration_engine import NarrationEngine
    from ttga.narration_service import NarrationService
    from ttga.qr_detection import QRDetection
    from ttga.zone import Zone

    from .event_manager import GameEventManager
    from .game_log import GameLog
    from .model_database import ModelDatabase


_NEGATIVE = {"no", "nope", "cancel", "stop", "abort", "quit"}
_COMPLETE_KEYWORDS = {"deployment complete", "deploy complete", "done", "finished", "complete"}

_ADVANCE_DEPLOY_BONUS = 3.0

# Maximum distance (inches) allowed between any two models in the same unit.
_UNIT_COHESION_IN = 3.0

_MM_PER_IN = 25.4


def _mm_to_in(mm: float) -> float:
    """Convert millimetres to inches."""
    return mm / _MM_PER_IN


def _distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Euclidean distance between two (x, y) points in the same units."""
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def _resolve_base_sizes_mm(
    card: ModelStatCard, db: Optional[ModelDatabase], count: int
) -> list[int]:
    """Return a base diameter (mm) for each of *count* physical models on *card*.

    Non-unit cards use their own :attr:`ModelStatCard.base_size` for every
    physical model. Unit cards list their composition in
    :attr:`ModelStatCard.troopers` (model name + quantity); each trooper
    type's base size is looked up in *db*. QR codes are registered in
    presentation order, not tied to a specific trooper type, so this is an
    approximation: the expanded trooper list order is used as a best-effort
    match to the registered QR order.

    Args:
        card: The army entry (single model or unit).
        db: Model database used to resolve trooper base sizes. May be
            ``None``, in which case the default base size is used.
        count: Number of physical models (QR codes) to produce sizes for.

    Returns:
        List of *count* base diameters in millimetres.
    """
    if not card.troopers:
        size = card.base_size or BASE_SIZES[0]
        return [size] * count

    sizes: list[int] = []
    for trooper in card.troopers:
        model = db.get_model(trooper.model_name) if db is not None else None
        size = model.base_size if model is not None else BASE_SIZES[0]
        sizes.extend([size] * max(1, trooper.quantity))

    if not sizes:
        sizes = [BASE_SIZES[0]]
    if len(sizes) < count:
        sizes.extend([sizes[-1]] * (count - len(sizes)))
    return sizes[:count]


# Overlay colours (BGRA).
_P1_ZONE_COLOR = (255, 100, 100, 40)       # translucent blue
_P1_BORDER_COLOR = (255, 80, 80, 200)      # solid blue
_P2_ZONE_COLOR = (100, 100, 255, 40)       # translucent red
_P2_BORDER_COLOR = (80, 80, 255, 200)      # solid red
_MARKER_IN_ZONE = (100, 255, 100, 220)     # green
_MARKER_OUT_ZONE = (100, 100, 255, 220)    # red
_MARKER_RADIUS = 6
_SUGGESTED_COLOR = (0, 200, 255, 220)      # amber outline (Nemesis ghost markers)


class DeploymentState(Enum):
    """Discrete states of the deployment phase."""

    IDLE = auto()
    ANNOUNCE = auto()
    TRACKING = auto()
    NEMESIS_DEPLOYING = auto()
    DONE = auto()


@dataclass
class ModelDeploymentStatus:
    """Tracks the deployment state of a single army entry (model or unit).

    A unit entry has one physical model per registered QR code; all
    per-model lists below (``base_sizes_mm``, ``positions``, ``valid``) are
    parallel to :attr:`qr_codes`.

    Attributes:
        card: The model's stat card.
        qr_codes: QR code messages assigned to this entry, one per physical
            model.
        base_sizes_mm: Base diameter (mm) for each physical model.
        positions: Latest position in inches (game coords) for each
            physical model, or ``None`` if not yet detected.
        valid: Whether each physical model currently satisfies all
            deployment rules (containment, unit cohesion, no overlap).
        advance_deploy: Whether this model/unit has Advance Deployment.
    """

    card: ModelStatCard
    qr_codes: list[str]
    base_sizes_mm: list[int] = field(default_factory=list)
    positions: list[Optional[tuple[float, float]]] = field(default_factory=list)
    valid: list[bool] = field(default_factory=list)
    advance_deploy: bool = False

    def __post_init__(self) -> None:
        n = len(self.qr_codes)
        if not self.base_sizes_mm:
            self.base_sizes_mm = [BASE_SIZES[0]] * n
        if not self.positions:
            self.positions = [None] * n
        if not self.valid:
            self.valid = [False] * n

    @property
    def in_zone(self) -> bool:
        """True once every physical model has been placed and is valid."""
        return bool(self.positions) and all(
            p is not None for p in self.positions
        ) and all(self.valid)

    def radius_in(self, index: int) -> float:
        """Base radius in inches for the physical model at *index*."""
        mm = (
            self.base_sizes_mm[index]
            if index < len(self.base_sizes_mm)
            else BASE_SIZES[0]
        )
        return _mm_to_in(mm) / 2.0


class Deployment(QtCore.QObject):
    """AR-assisted deployment phase for two players.

    Signals:
        model_position_updated(int, str, int, object, bool):
            ``(player_index, model_name, model_index, (x_in, y_in),
            entry_fully_valid)`` – one physical model's position was updated
            from a QR detection. ``model_index`` is the index within the
            entry's physical models (0 for single-model entries).
            ``entry_fully_valid`` reflects the whole entry's status after
            recomputing all deployment rules.
        all_placed_changed(int, bool):
            ``(player, all_models_in_zone)`` – the overall placement status
            for a player changed.
        phase_completed(): Both players have finished deploying.
        deployment_cancelled(): The deployment was cancelled.
        narrate(str): Text the narrator should speak aloud.
        status_changed(str): Short status string for the UI.
    """

    model_position_updated = QtCore.Signal(int, str, int, object, bool)
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
        first_player_depth_in: float,
        second_player_depth_in: float,
        zone: Zone,
        event_manager: GameEventManager,
        game_log: GameLog,
        narrator: Any = None,
        narration_engine: Optional[NarrationEngine] = None,
        narration_service: Optional[NarrationService] = None,
        db: Optional[ModelDatabase] = None,
        nemesis_player: Optional[int] = None,
        nemesis_deployment_strategy: Optional[str] = None,
        in_game_armies: Optional[list[InGameArmy]] = None,
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
        self._first_depth = first_player_depth_in
        self._second_depth = second_player_depth_in
        self._zone = zone
        self._nemesis_player = nemesis_player
        self._nemesis_strategy_name = nemesis_deployment_strategy
        # Suggested ("ghost") positions for Nemesis's models, keyed by
        # player index: one list of (x, y) per physical model, parallel to
        # that player's statuses/positions.
        self._suggested_positions: dict[int, list[list[tuple[float, float]]]] = {}
        # Sequential Nemesis deployment state.
        self._nemesis_deploy_queue: list[tuple[int, int, str]] = []
        self._nemesis_deploy_current: Optional[tuple[int, int, str]] = None

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
                base_sizes = _resolve_base_sizes_mm(card, db, len(codes))
                player_statuses.append(
                    ModelDeploymentStatus(
                        card=card,
                        qr_codes=list(codes),
                        base_sizes_mm=base_sizes,
                        advance_deploy=advance,
                    )
                )
            self._statuses.append(player_statuses)

        # Build a QR-code → (player, model_index, physical_index) lookup for
        # fast detection matching.
        self._qr_lookup: dict[str, tuple[int, int, int]] = {}
        for p_idx, player_statuses in enumerate(self._statuses):
            for m_idx, status in enumerate(player_statuses):
                for code_idx, code in enumerate(status.qr_codes):
                    self._qr_lookup[code] = (p_idx, m_idx, code_idx)

        # Build a QR-code -> InGameModel lookup for position syncing.
        self._in_game_armies = in_game_armies
        self._in_game_model_lookup: dict[str, InGameModel] = {}
        if in_game_armies is not None:
            for army in in_game_armies:
                for model in army.all_models:
                    if model.qr_code:
                        self._in_game_model_lookup[model.qr_code] = model

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

    def _depth_for(self, player: int) -> float:
        """Return the base deployment zone depth (inches) for *player*.

        The player who deploys first uses ``first_player_depth_in``; the
        other player uses ``second_player_depth_in`` (typically deeper, to
        compensate for going second).
        """
        return (
            self._first_depth
            if player == self._first_player
            else self._second_depth
        )

    def _zone_rect_in(
        self, player: int, extra_depth: float = 0.0
    ) -> tuple[float, float, float, float]:
        """Return (x_min, y_min, x_max, y_max) in inches for *player*'s zone.

        The rectangle spans the full board height.  Depth (from the player's
        board edge) is the base deployment depth plus *extra_depth* (used to
        add the per-model Advance Deployment bonus).
        """
        side = self._sides.get(player, "left")
        board_w = self._zone.width
        board_h = self._zone.height
        depth = self._depth_for(player) + extra_depth

        if side == "left":
            return (0.0, 0.0, depth, board_h)
        else:
            return (board_w - depth, 0.0, board_w, board_h)

    # ------------------------------------------------------------------
    # Deployment rule validation
    # ------------------------------------------------------------------

    def _recompute_validity(self) -> None:
        """Recompute per-physical-model validity across both players.

        A physical model's placement is valid only if all three rules hold:

        1. Its base is fully inside its player's deployment zone (no part
           of the base may be outside), accounting for base size and the
           Advance Deployment bonus when applicable.
        2. It is within 3" of every other model in the same unit (unit
           cohesion). Units of one model automatically satisfy this.
        3. Its base does not overlap any other placed model's base,
           anywhere on the table (either player's models).
        """
        # Collect every currently placed physical model: (player, model_idx,
        # code_idx, x, y, radius_in).
        placed: list[tuple[int, int, int, float, float, float]] = []
        for p_idx, player_statuses in enumerate(self._statuses):
            for m_idx, status in enumerate(player_statuses):
                for code_idx, pos in enumerate(status.positions):
                    if pos is None:
                        continue
                    x, y = pos
                    r = status.radius_in(code_idx)
                    placed.append((p_idx, m_idx, code_idx, x, y, r))
                    status.valid[code_idx] = True

        # Rule 1: full base containment within the deployment zone.
        for p_idx, m_idx, code_idx, x, y, r in placed:
            status = self._statuses[p_idx][m_idx]
            extra = _ADVANCE_DEPLOY_BONUS if status.advance_deploy else 0.0
            x_min, y_min, x_max, y_max = self._zone_rect_in(p_idx, extra)
            if not (
                x - r >= x_min
                and x + r <= x_max
                and y - r >= y_min
                and y + r <= y_max
            ):
                status.valid[code_idx] = False

        # Rule 2: unit cohesion — every model within 3" of every other model
        # in the same unit.
        for player_statuses in self._statuses:
            for status in player_statuses:
                placed_idxs = [
                    i for i, p in enumerate(status.positions) if p is not None
                ]
                if len(placed_idxs) < 2:
                    continue
                for i in placed_idxs:
                    ok = all(
                        i == j
                        or _distance(status.positions[i], status.positions[j])
                        <= _UNIT_COHESION_IN
                        for j in placed_idxs
                    )
                    if not ok:
                        status.valid[i] = False

        # Rule 3: no base overlap between any two placed models, anywhere on
        # the table (across both players).
        for a in range(len(placed)):
            pa, ma, ca, xa, ya, ra = placed[a]
            for b in range(a + 1, len(placed)):
                pb, mb, cb, xb, yb, rb = placed[b]
                if _distance((xa, ya), (xb, yb)) < (ra + rb):
                    self._statuses[pa][ma].valid[ca] = False
                    self._statuses[pb][mb].valid[cb] = False

        self._overlay_dirty = True

    # ------------------------------------------------------------------
    # Detection handling
    # ------------------------------------------------------------------

    def _on_detection(self, detections: list, zone_name: str) -> None:
        """Process QR detections: update per-model positions and validity."""
        if not self._active:
            return

        updated: list[tuple[int, int, int]] = []
        for det in detections:
            msg = (getattr(det, "message", "") or "").strip()
            if not msg or msg not in self._qr_lookup:
                continue

            p_idx, m_idx, code_idx = self._qr_lookup[msg]
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

            status.positions[code_idx] = (x_in, y_in)
            # Sync position to the InGameModel if available.
            in_game_model = self._in_game_model_lookup.get(msg)
            if in_game_model is not None:
                in_game_model.position = (x_in, y_in)
            updated.append((p_idx, m_idx, code_idx))

        if updated:
            # Validity depends on every other placed model (cohesion and
            # overlap are cross-model), so recompute once per batch rather
            # than incrementally per detection.
            self._recompute_validity()
            for p_idx, m_idx, code_idx in updated:
                status = self._statuses[p_idx][m_idx]
                self.model_position_updated.emit(
                    p_idx,
                    status.card.name,
                    code_idx,
                    status.positions[code_idx],
                    status.in_zone,
                )

        # Advance Nemesis sequential deployment if the current model was detected.
        if (self._state == DeploymentState.NEMESIS_DEPLOYING
                and self._nemesis_deploy_current is not None
                and updated):
            waiting_qr = self._nemesis_deploy_current[2]
            for p, m, c in updated:
                status_qr = self._statuses[p][m].qr_codes
                if c < len(status_qr) and status_qr[c] == waiting_qr:
                    self._nemesis_deploy_next(self._current_player)
                    break

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
        depth = self._depth_for(player)
        model_count = len(self._statuses[player])
        is_nemesis_turn = player == self._nemesis_player

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

        if is_nemesis_turn and model_count > 0:
            self._say(
                f"Nemesis will now deploy its army on the {side_label} edge. "
                f"{model_count} {'model' if model_count == 1 else 'models'} to place.",
                use_persona=False,
            )
            self.status_changed.emit("Deployment: Nemesis placing models…")
            self._begin_nemesis_sequential_deploy(player)
            return

        self._state = DeploymentState.TRACKING

    def _generate_nemesis_suggestions(self, player: int) -> None:
        """Compute suggested ("ghost") positions for Nemesis's models.

        Uses the strategy named by ``nemesis_deployment_strategy``. Failure
        to resolve the strategy silently disables suggestions for this
        turn -- the player can still freely place Nemesis's models and the
        real deployment rules are enforced regardless.
        """
        self._suggested_positions.pop(player, None)
        if not self._nemesis_strategy_name:
            return
        try:
            strategy = get_strategy(self._nemesis_strategy_name)
        except KeyError:
            self._log.system(
                f"Unknown Nemesis deployment strategy "
                f"'{self._nemesis_strategy_name}'; skipping suggestions."
            )
            return

        zone_rect = self._zone_rect_in(player)
        units = [
            [status.radius_in(i) for i in range(len(status.qr_codes))]
            for status in self._statuses[player]
        ]
        self._suggested_positions[player] = strategy(zone_rect, units)
        self._overlay_dirty = True

    # ------------------------------------------------------------------
    # Nemesis sequential deployment
    # ------------------------------------------------------------------

    def _begin_nemesis_sequential_deploy(self, player: int) -> None:
        """Start the sequential one-model-at-a-time deployment for Nemesis."""
        self._generate_nemesis_suggestions(player)
        self._nemesis_deploy_queue = []
        for m_idx, status in enumerate(self._statuses[player]):
            for code_idx, qr in enumerate(status.qr_codes):
                self._nemesis_deploy_queue.append((m_idx, code_idx, qr))
        self._nemesis_deploy_current = None
        self._state = DeploymentState.NEMESIS_DEPLOYING
        self._nemesis_deploy_next(player)

    def _nemesis_deploy_next(self, player: int) -> None:
        """Announce and show the circle for the next Nemesis model, or finish."""
        if not self._nemesis_deploy_queue:
            self._nemesis_deploy_current = None
            self._say(
                "All Nemesis models have been placed. "
                "Deployment for Nemesis is complete.",
                use_persona=False,
            )
            self._advance_or_finish()
            return

        m_idx, code_idx, qr = self._nemesis_deploy_queue.pop(0)
        self._nemesis_deploy_current = (m_idx, code_idx, qr)
        status = self._statuses[player][m_idx]

        # Get the identification label from the InGameModel.
        label = ""
        in_game_model = self._in_game_model_lookup.get(qr)
        if in_game_model is not None:
            label = in_game_model.label

        model_name = status.card.name
        self._say(
            f"Place the {model_name}, model {label}. "
            "A circle on the table shows where to position it.",
            use_persona=False,
        )
        self._overlay_dirty = True

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
            depth = self._depth_for(p_idx)
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

        # Draw a hollow circle for the current Nemesis model being deployed.
        if (self._state == DeploymentState.NEMESIS_DEPLOYING
                and self._nemesis_deploy_current is not None):
            m_idx, code_idx, _ = self._nemesis_deploy_current
            suggestions = self._suggested_positions.get(self._current_player)
            if (suggestions and m_idx < len(suggestions)
                    and code_idx < len(suggestions[m_idx])):
                x, y = suggestions[m_idx][code_idx]
                status = self._statuses[self._current_player][m_idx]
                base_mm = (
                    status.base_sizes_mm[code_idx]
                    if code_idx < len(status.base_sizes_mm)
                    else BASE_SIZES[0]
                )
                # Diameter = base + 4 mm -> radius in inches.
                radius_in = (base_mm + 4.0) / (2.0 * _MM_PER_IN)
                # Thickness = 2 mm -> pixels.
                thickness_px = max(1, int(2.0 / _MM_PER_IN * res))
                x_px = int(x * res)
                y_px = int(y * res)
                r_px = max(_MARKER_RADIUS, int(radius_in * res))
                cv2.circle(
                    overlay, (x_px, y_px), r_px,
                    _SUGGESTED_COLOR, thickness_px,
                )

        # Draw a base-sized marker per physical model, coloured by that
        # specific model's own rule validity (containment, cohesion, overlap).
        for player_statuses in self._statuses:
            for status in player_statuses:
                for idx, pos in enumerate(status.positions):
                    if pos is None:
                        continue
                    x_px = int(pos[0] * res)
                    y_px = int(pos[1] * res)
                    r_px = max(_MARKER_RADIUS, int(status.radius_in(idx) * res))
                    color = (
                        _MARKER_IN_ZONE if status.valid[idx] else _MARKER_OUT_ZONE
                    )
                    cv2.circle(overlay, (x_px, y_px), r_px, color, -1)

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
