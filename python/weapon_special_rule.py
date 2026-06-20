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

"""Weapon special rules for the Warmachine game.

Defines the :class:`WeaponSpecialRule` base class, result value types such as
:class:`RollModifier`, and all concrete rule implementations.

Adding a new rule
-----------------
1. Subclass :class:`WeaponSpecialRule` and set a ``name`` class attribute.
2. Override whichever attack-phase methods are relevant; leave the rest to
   return ``None`` / ``None`` via the base-class defaults.
3. Register the class by adding it to the ``_RULE_CLASSES`` list near the
   bottom of this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class Duration(str, Enum):
    """How long an effect placed on a model remains active."""

    GAME = "Game"
    ROUND = "Round"
    TURN_PLAYER = "Turn Player"
    TURN_OPPONENT = "Turn Opponent"
    ACTIVATION_PLAYER = "Activation Player"
    ACTIVATION_OPPONENT = "Activation Opponent"
    ONCE_MORE = "Once More"


# ---------------------------------------------------------------------------
# Result value types
# ---------------------------------------------------------------------------


@dataclass
class RollModifier:
    """Modifier applied to an attack or damage roll.

    Attributes:
        attack_roll_dice: Extra dice added to the attack roll.
        damage_roll_dice: Extra dice added to the damage roll.
    """

    attack_roll_dice: int = 0
    damage_roll_dice: int = 0


@dataclass
class NextAutomaticHit:
    """Effect that causes future attacks against the tagged model to auto-hit.

    Attributes:
        from_same_player: Auto-hit applies to attacks from the same player.
        from_same_unit: Auto-hit applies to attacks from the same unit.
        from_same_model: Auto-hit applies to attacks from the same model.
        from_same_weapon: Auto-hit applies only from the same weapon.
        is_ranged_attack: Only ranged attacks benefit.
        is_melee_attack: Only melee attacks benefit.
        is_arcane_attack: Only arcane attacks benefit.
        player: Specific player instance the restriction applies to.
        unit: Specific unit instance the restriction applies to.
        model: Specific model instance the restriction applies to.
        weapon_name: Specific weapon name the restriction applies to.
        duration: How long this effect persists.
    """

    from_same_player: bool = False
    from_same_unit: bool = False
    from_same_model: bool = False
    from_same_weapon: bool = False
    is_ranged_attack: bool = False
    is_melee_attack: bool = False
    is_arcane_attack: bool = False
    player: Any = None
    unit: Any = None
    model: Any = None
    weapon_name: str = ""
    duration: Optional[Duration] = None


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------


class WeaponSpecialRule:
    """Base class for all weapon special rules.

    Subclasses override the phase methods that are relevant to the rule and
    return an appropriate result object.  The base implementations all return
    ``None``, meaning "no effect at this phase".

    Attributes:
        name: Human-readable name of the rule, used for serialisation and
            display.  Must be unique across all registered rules.
    """

    name: str = ""

    def before_hit(
        self,
        is_direct: bool,
        attacked_model: Any = None,
    ) -> Optional[RollModifier]:
        """Called before the attack roll is made.

        Args:
            is_direct: ``True`` when the attack targets a model directly
                (as opposed to blast/spray collateral).
            attacked_model: The model being attacked.  Future implementations
                will query this model for active :class:`NextAutomaticHit`
                effects to determine whether this attack auto-hits.  For now
                this parameter is unused and ``None`` is always returned.

        Returns:
            A :class:`RollModifier` to apply, or ``None`` for no effect.
        """
        return None

    def on_hit(
        self,
        is_direct: bool,
        is_successful: bool,
        is_critical: bool,
    ) -> Optional[NextAutomaticHit]:
        """Called after the attack roll result is known.

        Args:
            is_direct: ``True`` for a direct hit target.
            is_successful: ``True`` if the attack roll succeeded.
            is_critical: ``True`` if the roll was a critical hit.

        Returns:
            A :class:`NextAutomaticHit` effect to place on the target, or
            ``None`` for no effect.
        """

    def before_damage(self, is_direct: bool) -> Optional[RollModifier]:
        """Called before the damage roll is made.

        Args:
            is_direct: ``True`` when this is the directly-hit target.

        Returns:
            A :class:`RollModifier` to apply, or ``None`` for no effect.
        """
        return None

    def on_damage(
        self,
        is_direct: bool,
        is_successful: bool,
        is_critical: bool,
    ) -> None:
        """Called after the damage roll result is known.

        Args:
            is_direct: ``True`` for the directly-hit target.
            is_successful: ``True`` if the damage roll dealt damage.
            is_critical: ``True`` if the roll was a critical hit.
        """

    def on_disabled(self) -> None:
        """Called when the target model is disabled by this weapon."""


# ---------------------------------------------------------------------------
# Concrete rules
# ---------------------------------------------------------------------------


class ElectricalCurrent(WeaponSpecialRule):
    """If this attack hits a model during this unit's activation, ranged
    attacks against that model made by models in this unit later this
    activation automatically hit.
    """

    name = "Electrical Current"

    def on_hit(
        self,
        is_direct: bool,
        is_successful: bool,
        is_critical: bool,
    ) -> Optional[NextAutomaticHit]:
        if is_successful:
            return NextAutomaticHit(
                from_same_unit=True,
                is_ranged_attack=True,
                duration=Duration.ACTIVATION_OPPONENT,
            )
        return None


class BrutalDamage(WeaponSpecialRule):
    """On a direct hit, gain an additional die on this weapon's damage rolls
    against the target directly hit.
    """

    name = "Brutal Damage"

    def before_damage(self, is_direct: bool) -> Optional[RollModifier]:
        if is_direct:
            return RollModifier(damage_roll_dice=1)
        return None


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_RULE_CLASSES: list[type[WeaponSpecialRule]] = [
    BrutalDamage,
    ElectricalCurrent,
]

_REGISTRY: dict[str, type[WeaponSpecialRule]] = {
    cls.name: cls for cls in _RULE_CLASSES
}


def all_rule_names() -> list[str]:
    """Return the sorted list of all registered weapon special rule names."""
    return sorted(_REGISTRY.keys())


def weapon_special_rule_from_name(name: str) -> WeaponSpecialRule:
    """Instantiate a :class:`WeaponSpecialRule` by its registered name.

    Args:
        name: The ``name`` attribute of the desired rule class.

    Returns:
        A new instance of the matching rule class.

    Raises:
        ValueError: If *name* does not match any registered rule.
    """
    cls = _REGISTRY.get(name)
    if cls is None:
        raise ValueError(f"Unknown weapon special rule: {name!r}")
    return cls()
