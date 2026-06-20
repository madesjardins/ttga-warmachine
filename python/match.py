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
from .game_log import GameLog

if TYPE_CHECKING:
    from .event_manager import GameEventManager
    from .model_database import ModelDatabase


class MatchPhase(str, Enum):
    """Discrete phases a match passes through."""

    ARMY_CREATION = "Army Creation"
    # Future phases will be added here.


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
        parent: Optional[QtCore.QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._db = db
        self._event_manager = event_manager
        self._narrator = narrator
        self._phase: Optional[MatchPhase] = None
        self._log = GameLog(parent=self)
        self._army_creation: Optional[ArmyCreation] = None

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

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the match (begins with army creation)."""
        self._log.system("A new match has begun.")
        self._begin_army_creation()

    def stop(self) -> None:
        """Stop the match prematurely."""
        if self._army_creation is not None:
            self._army_creation.stop()
        self._log.system("The match has been stopped.")
        self._log.close()
        self.match_ended.emit()

    # ------------------------------------------------------------------
    # Phase transitions
    # ------------------------------------------------------------------

    def _begin_army_creation(self) -> None:
        self._phase = MatchPhase.ARMY_CREATION
        self._army_creation = ArmyCreation(
            db=self._db,
            event_manager=self._event_manager,
            game_log=self._log,
            narrator=self._narrator,
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
        # Future: transition to the next phase (deployment, rounds, etc.).
