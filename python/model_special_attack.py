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

"""Model special attacks for the Warmachine game.

Defines the :class:`ModelSpecialAttack` base class and all concrete special
attack implementations.

Design notes
------------
Special attacks are structurally closer to ranged weapons (they mostly have
a RNG / POW / AOE) than to model special rules, so :class:`ModelSpecialAttack`
borrows that shape directly (``range``, ``power``, ``blast_power``,
``area_of_effect``), plus a handful of fields for buff/utility attacks that
grant another rule for a limited :class:`~.weapon_special_rule.Duration`
(reusing the same ``Duration`` enum used by weapon special rules).

Magic Ability
~~~~~~~~~~~~~
Many special attacks are a "Magic Ability": a special attack that a caster
model can use as part of its normal spellcasting. This is modelled as the
boolean flag :attr:`ModelSpecialAttack.is_magic_ability` rather than a
subclass, since it is an orthogonal property (most other fields still apply
identically) shared by a large fraction of special attacks.

**Performing a Magic Ability special attack counts as casting a spell** for
any rule that cares about a model "casting a spell" this turn/round (e.g.
Harmonious Exaltation's own COST reduction, or upkeep-related interactions).

A handful of entries are explicitly called out as a "special action" rather
than a "special attack" in their own rules text (e.g. Spell Slave, Dark
Calling); this is tracked with :attr:`ModelSpecialAttack.is_special_action`
without moving them to a separate module, since the surrounding UI/data
model treats "special attacks" as a single tag list on the model card.

As with :mod:`model_special_rule`, the class docstring on each concrete
attack is the verbatim rules text and is the source of truth; the
structured fields below are a best-effort extraction for programmatic use.

Adding a new special attack
----------------------------
1. Subclass :class:`ModelSpecialAttack`, set the ``name`` class attribute,
   and write the verbatim rule text as the class docstring.
2. Fill in whichever of ``is_magic_ability`` / ``is_special_action`` /
   ``is_arcane_attack`` / ``range`` / ``power`` / ``blast_power`` /
   ``area_of_effect`` / ``target`` / ``duration`` / ``grants`` apply. Fields
   that don't cleanly generalise can be left at their defaults — the
   docstring remains authoritative.
3. Register the class by adding it to the ``_SPECIAL_ATTACK_CLASSES`` list
   near the bottom of this module.
"""

from __future__ import annotations

from typing import Optional

from .weapon_special_rule import Duration


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------


class ModelSpecialAttack:
    """Base class for all model special attacks.

    Attributes:
        name: Human-readable name of the special attack, used for
            serialisation and display. Must be unique across all
            registered special attacks.
        is_magic_ability: ``True`` if this is a Magic Ability special
            attack. Performing it counts as casting a spell.
        is_special_action: ``True`` if this entry's own rules text calls it
            a special action rather than a special attack.
        is_arcane_attack: ``True`` if this attack is explicitly an arcane
            attack.
        range: Range in inches (RNG), or ``None`` if the attack has no
            range (e.g. self-only effects) or the range is otherwise
            non-standard (see the docstring).
        power: Primary POW of the attack, or ``None`` if it deals no direct
            damage.
        blast_power: Secondary/blast POW (e.g. the second value in a
            ``POW X/Y`` attack), or ``None`` if not applicable.
        area_of_effect: Blast template diameter in inches (AOE), or ``0``
            if not applicable.
        target: Short description of the valid target (e.g. "friendly
            horror"), or ``""`` if not applicable / self-only.
        duration: How long a granted effect lasts, or ``None`` if not
            applicable.
        grants: Names of special rules/advantages granted by this attack
            while ``duration`` applies. Resolved by name against the
            relevant registries by the caller.
    """

    name: str = ""
    is_magic_ability: bool = False
    is_special_action: bool = False
    is_arcane_attack: bool = False
    range: Optional[float] = None
    power: Optional[int] = None
    blast_power: Optional[int] = None
    area_of_effect: int = 0
    target: str = ""
    duration: Optional[Duration] = None
    grants: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Concrete special attacks
# ---------------------------------------------------------------------------


class RitualsOfShadow(ModelSpecialAttack):
    """Rituals of Shadow (Magic Ability).

    RNG 6. Target friendly horror. If the horror was in range, it gains 1
    essence point.
    """

    name = "Rituals of Shadow"
    is_magic_ability = True
    range = 6.0
    target = "friendly horror"


class TouchOfDarkness(ModelSpecialAttack):
    """Touch of Darkness (Magic Ability).

    RNG 3. Target friendly living soulless model. If that model is in
    range, remove d3 damage points from it.
    """

    name = "Touch of Darkness"
    is_magic_ability = True
    range = 3.0
    target = "friendly living soulless model"


class HexBolt(ModelSpecialAttack):
    """Hex Bolt (Magic Ability).

    RNG 6, POW 13 arcane attack. Models hit cannot make special actions,
    special attacks, or power attacks for one round.
    """

    name = "Hex Bolt"
    is_magic_ability = True
    is_arcane_attack = True
    range = 6.0
    power = 13
    duration = Duration.ROUND


class Annihilation(ModelSpecialAttack):
    """Annihilation (Magic Ability).

    RNG 10, AOE 2, POW 10/10 arcane attack. Models destroyed by
    Annihilation are removed from play and do not generate corpse tokens.
    When a living enemy model is destroyed by Annihilation, the spellcaster
    gains the destroyed model's soul token regardless of the proximity of
    other models.
    """

    name = "Annihilation"
    is_magic_ability = True
    is_arcane_attack = True
    range = 10.0
    area_of_effect = 2
    power = 10
    blast_power = 10


class CombatDrugs(ModelSpecialAttack):
    """Combat Drugs.

    RNG 5. Target Cohort model in this model's battlegroup gains
    Aggressive for one turn.
    """

    name = "Combat Drugs"
    range = 5.0
    target = "Cohort model in this model's battlegroup"
    duration = Duration.TURN_PLAYER
    grants = ("Aggressive",)


class Vitalizer(ModelSpecialAttack):
    """Vitalizer.

    RNG 6. Target friendly monstrosity. If target monstrosity is in range,
    it gains 1 focus point.
    """

    name = "Vitalizer"
    range = 6.0
    target = "friendly monstrosity"


class HarmoniousExaltation(ModelSpecialAttack):
    """Harmonious Exaltation (Magic Ability).

    RNG 5. Target this model's Leader. If it is in range, once this turn
    when the Leader casts a spell, reduce the COST of the spell by 1.
    """

    name = "Harmonious Exaltation"
    is_magic_ability = True
    range = 5.0
    target = "this model's Leader"
    duration = Duration.TURN_PLAYER


class SpellSlave(ModelSpecialAttack):
    """Spell Slave (Magic Ability).

    This model must be in its Leader's control range to make the Spell
    Slave special action. When it does, it casts one of the spells on its
    Leader's card with a COST of 3 or less. This model cannot cast upkeep
    spells or spells with a RNG of SELF or CTRL. When casting an offensive
    spell, Spell Slave is an arcane attack.
    """

    name = "Spell Slave"
    is_magic_ability = True
    is_special_action = True
    target = "itself, while within its Leader's control range"


class HexBlast(ModelSpecialAttack):
    """Hex Blast (Magic Ability).

    RNG 10, AOE 2, POW 13/8 arcane attack. Enemy upkeep spells and animi on
    the model/unit directly hit by Hex Blast immediately expire.
    """

    name = "Hex Blast"
    is_magic_ability = True
    is_arcane_attack = True
    range = 10.0
    area_of_effect = 2
    power = 13
    blast_power = 8


class Marionnette(ModelSpecialAttack):
    """Marionnette (Magic Ability).

    RNG 10 arcane attack. Target enemy model/unit. You can have one
    affected model reroll one attack or damage roll, then Marionette
    expires. Marionette lasts for one round.
    """

    name = "Marionnette"
    is_magic_ability = True
    is_arcane_attack = True
    range = 10.0
    target = "enemy model/unit"
    duration = Duration.ROUND


class PuppetMaster(ModelSpecialAttack):
    """Puppet Master (Magic Ability).

    RNG 6. Target friendly model/unit. If the target model/unit is in
    range, you can have one affected model reroll one attack or damage
    roll, then Puppet Master expires. Puppet Master lasts for one round.
    """

    name = "Puppet Master"
    is_magic_ability = True
    range = 6.0
    target = "friendly model/unit"
    duration = Duration.ROUND


class GripOfShadows(ModelSpecialAttack):
    """Grip of Shadows (Magic Ability).

    This model gains Telemetry for one round.
    """

    name = "Grip of Shadows"
    is_magic_ability = True
    duration = Duration.ROUND
    grants = ("Telemetry",)


class WhispersAtTheGate(ModelSpecialAttack):
    """Whispers at the Gate (Magic Ability).

    Remove 1 essence point from each enemy infernal model currently within
    5" of this model. Add 1 essence point to each friendly infernal model
    currently within 5" of this model.
    """

    name = "Whispers at the Gate"
    is_magic_ability = True
    range = 5.0


class WordOfRuin(ModelSpecialAttack):
    """Word of Ruin (Magic Ability).

    This model gains Master of Ruin for one round.
    """

    name = "Word of Ruin"
    is_magic_ability = True
    duration = Duration.ROUND
    grants = ("Master of Ruin",)


class DarkCalling(ModelSpecialAttack):
    """Dark Calling (Magic Ability).

    RNG 3. Target friendly horror. If the horror is in range, it
    immediately makes one basic melee or ranged attack. A model can be
    targeted by Dark Calling special action only once per turn.
    """

    name = "Dark Calling"
    is_magic_ability = True
    is_special_action = True
    range = 3.0
    target = "friendly horror"


class FlysKiss(ModelSpecialAttack):
    """Fly's Kiss (Magic Ability).

    RNG 8, POW 12 arcane attack. If this attack boxes an enemy model,
    models within 2" of the boxed model suffer an unboostable POW 10
    corrosion blast damage roll, then the boxed model is removed from
    play.
    """

    name = "Fly's Kiss"
    is_magic_ability = True
    is_arcane_attack = True
    range = 8.0
    power = 12
    blast_power = 10


class InvocationOfBitterestNight(ModelSpecialAttack):
    """Invocation of Bitterest Night (Magic Ability).

    This model gains Stealth and Black Mantle for one round.
    """

    name = "Invocation of Bitterest Night"
    is_magic_ability = True
    duration = Duration.ROUND
    grants = ("Stealth", "Black Mantle")


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_SPECIAL_ATTACK_CLASSES: list[type[ModelSpecialAttack]] = [
    RitualsOfShadow,
    TouchOfDarkness,
    HexBolt,
    Annihilation,
    CombatDrugs,
    Vitalizer,
    HarmoniousExaltation,
    SpellSlave,
    HexBlast,
    Marionnette,
    PuppetMaster,
    GripOfShadows,
    WhispersAtTheGate,
    WordOfRuin,
    DarkCalling,
    FlysKiss,
    InvocationOfBitterestNight,
]

_REGISTRY: dict[str, type[ModelSpecialAttack]] = {
    cls.name: cls for cls in _SPECIAL_ATTACK_CLASSES
}


def all_special_attack_names() -> list[str]:
    """Return the sorted list of all registered model special attack names."""
    return sorted(_REGISTRY.keys())


def model_special_attack_from_name(name: str) -> ModelSpecialAttack:
    """Instantiate a :class:`ModelSpecialAttack` by its registered name.

    Args:
        name: The ``name`` attribute of the desired special attack class.

    Returns:
        A new instance of the matching special attack class.

    Raises:
        ValueError: If *name* does not match any registered special attack.
    """
    cls = _REGISTRY.get(name)
    if cls is None:
        raise ValueError(f"Unknown model special attack: {name!r}")
    return cls()
