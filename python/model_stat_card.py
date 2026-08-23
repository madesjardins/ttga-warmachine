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

"""Model stat card module for the Warmachine game.

Defines the ModelStatCard dataclass and all related enums used to represent
Warmachine model data in a JSON-serializable format.  The statistics type
itself lives in :mod:`model_statistics` and is re-exported here for
convenience.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .damage_system import (
    AnyDamageSystem,
    BoxDamageSystem,
    DamageSystemType,
    damage_system_from_dict,
)
from .model_special_attack import ModelSpecialAttack, model_special_attack_from_name
from .model_special_rule import ModelSpecialRule, model_special_rule_from_name
from .model_statistics import ModelStatistics
from .weapon import Hardpoint, MeleeWeapon, RangeWeapon


BASE_SIZES: tuple[int, ...] = (30, 40, 50, 90, 120)
"""Valid base diameter values in millimetres."""


class Faction(str, Enum):
    """Faction a model belongs to.

    Values are intentionally kept as human-readable strings so they
    serialise cleanly to JSON without a custom encoder.
    """

    CIRCLE_ORBOROS = "Circle Orboros"
    CONVERGENCE_OF_CYRISS = "Convergence of Cyriss"
    CRUCIBLE_GUARD = "Crucible Guard"
    CRYX = "Cryx"
    CYGNAR = "Cygnar"
    DUSK = "Dusk"
    GRYMKIN = "Grymkin"
    INFERNALS = "Infernals"
    KHADOR = "Khador"
    KHYMAERA = "Khymaera"
    LEGION_OF_EVERBLIGHT = "Legion of Everblight"
    MERCENARIES = "Mercenaries"
    ORGOTH = "Orgoth"
    PROTECTORATE_OF_MENOTH = "Protectorate of Menoth"
    RETRIBUTION_OF_SCYRAH = "Retribution of Scyrah"
    SKORNE = "Skorne"
    SOUTHERN_KRIELS = "Southern Kriels"
    TROLLBLOODS = "Trollbloods"


class BasicType(str, Enum):
    """Basic model type classification.

    Values are intentionally kept as human-readable strings so they
    serialise cleanly to JSON without a custom encoder.
    """

    WARCASTER = "Warcaster"
    WARLOCK = "Warlock"
    INFERNAL_MASTER = "Infernal Master"
    WARJACK = "Warjack"
    WARBEAST = "Warbeast"
    MONSTROSITY = "Monstrosity"
    HORROR = "Horror"
    BATTLE_ENGINE = "Battle Engine"
    STRUCTURE = "Structure"
    SOLO = "Solo"
    TROOPER = "Trooper"
    COMMAND_ATTACHMENT = "Command Attachment"
    WEAPON_ATTACHMENT = "Weapon Attachment"
    UNIT = "Unit"
    COMMAND_ATTACHMENT_UNIT = "Command Attachment Unit"


_UNIT_TYPES: frozenset[BasicType] = frozenset(
    {BasicType.UNIT, BasicType.COMMAND_ATTACHMENT_UNIT}
)


class Army(str, Enum):
    """Army list a model may be included in.

    Values are intentionally kept as human-readable strings so they
    serialise cleanly to JSON without a custom encoder.
    """

    CYGNAR = "Cygnar"
    STORM_KNIGHTS = "Storm Knights"
    KHADOR = "Khador"
    FIFTH_DIVISION = "5th Division"


class Keyword(str, Enum):
    """Model keyword.

    Values are intentionally kept as human-readable strings so they
    serialise cleanly to JSON without a custom encoder.
    """

    MERCENARY = "Mercenary"
    BLIGHTED = "Blighted"
    OGRUN = "Ogrun"
    NYSS = "Nyss"


class ModelAdvantage(str, Enum):
    """Model advantage.

    Values are intentionally kept as human-readable strings so they
    serialise cleanly to JSON without a custom encoder.
    """

    JACK_MARSHAL = "Jack Marshal"
    ADVANCE_DEPLOYMENT = "Advance Deployment"
    AMBUSH = "Ambush"
    AMPHIBIOUS = "Amphibious"
    ARC_NODE = "Arc Node"
    ASSAULT = "Assault"
    CAVALRY = "Cavalry"
    COMBINED_MELEE_ATTACK = "Combined Melee Attack"
    COMBINED_RANGED_ATTACK = "Combined Ranged Attack"
    CONSTRUCT = "Construct"
    DUAL_ATTACK = "Dual Attack"
    EYELESS_SIGHT = "Eyeless Sight"
    FLIGHT = "Flight"
    GLADIATOR = "Gladiator"
    GUNFIGHTER = "Gunfighter"
    HEADBUTT_POWER_ATTACK = "Headbutt Power Attack"
    INCORPOREAL = "Incorporeal"
    PATHFINDER = "Pathfinder"
    SLAM_POWER_ATTACK = "Slam Power Attack"
    SOULLESS = "Soulless"
    STEALTH = "Stealth"
    TOUGH = "Tough"
    TRAMPLE_POWER_ATTACK = "Trample Power Attack"
    UNDEAD = "Undead"
    UNSTOPPABLE = "Unstoppable"


class ModelResistance(str, Enum):
    """Model resistance to a damage type.

    Values are intentionally kept as human-readable strings so they
    serialise cleanly to JSON without a custom encoder.
    """

    BLAST = "Blast"
    COLD = "Cold"
    CORROSION = "Corrosion"
    ELECTRICITY = "Electricity"
    FIRE = "Fire"


@dataclass
class TrooperEntry:
    """A model and its quantity within a unit."""

    model_name: str
    quantity: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {"model_name": self.model_name, "quantity": self.quantity}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TrooperEntry:
        return cls(
            model_name=str(data["model_name"]),
            quantity=int(data.get("quantity", 1)),
        )


@dataclass
class ModelStatCard:
    """Represents a Warmachine model stat card.

    All fields are JSON-serializable via :meth:`to_dict` / :meth:`from_dict`.

    Attributes:
        name: Unique model name used as the primary identifier.
        short_name: Abbreviated display name.
        vocal_names: Names accepted by voice recognition for this model.
        faction: Faction the model belongs to.
        basic_type: Basic model type classification (Solo, Trooper, …).
        base_size: Base diameter in millimetres. Must be one of
            ``(30, 40, 50, 90, 120)``.
        cost: Point cost. Must be >= 0.
        model_statistics: Combat statistics for this model.
        damage_system_type: Identifies which damage system this model uses.
        damage_system: The model's damage system instance.
        is_character: True if the model is a Character. Defaults to False.
        fa: Field allowance. Must be >= -1; -1 means infinite. Defaults to -1.
        armies: Army lists this model may be included in.
        keywords: Model keywords.
        advantages: Model advantages.
        model_resistances: Damage type resistances.
        feat: Feat description text (empty string if none).
        special_actions: Special action descriptions.
        special_attacks: Model special attacks.
        spells: Spell descriptions.
        special_rules: Model special rules.
        melee_weapons: Melee weapons carried by the model.
        range_weapons: Ranged weapons carried by the model.
        available_hardpoints: Weapon hardpoints available on the model, grouped
            as a list of hardpoint sets (each inner list is one set).
    """

    name: str
    vocal_names: list[str]
    faction: Faction
    basic_type: BasicType
    base_size: int
    cost: int
    short_name: str = ""
    model_statistics: ModelStatistics = field(default_factory=ModelStatistics)
    damage_system_type: DamageSystemType = DamageSystemType.BOX
    damage_system: AnyDamageSystem = field(default_factory=BoxDamageSystem)
    is_character: bool = False
    fa: int = -1
    armies: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    advantages: list[ModelAdvantage] = field(default_factory=list)
    model_resistances: list[ModelResistance] = field(default_factory=list)
    feat: str = ""
    special_actions: list[str] = field(default_factory=list)
    special_attacks: list[ModelSpecialAttack] = field(default_factory=list)
    spells: list[str] = field(default_factory=list)
    special_rules: list[ModelSpecialRule] = field(default_factory=list)
    melee_weapons: list[MeleeWeapon] = field(default_factory=list)
    range_weapons: list[RangeWeapon] = field(default_factory=list)
    available_hardpoints: list[list[Hardpoint]] = field(default_factory=list)
    troopers: list[TrooperEntry] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Validate field values after initialisation.

        Raises:
            ValueError: If any field contains an invalid value.
        """
        if self.basic_type not in _UNIT_TYPES and self.base_size not in BASE_SIZES:
            raise ValueError(
                f"base_size must be one of {BASE_SIZES}, got {self.base_size}"
            )
        if self.cost < 0:
            raise ValueError(f"cost must be >= 0, got {self.cost}")
        if self.fa < -1:
            raise ValueError(f"fa must be >= -1, got {self.fa}")

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-compatible dictionary.

        Returns:
            Dictionary representation suitable for direct use with
            :func:`json.dumps`.
        """
        if self.basic_type in _UNIT_TYPES:
            result: dict[str, Any] = {
                "name": self.name,
                "vocal_names": list(self.vocal_names),
                "faction": self.faction.value,
                "basic_type": self.basic_type.value,
                "cost": self.cost,
                "fa": self.fa,
                "armies": list(self.armies),
                "keywords": list(self.keywords),
                "troopers": [t.to_dict() for t in self.troopers],
            }
            if self.short_name:
                result["short_name"] = self.short_name
            return result
        return {
            "name": self.name,
            "short_name": self.short_name if self.is_character else "",
            "vocal_names": list(self.vocal_names),
            "faction": self.faction.value,
            "basic_type": self.basic_type.value,
            "base_size": self.base_size,
            "cost": self.cost,
            "model_statistics": self.model_statistics.to_dict(),
            "damage_system_type": self.damage_system_type.value,
            "damage_system": self.damage_system.to_dict(),
            "is_character": self.is_character,
            "fa": self.fa,
            "armies": list(self.armies),
            "keywords": list(self.keywords),
            "advantages": [adv.value for adv in self.advantages],
            "model_resistances": [r.value for r in self.model_resistances],
            "feat": self.feat,
            "special_actions": list(self.special_actions),
            "special_attacks": [a.name for a in self.special_attacks],
            "spells": list(self.spells),
            "special_rules": [r.name for r in self.special_rules],
            "melee_weapons": [w.to_dict() for w in self.melee_weapons],
            "range_weapons": [w.to_dict() for w in self.range_weapons],
            "available_hardpoints": [[h.to_dict() for h in group] for group in self.available_hardpoints],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ModelStatCard:
        """Deserialise from a dictionary produced by :meth:`to_dict`.

        Args:
            data: Dictionary as returned by :meth:`to_dict`.

        Returns:
            New :class:`ModelStatCard` instance.

        Raises:
            KeyError: If a required field is missing from *data*.
            ValueError: If a field value is invalid or an unknown enum
                value is encountered.
        """
        return cls(
            name=data["name"],
            vocal_names=list(data["vocal_names"]),
            short_name=str(data.get("short_name", "")),
            faction=Faction(data["faction"]),
            basic_type=BasicType(data["basic_type"]),
            base_size=int(data.get("base_size", BASE_SIZES[0])),
            cost=int(data["cost"]),
            model_statistics=ModelStatistics.from_dict(data.get("model_statistics", {})),
            damage_system_type=DamageSystemType(data.get("damage_system_type", DamageSystemType.BOX.value)),
            damage_system=damage_system_from_dict(
                DamageSystemType(data.get("damage_system_type", DamageSystemType.BOX.value)),
                data.get("damage_system", {}),
            ),
            is_character=bool(data.get("is_character", False)),
            fa=int(data.get("fa", -1)),
            armies=list(data.get("armies", [])),
            keywords=list(data.get("keywords", [])),
            advantages=[ModelAdvantage(adv) for adv in data.get("advantages", [])],
            model_resistances=[ModelResistance(r) for r in data.get("model_resistances", [])],
            feat=str(data.get("feat", "")),
            special_actions=list(data.get("special_actions", [])),
            special_attacks=[
                model_special_attack_from_name(a) for a in data.get("special_attacks", [])
            ],
            spells=list(data.get("spells", [])),
            special_rules=[model_special_rule_from_name(r) for r in data.get("special_rules", [])],
            melee_weapons=[
                MeleeWeapon.from_dict(w) for w in data.get("melee_weapons", [])
            ],
            range_weapons=[
                RangeWeapon.from_dict(w) for w in data.get("range_weapons", [])
            ],
            available_hardpoints=[
                [Hardpoint.from_dict(h) for h in group]
                for group in data.get("available_hardpoints", [])
            ],
            troopers=[
                TrooperEntry.from_dict(t) for t in data.get("troopers", [])
            ],
        )
