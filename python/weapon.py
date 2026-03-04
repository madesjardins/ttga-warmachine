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

"""Weapon module for the Warmachine game.

Defines melee and ranged weapon dataclasses and all related enums.
All classes are JSON-serializable via their :meth:`to_dict` / :meth:`from_dict`
pair.  A ``"weapon_type"`` discriminator key is included in every serialised
dictionary so that :func:`weapon_from_dict` can reconstruct the correct
concrete class without extra context.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Union


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class WeaponLocation(str, Enum):
    """Mount location of the weapon on the model.

    Values are intentionally kept as human-readable strings so they
    serialise cleanly to JSON without a custom encoder.
    """

    LEFT = "Left"
    RIGHT = "Right"
    HEAD = "Head"
    S = "S"
    ANY = "Any"


class WeaponQuality(str, Enum):
    """Special quality attached to a weapon.

    Values are intentionally kept as human-readable strings so they
    serialise cleanly to JSON without a custom encoder.
    """

    BLESSED = "Blessed"
    BUCKLER = "Buckler"
    CHAIN_WEAPON = "Chain Weapon"
    PISTOL = "Pistol"
    SHIELD = "Shield"
    THROW_POWER_ATTACK = "Throw Power Attack"
    WEAPON_MASTER = "Weapon Master"


class ContinuousEffect(str, Enum):
    """Continuous effect applied on hit.

    Values are intentionally kept as human-readable strings so they
    serialise cleanly to JSON without a custom encoder.
    """

    CORROSION = "Corrosion"
    FIRE = "Fire"


class CriticalEffect(str, Enum):
    """Effect triggered on a critical hit.

    Values are intentionally kept as human-readable strings so they
    serialise cleanly to JSON without a custom encoder.
    """

    CORROSION = "Corrosion"
    DISRUPTION = "Disruption"
    FIRE = "Fire"


class DamageType(str, Enum):
    """Elemental or special damage type dealt by the weapon.

    Values are intentionally kept as human-readable strings so they
    serialise cleanly to JSON without a custom encoder.
    """

    COLD = "Cold"
    CORROSION = "Corrosion"
    ELECTRICITY = "Electricity"
    FIRE = "Fire"
    MAGICAL = "Magical"


class RangeWeaponType(str, Enum):
    """Delivery mechanism for a ranged weapon.

    Values are intentionally kept as human-readable strings so they
    serialise cleanly to JSON without a custom encoder.
    """

    SHOT = "Shot"
    SPRAY = "Spray"
    AREA_OF_EFFECT = "Area of Effect"


# ---------------------------------------------------------------------------
# Discriminator constants
# ---------------------------------------------------------------------------

_WEAPON_TYPE_MELEE = "melee"
_WEAPON_TYPE_RANGE = "range"


# ---------------------------------------------------------------------------
# MeleeWeapon
# ---------------------------------------------------------------------------


@dataclass
class MeleeWeapon:
    """A melee weapon carried by a Warmachine model.

    Attributes:
        location: Mount location on the model.
        range: Weapon reach in inches.
        power: Power stat (P).
        weapon_qualities: Special qualities of the weapon.
    """

    location: WeaponLocation
    range: int
    power: int
    name: str = ""
    two_x: bool = False
    weapon_qualities: list[WeaponQuality] = field(default_factory=list)
    continuous_effects: list[ContinuousEffect] = field(default_factory=list)
    critical_effects: list[CriticalEffect] = field(default_factory=list)
    damage_types: list[DamageType] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-compatible dictionary.

        A ``"weapon_type"`` discriminator key is included so that
        :func:`weapon_from_dict` can reconstruct the correct class.

        Returns:
            Dictionary representation suitable for direct use with
            :func:`json.dumps`.
        """
        return {
            "weapon_type": _WEAPON_TYPE_MELEE,
            "name": self.name,
            "location": self.location.value,
            "range": self.range,
            "power": self.power,
            "two_x": self.two_x,
            "weapon_qualities": [q.value for q in self.weapon_qualities],
            "continuous_effects": [e.value for e in self.continuous_effects],
            "critical_effects": [e.value for e in self.critical_effects],
            "damage_types": [t.value for t in self.damage_types],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MeleeWeapon:
        """Deserialise from a dictionary produced by :meth:`to_dict`.

        Args:
            data: Dictionary as returned by :meth:`to_dict`.

        Returns:
            New :class:`MeleeWeapon` instance.

        Raises:
            KeyError: If a required field is missing from *data*.
            ValueError: If a field value is invalid or an unknown enum
                value is encountered.
        """
        return cls(
            location=WeaponLocation(data["location"]),
            range=int(data["range"]),
            power=int(data["power"]),
            name=str(data.get("name", "")),
            two_x=bool(data.get("two_x", False)),
            weapon_qualities=[WeaponQuality(q) for q in data.get("weapon_qualities", [])],
            continuous_effects=[ContinuousEffect(e) for e in data.get("continuous_effects", [])],
            critical_effects=[CriticalEffect(e) for e in data.get("critical_effects", [])],
            damage_types=[DamageType(t) for t in data.get("damage_types", [])],
        )


# ---------------------------------------------------------------------------
# RangeWeapon
# ---------------------------------------------------------------------------


@dataclass
class RangeWeapon:
    """A ranged weapon carried by a Warmachine model.

    Attributes:
        location: Mount location on the model.
        range: Maximum range in inches.
        power: Power stat (P).
        rate_of_fire: Number of shots per activation (ROF).
        range_weapon_type: Delivery mechanism (Shot, Spray or Area of Effect).
        area_of_effect: Blast template diameter in inches (0 if not applicable).
        blast_power: Power of the blast damage (0 if not applicable).
        weapon_qualities: Special qualities of the weapon.
    """

    location: WeaponLocation
    range: int
    power: int
    name: str = ""
    two_x: bool = False
    rof_dice: int = 0
    rof_flat: int = 1
    range_weapon_type: RangeWeaponType = RangeWeaponType.SHOT
    area_of_effect: int = 0
    blast_power: int = 0
    weapon_qualities: list[WeaponQuality] = field(default_factory=list)
    continuous_effects: list[ContinuousEffect] = field(default_factory=list)
    critical_effects: list[CriticalEffect] = field(default_factory=list)
    damage_types: list[DamageType] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-compatible dictionary.

        A ``"weapon_type"`` discriminator key is included so that
        :func:`weapon_from_dict` can reconstruct the correct class.

        Returns:
            Dictionary representation suitable for direct use with
            :func:`json.dumps`.
        """
        return {
            "weapon_type": _WEAPON_TYPE_RANGE,
            "name": self.name,
            "location": self.location.value,
            "range": self.range,
            "power": self.power,
            "two_x": self.two_x,
            "rof_dice": self.rof_dice,
            "rof_flat": self.rof_flat,
            "range_weapon_type": self.range_weapon_type.value,
            "area_of_effect": self.area_of_effect,
            "blast_power": self.blast_power,
            "weapon_qualities": [q.value for q in self.weapon_qualities],
            "continuous_effects": [e.value for e in self.continuous_effects],
            "critical_effects": [e.value for e in self.critical_effects],
            "damage_types": [t.value for t in self.damage_types],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RangeWeapon:
        """Deserialise from a dictionary produced by :meth:`to_dict`.

        Args:
            data: Dictionary as returned by :meth:`to_dict`.

        Returns:
            New :class:`RangeWeapon` instance.

        Raises:
            KeyError: If a required field is missing from *data*.
            ValueError: If a field value is invalid or an unknown enum
                value is encountered.
        """
        old_rof = int(data.get("rate_of_fire", 1))
        return cls(
            location=WeaponLocation(data["location"]),
            range=int(data["range"]),
            power=int(data["power"]),
            name=str(data.get("name", "")),
            two_x=bool(data.get("two_x", False)),
            rof_dice=int(data.get("rof_dice", 0)),
            rof_flat=int(data.get("rof_flat", old_rof)),
            range_weapon_type=RangeWeaponType(data.get("range_weapon_type", RangeWeaponType.SHOT.value)),
            area_of_effect=int(data.get("area_of_effect", 0)),
            blast_power=int(data.get("blast_power", 0)),
            weapon_qualities=[WeaponQuality(q) for q in data.get("weapon_qualities", [])],
            continuous_effects=[ContinuousEffect(e) for e in data.get("continuous_effects", [])],
            critical_effects=[CriticalEffect(e) for e in data.get("critical_effects", [])],
            damage_types=[DamageType(t) for t in data.get("damage_types", [])],
        )


# ---------------------------------------------------------------------------
# Hardpoint
# ---------------------------------------------------------------------------


@dataclass
class Hardpoint:
    """A weapon hardpoint available on a Warmachine model.

    Attributes:
        name: Display name of the hardpoint.
        location: Mount location on the model.
    """

    name: str
    location: WeaponLocation

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-compatible dictionary.

        Returns:
            Dictionary representation suitable for direct use with
            :func:`json.dumps`.
        """
        return {
            "name": self.name,
            "location": self.location.value,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Hardpoint:
        """Deserialise from a dictionary produced by :meth:`to_dict`.

        Args:
            data: Dictionary as returned by :meth:`to_dict`.

        Returns:
            New :class:`Hardpoint` instance.

        Raises:
            KeyError: If a required field is missing from *data*.
            ValueError: If an unknown enum value is encountered.
        """
        return cls(
            name=str(data["name"]),
            location=WeaponLocation(data["location"]),
        )


# ---------------------------------------------------------------------------
# Union type alias and factory helper
# ---------------------------------------------------------------------------


AnyWeapon = Union[MeleeWeapon, RangeWeapon]
"""Type alias for any concrete weapon."""


def weapon_from_dict(data: dict[str, Any]) -> AnyWeapon:
    """Deserialise a weapon using the ``"weapon_type"`` discriminator.

    Args:
        data: Serialised weapon dictionary as returned by the corresponding
            ``to_dict`` method.  Must contain a ``"weapon_type"`` key with
            value ``"melee"`` or ``"range"``.

    Returns:
        Concrete weapon instance matching the discriminator.

    Raises:
        ValueError: If ``"weapon_type"`` is missing or not a recognised value.
    """
    weapon_type = data.get("weapon_type")
    if weapon_type == _WEAPON_TYPE_MELEE:
        return MeleeWeapon.from_dict(data)
    if weapon_type == _WEAPON_TYPE_RANGE:
        return RangeWeapon.from_dict(data)
    raise ValueError(f"Unknown weapon_type discriminator: {weapon_type!r}")
