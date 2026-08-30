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

"""In-game object classes for the Warmachine game.

Defines :class:`InGameModel`, :class:`InGameUnit`, :class:`InGameArmy`, and
:class:`Table` -- runtime game-state objects that track positions, health,
continuous effects, and turn state beyond the deployment phase.

These objects are instantiated from :class:`ArmyCreation` results just before
deployment begins, and are updated with positions as QR codes are detected
during deployment.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Optional

from .damage_system import (
    AnyDamageSystem,
    BoxDamageSystem,
    GridDamageSystem,
    SpiralDamageSystem,
    WebDamageSystem,
)
from .model_stat_card import BasicType, ModelStatCard

if TYPE_CHECKING:
    from .model_database import ModelDatabase


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_UNIT_BASIC_TYPES = frozenset({BasicType.UNIT, BasicType.COMMAND_ATTACHMENT_UNIT})


def _total_health(damage_system: AnyDamageSystem) -> int:
    """Compute total health (damage capacity) from a damage system.

    Args:
        damage_system: Any concrete damage system instance.

    Returns:
        Total number of damage boxes/cells the system can absorb.
    """
    if isinstance(damage_system, BoxDamageSystem):
        return damage_system.boxes
    if isinstance(damage_system, GridDamageSystem):
        count = 0
        for row in damage_system.left_grid:
            count += sum(1 for cell in row if cell.value != "NA")
        if damage_system.right_grid is not None:
            for row in damage_system.right_grid:
                count += sum(1 for cell in row if cell.value != "NA")
        return count
    if isinstance(damage_system, SpiralDamageSystem):
        return (
            damage_system.mind.branch1
            + damage_system.mind.branch2
            + damage_system.mind.common
            + damage_system.body.branch1
            + damage_system.body.branch2
            + damage_system.body.common
            + damage_system.spirit.branch1
            + damage_system.spirit.branch2
            + damage_system.spirit.common
        )
    if isinstance(damage_system, WebDamageSystem):
        return damage_system.outer + damage_system.middle + damage_system.center
    return 1


def _letter_for_index(index: int) -> str:
    """Convert a 0-based index to a letter label (0->A, 1->B, ..., 25->Z, 26->AA, ...)."""
    result = ""
    n = index
    while True:
        result = chr(ord("A") + n % 26) + result
        n = n // 26 - 1
        if n < 0:
            break
    return result


# ---------------------------------------------------------------------------
# In-game objects
# ---------------------------------------------------------------------------


@dataclass
class InGameModel:
    """A single physical model on the table during a match.

    Attributes:
        stat_card: The model's stat card (static definition).
        qr_code: QR code message assigned to this physical model.
        label: Identification letter (A, B, C, ...) for narration.
        position: (x, y) position in inches (game coordinates), or None if
            not yet placed on the table.
        health: Current remaining health (damage capacity).
        max_health: Maximum health (for reference / healing).
        continuous_effects: List of active continuous effect names (e.g.
            "Fire", "Corrosion").
        statistics_modifiers: List of active statistic modifiers (to be
            implemented later).
        played_this_turn: Whether this model has activated/played this turn.
    """

    stat_card: ModelStatCard
    qr_code: str = ""
    label: str = ""
    position: Optional[tuple[float, float]] = None
    health: int = 1
    max_health: int = 1
    continuous_effects: list[str] = field(default_factory=list)
    statistics_modifiers: list[Any] = field(default_factory=list)
    played_this_turn: bool = False


@dataclass
class InGameUnit:
    """A unit composed of multiple physical models.

    Attributes:
        stat_card: The unit entry's stat card (defines the unit as a whole).
        models: The individual physical models in this unit.
    """

    stat_card: ModelStatCard
    models: list[InGameModel] = field(default_factory=list)


class InGameArmy:
    """An army during a match, composed of independent models and units.

    Attributes:
        faction: Faction name for this army (or None).
        independent_models: Solo models, warcasters, warjacks, etc.
        units: Units (groups of models).
    """

    def __init__(
        self,
        faction: Optional[str] = None,
        independent_models: Optional[list[InGameModel]] = None,
        units: Optional[list[InGameUnit]] = None,
    ) -> None:
        self.faction = faction
        self.independent_models: list[InGameModel] = independent_models or []
        self.units: list[InGameUnit] = units or []

    @property
    def all_models(self) -> list[InGameModel]:
        """All models in the army (independent + all unit members)."""
        models = list(self.independent_models)
        for unit in self.units:
            models.extend(unit.models)
        return models

    @property
    def total_cost(self) -> int:
        """Total point cost of all entries in this army."""
        return sum(m.stat_card.cost for m in self.independent_models) + sum(
            u.stat_card.cost for u in self.units
        )


@dataclass
class Table:
    """The game table, holding terrain and area effects.

    Attributes:
        width: Table width in inches.
        height: Table height in inches.
        terrain_features: List of terrain features (to be implemented).
        cloud_effects: List of cloud effects (to be implemented).
    """

    width: float = 48.0
    height: float = 48.0
    terrain_features: list[Any] = field(default_factory=list)
    cloud_effects: list[Any] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def _resolve_trooper_card(
    unit_card: ModelStatCard, code_idx: int, db: Optional[ModelDatabase]
) -> ModelStatCard:
    """Resolve the stat card for the *code_idx*-th physical model in a unit.

    Unit cards list their composition in :attr:`ModelStatCard.troopers`
    (model name + quantity). QR codes are registered in presentation order,
    so we expand the trooper list and pick by index.

    If the trooper can't be resolved (no db or index out of range), the
    unit card itself is returned as a fallback.
    """
    if not unit_card.troopers or db is None:
        return unit_card

    expanded: list[str] = []
    for trooper in unit_card.troopers:
        expanded.extend([trooper.model_name] * max(1, trooper.quantity))

    if code_idx < len(expanded):
        model = db.get_model(expanded[code_idx])
        if model is not None:
            return model

    return unit_card


def create_armies_from_creation(
    armies: list[list[ModelStatCard]],
    qr_codes: list[list[list[str]]],
    factions: list[Optional[str]],
    db: Optional[ModelDatabase] = None,
) -> list[InGameArmy]:
    """Instantiate :class:`InGameArmy` objects from army-creation results.

    Each entry in a player's army list becomes either an
    :class:`InGameModel` (for single-model entries) or an
    :class:`InGameUnit` (for unit entries), with one :class:`InGameModel`
    per registered QR code. Models are assigned identification letters
    (A, B, C, ...) in order.

    Args:
        armies: Per-player list of model stat cards (one per army entry).
        qr_codes: Per-player, per-entry list of QR code messages.
        factions: Faction name for each player (or None).
        db: Model database for resolving trooper stat cards within units.

    Returns:
        One :class:`InGameArmy` per player.
    """
    result: list[InGameArmy] = []
    for p_idx, army_list in enumerate(armies):
        faction = factions[p_idx] if p_idx < len(factions) else None
        in_game_army = InGameArmy(faction=faction)
        letter_counter = 0

        for m_idx, card in enumerate(army_list):
            codes = (
                qr_codes[p_idx][m_idx]
                if p_idx < len(qr_codes) and m_idx < len(qr_codes[p_idx])
                else []
            )

            if card.basic_type in _UNIT_BASIC_TYPES:
                unit = InGameUnit(stat_card=card)
                for code_idx, qr in enumerate(codes):
                    trooper_card = _resolve_trooper_card(card, code_idx, db)
                    health = _total_health(trooper_card.damage_system)
                    model = InGameModel(
                        stat_card=trooper_card,
                        qr_code=qr,
                        label=_letter_for_index(letter_counter),
                        health=health,
                        max_health=health,
                    )
                    unit.models.append(model)
                    letter_counter += 1
                in_game_army.units.append(unit)
            else:
                health = _total_health(card.damage_system)
                qr = codes[0] if codes else ""
                model = InGameModel(
                    stat_card=card,
                    qr_code=qr,
                    label=_letter_for_index(letter_counter),
                    health=health,
                    max_health=health,
                )
                in_game_army.independent_models.append(model)
                letter_counter += 1

        result.append(in_game_army)
    return result
