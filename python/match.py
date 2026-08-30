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

"""Single-match orchestration for the Warmachine game.

A :class:`Match` owns the full lifecycle of one game: army creation → (future
phases) → end.  It creates and manages the :class:`GameLog` and delegates each
phase to its own object (e.g. :class:`ArmyCreation`).
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Any, Optional

from PySide6 import QtCore

from .army_creation import ArmyCreation
from .deployment import Deployment
from .game_log import GameLog
from .game_objects import InGameArmy, create_armies_from_creation
from .match_settings import NEMESIS_PLAYER_INDEX
from .roll_off import RollOff
from .setup_flow import SetupFlow

if TYPE_CHECKING:
    from ttga.narration_engine import NarrationEngine
    from ttga.narration_service import NarrationService
    from ttga.zone import Zone

    from .event_manager import GameEventManager
    from .match_settings import MatchSettings
    from .model_database import ModelDatabase


class MatchPhase(str, Enum):
    """Discrete phases a match passes through."""

    SETUP = "Setup"
    ARMY_CREATION = "Army Creation"
    ROLL_OFF = "Roll-off"
    DEPLOYMENT = "Deployment"


class Match(QtCore.QObject):
    """Orchestrates a single Warmachine match.

    Signals:
        phase_changed(str): Emitted with the :class:`MatchPhase` value when
            the match transitions to a new phase.
        match_ended(): The match has concluded (all phases done or stopped).
    """

    phase_changed = QtCore.Signal(str)
    match_ended = QtCore.Signal()

    def __init__(
        self,
        db: ModelDatabase,
        event_manager: GameEventManager,
        narrator: Any = None,
        narration_engine: Optional[NarrationEngine] = None,
        narration_service: Optional[NarrationService] = None,
        zone: Optional[Zone] = None,
        *,
        match_settings: Optional[MatchSettings] = None,
        match_threshold: float = 0.7,
        parent: Optional[QtCore.QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._db = db
        self._event_manager = event_manager
        self._narrator = narrator
        self._narration = narration_engine
        self._service = narration_service
        self._zone = zone
        self._match_settings = match_settings
        self._match_threshold: float = match_threshold
        self._phase: Optional[MatchPhase] = None
        self._log = GameLog(parent=self)
        self._setup_flow: Optional[SetupFlow] = None
        self._army_creation: Optional[ArmyCreation] = None
        self._roll_off: Optional[RollOff] = None
        self._deployment: Optional[Deployment] = None
        self._in_game_armies: list[InGameArmy] = []
        self._roll_off_result: dict = {}
        self._config: dict = {}

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def phase(self) -> Optional[MatchPhase]:
        """Current match phase, or ``None`` before :meth:`start`."""
        return self._phase

    @property
    def log(self) -> GameLog:
        """The :class:`GameLog` for this match."""
        return self._log

    @property
    def army_creation(self) -> Optional[ArmyCreation]:
        """The :class:`ArmyCreation` instance (available during that phase)."""
        return self._army_creation

    @property
    def setup_flow(self) -> Optional[SetupFlow]:
        """The :class:`SetupFlow` instance (available during the setup phase)."""
        return self._setup_flow

    @property
    def config(self) -> dict:
        """The configuration produced by the setup phase."""
        return self._config

    @property
    def roll_off(self) -> Optional[RollOff]:
        """The :class:`RollOff` instance (available during that phase)."""
        return self._roll_off

    @property
    def deployment(self) -> Optional[Deployment]:
        """The :class:`Deployment` instance (available during that phase)."""
        return self._deployment

    @property
    def in_game_armies(self) -> list[InGameArmy]:
        """In-game army objects (available after army creation, before deployment)."""
        return self._in_game_armies

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the match (begins with the conversational setup phase)."""
        self._log.system("A new match has begun.")
        self._begin_setup()

    def stop(self) -> None:
        """Stop the match prematurely."""
        if self._setup_flow is not None:
            self._setup_flow.stop()
        if self._army_creation is not None:
            self._army_creation.stop()
        if self._roll_off is not None:
            self._roll_off.stop()
        if self._deployment is not None:
            self._deployment.stop()
        self._log.system("The match has been stopped.")
        self._log.close()
        self.match_ended.emit()

    # ------------------------------------------------------------------
    # Phase transitions
    # ------------------------------------------------------------------

    def _begin_setup(self) -> None:
        self._phase = MatchPhase.SETUP
        self._setup_flow = SetupFlow(
            event_manager=self._event_manager,
            game_log=self._log,
            narrator=self._narrator,
            narration_engine=self._narration,
            narration_service=self._service,
            match_settings=self._match_settings,
            parent=self,
        )
        self._setup_flow.setup_complete.connect(self._on_setup_complete)
        self._setup_flow.setup_cancelled.connect(self._on_setup_cancelled)
        # Emit only after setup_flow exists so listeners can wire its signals
        # before the phase starts.
        self.phase_changed.emit(self._phase.value)
        self._setup_flow.start()

    @QtCore.Slot(dict)
    def _on_setup_complete(self, config: dict) -> None:
        self._config = config
        self._log.system("Setup phase is complete.")
        self._begin_army_creation()

    @QtCore.Slot()
    def _on_setup_cancelled(self) -> None:
        self._log.system("Setup was cancelled; the match will not start.")
        self._log.close()
        self.match_ended.emit()

    def _begin_army_creation(self) -> None:
        self._phase = MatchPhase.ARMY_CREATION
        nemesis_player = (
            NEMESIS_PLAYER_INDEX
            if self._match_settings is not None
            and self._match_settings.nemesis_chooses_army
            else None
        )
        points = (
            self._match_settings.points if self._match_settings is not None else None
        )
        self._army_creation = ArmyCreation(
            db=self._db,
            event_manager=self._event_manager,
            game_log=self._log,
            narrator=self._narrator,
            narration_engine=self._narration,
            narration_service=self._service,
            match_threshold=self._match_threshold,
            nemesis_player=nemesis_player,
            points=points,
            parent=self,
        )
        self._army_creation.phase_completed.connect(
            self._on_army_creation_done
        )
        # Emit only after army_creation exists so listeners (e.g. the dialog)
        # can wire its signals before the phase starts.
        self.phase_changed.emit(self._phase.value)
        self._army_creation.start()

    @QtCore.Slot()
    def _on_army_creation_done(self) -> None:
        self._log.system("Army creation phase is complete.")
        self._begin_roll_off()

    def _begin_roll_off(self) -> None:
        self._phase = MatchPhase.ROLL_OFF
        self._roll_off = RollOff(
            event_manager=self._event_manager,
            game_log=self._log,
            narrator=self._narrator,
            narration_engine=self._narration,
            narration_service=self._service,
            parent=self,
        )
        self._roll_off.roll_off_complete.connect(self._on_roll_off_complete)
        self._roll_off.roll_off_cancelled.connect(self._on_roll_off_cancelled)
        self.phase_changed.emit(self._phase.value)
        self._roll_off.start()

    @QtCore.Slot(dict)
    def _on_roll_off_complete(self, result: dict) -> None:
        self._roll_off_result = result
        self._log.system(
            f"Roll-off complete: first_player={result.get('first_player')}, "
            f"sides={result.get('sides')}."
        )
        self._begin_deployment()

    @QtCore.Slot()
    def _on_roll_off_cancelled(self) -> None:
        self._log.system("Roll-off was cancelled; the match will not continue.")
        self._log.close()
        self.match_ended.emit()

    def _begin_deployment(self) -> None:
        self._phase = MatchPhase.DEPLOYMENT
        if self._match_settings is not None:
            first_depth = self._match_settings.first_player_depth_in
            second_depth = self._match_settings.second_player_depth_in
        else:
            first_depth = self._config.get("deployment_depth", 7.0)
            second_depth = first_depth
        nemesis_player = (
            NEMESIS_PLAYER_INDEX
            if self._match_settings is not None
            and self._match_settings.nemesis_chooses_deployment
            else None
        )
        nemesis_strategy = (
            self._match_settings.nemesis_deployment_strategy
            if self._match_settings is not None
            else None
        )
        # Instantiate in-game army objects from army-creation results.
        self._in_game_armies = create_armies_from_creation(
            armies=self._army_creation.armies,
            qr_codes=self._army_creation.qr_codes,
            factions=self._army_creation.factions,
            db=self._db,
        )
        self._deployment = Deployment(
            armies=self._army_creation.armies,
            qr_codes=self._army_creation.qr_codes,
            sides=self._roll_off_result["sides"],
            first_player=self._roll_off_result["first_player"],
            first_player_depth_in=first_depth,
            second_player_depth_in=second_depth,
            zone=self._zone,
            event_manager=self._event_manager,
            game_log=self._log,
            narrator=self._narrator,
            narration_engine=self._narration,
            narration_service=self._service,
            db=self._db,
            nemesis_player=nemesis_player,
            nemesis_deployment_strategy=nemesis_strategy,
            in_game_armies=self._in_game_armies,
            parent=self,
        )
        self._deployment.phase_completed.connect(self._on_deployment_done)
        self._deployment.deployment_cancelled.connect(
            self._on_deployment_cancelled
        )
        self.phase_changed.emit(self._phase.value)
        self._deployment.start()

    @QtCore.Slot()
    def _on_deployment_done(self) -> None:
        self._log.system("Deployment phase is complete.")
        self._log.system(
            "Armies are deployed. The match is ready to begin Round 1."
        )
        self._say_match(
            "Both armies are deployed and ready for battle. "
            "The first round is about to begin.",
        )
        # The match pauses here, right before the start of the first round.
        # Future: transition to Round 1 / turn structure.

    def _say_match(self, text: str, *, use_persona: bool = False) -> None:
        """Speak narration text using available narrator infrastructure."""
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

    @QtCore.Slot()
    def _on_deployment_cancelled(self) -> None:
        self._log.system("Deployment was cancelled; the match will not continue.")
        self._log.close()
        self.match_ended.emit()
