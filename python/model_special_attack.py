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

"""Model special actions and attacks for the Warmachine game.

Defines the :class:`ModelSpecialAction` base class, the
:class:`SpecialActionType` enum, and all concrete special action/attack
implementations.

Design notes
------------
Special attacks and special actions share the same data structure. The only
fundamental difference is that a *special attack* requires a dice roll (attack
roll) to succeed, while a *special action* automatically succeeds. This
distinction is captured by the :class:`SpecialActionType` enum field
``action_type``.

Special actions/attacks are structurally closer to ranged weapons (they
mostly have a RNG / POW / AOE) than to model special rules, so
:class:`ModelSpecialAction` borrows that shape directly (``range``, ``power``,
``blast_power``, ``area_of_effect``), plus a handful of fields for
buff/utility actions that grant another rule for a limited
:class:`~.weapon_special_rule.Duration` (reusing the same ``Duration`` enum
used by weapon special rules).

Magic Ability
~~~~~~~~~~~~~
Many special actions/attacks are a "Magic Ability": a special action/attack
that a caster model can use as part of its normal spellcasting. This is
modelled as the boolean flag :attr:`ModelSpecialAction.is_magic_ability`
rather than a subclass, since it is an orthogonal property (most other
fields still apply identically) shared by a large fraction of entries.

**Performing a Magic Ability counts as casting a spell** for any rule that
cares about a model "casting a spell" this turn/round (e.g. Harmonious
Exaltation's own COST reduction, or upkeep-related interactions).

As with :mod:`model_special_rule`, the class docstring on each concrete
action is the verbatim rules text and is the source of truth; the
structured fields below are a best-effort extraction for programmatic use.

Adding a new special action/attack
----------------------------------
1. Subclass :class:`ModelSpecialAction`, set the ``name`` class attribute,
   and write the verbatim rule text as the class docstring.
2. Set ``action_type`` to :attr:`SpecialActionType.SPECIAL_ATTACK` or
   :attr:`SpecialActionType.SPECIAL_ACTION`.
3. Fill in whichever of ``is_magic_ability`` / ``is_arcane_attack`` /
   ``range`` / ``power`` / ``blast_power`` / ``area_of_effect`` / ``target``
   / ``duration`` / ``grants`` apply. Fields that don't cleanly generalise
   can be left at their defaults — the docstring remains authoritative.
4. Register the class by adding it to the ``_SPECIAL_ACTION_CLASSES`` list
   near the bottom of this module.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from .rule_primitives import (
    ActionType,
    AdditionalAction,
    EffectScope,
    ModelFilter as MF,
    Relationship,
    Resource,
    ResourceChange,
    Restriction,
    RestrictionSpec,
    RollModifier as RM,
    RollType,
    RollModKind,
    RuleEffect,
    ScopeKind,
    UsageLimit,
)
from .weapon_special_rule import Duration


# ---------------------------------------------------------------------------
# Enum
# ---------------------------------------------------------------------------


class SpecialActionType(Enum):
    """Type of a :class:`ModelSpecialAction`.

    Attributes:
        SPECIAL_ACTION: A special action that automatically succeeds
            (no attack roll needed).
        SPECIAL_ATTACK: A special attack that requires an attack roll
            to succeed.
    """

    SPECIAL_ACTION = "special_action"
    SPECIAL_ATTACK = "special_attack"


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------


class ModelSpecialAction:
    """Base class for all model special actions and attacks.

    Attributes:
        name: Human-readable name, used for serialisation and display.
            Must be unique across all registered special actions/attacks.
        action_type: Whether this entry is a special action (auto-succeeds)
            or a special attack (requires an attack roll).
        is_magic_ability: ``True`` if this is a Magic Ability. Performing
            it counts as casting a spell.
        is_arcane_attack: ``True`` if this is explicitly an arcane attack.
        range: Range in inches (RNG), or ``None`` if the action has no
            range (e.g. self-only effects) or the range is otherwise
            non-standard (see the docstring).
        power: Primary POW of the attack, or ``None`` if it deals no direct
            damage.
        blast_power: Secondary/blast POW (e.g. the second value in a
            ``POW X/Y`` attack), or ``None`` if not applicable.
        area_of_effect: Blast template diameter in inches (AOE), or ``0``
            if not applicable.
        target: Structured target filter, or ``None`` if not applicable /
            self-only.
        target_text: Short prose description of the valid target for
            display, kept alongside the structured ``target``.
        damage_type: Damage type of the blast (e.g. ``"Corrosion"``), or
            ``""`` if not applicable.
        blast_unboostable: ``True`` if the blast damage roll cannot be
            boosted.
        duration: How long a granted effect lasts, or ``None`` if not
            applicable.
        grants: Names of special rules/advantages granted by this action
            while ``duration`` applies. Resolved by name against the
            relevant registries by the caller.
        on_hit: Effects applied to models hit by this attack, reusing
            :class:`~.rule_primitives.RuleEffect`.
        effects: Non-attack effects on cast/use (resource changes,
            self-buffs), reusing :class:`~.rule_primitives.RuleEffect`.
        destroyed_removed_from_play: ``True`` if models destroyed by this
            attack are removed from play.
        no_corpse_tokens: ``True`` if destroyed models do not generate
            corpse tokens.
        caster_gains_souls: ``True`` if the caster gains soul tokens from
            living enemy models destroyed by this attack.
        expires_upkeeps: ``True`` if enemy upkeep spells/animi on the
            model/unit directly hit immediately expire.
        usage_limit: Usage limits for this action (e.g. once per turn per
            target).
    """

    name: str = ""
    action_type: SpecialActionType = SpecialActionType.SPECIAL_ACTION
    is_magic_ability: bool = False
    is_arcane_attack: bool = False
    range: Optional[float] = None
    power: Optional[int] = None
    blast_power: Optional[int] = None
    area_of_effect: int = 0
    target: Optional[MF] = None
    target_text: str = ""
    damage_type: str = ""
    blast_unboostable: bool = False
    duration: Optional[Duration] = None
    grants: tuple[str, ...] = ()
    on_hit: tuple[RuleEffect, ...] = ()
    effects: tuple[RuleEffect, ...] = ()
    destroyed_removed_from_play: bool = False
    no_corpse_tokens: bool = False
    caster_gains_souls: bool = False
    expires_upkeeps: bool = False
    usage_limit: Optional[UsageLimit] = None
    notes: str = ""


# ---------------------------------------------------------------------------
# Concrete special actions / attacks
# ---------------------------------------------------------------------------


class RitualsOfShadow(ModelSpecialAction):
    """Rituals of Shadow (Magic Ability).

    RNG 6. Target friendly horror. If the horror was in range, it gains 1
    essence point.
    """

    name = "Rituals of Shadow"
    is_magic_ability = True
    range = 6.0
    target = MF(relationship=Relationship.FRIENDLY, basic_types=("Horror",))
    target_text = "friendly horror"
    effects = (
        RuleEffect(resource_changes=(ResourceChange(resource=Resource.ESSENCE, amount=1),)),
    )


class TouchOfDarkness(ModelSpecialAction):
    """Touch of Darkness (Magic Ability).

    RNG 3. Target friendly living soulless model. If that model is in
    range, remove d3 damage points from it.
    """

    name = "Touch of Darkness"
    is_magic_ability = True
    range = 3.0
    target = MF(relationship=Relationship.FRIENDLY, is_living=True, advantages=("Soulless",))
    target_text = "friendly living soulless model"
    effects = (
        RuleEffect(resource_changes=(ResourceChange(resource=Resource.DAMAGE, amount=-1, dice="d3"),)),
    )


class HexBolt(ModelSpecialAction):
    """Hex Bolt (Magic Ability).

    RNG 6, POW 13 arcane attack. Models hit cannot make special actions,
    special attacks, or power attacks for one round.
    """

    name = "Hex Bolt"
    action_type = SpecialActionType.SPECIAL_ATTACK
    is_magic_ability = True
    is_arcane_attack = True
    range = 6.0
    power = 13
    on_hit = (
        RuleEffect(
            restrictions=(
                RestrictionSpec(restriction=Restriction.CANNOT_MAKE_SPECIAL_ACTIONS),
                RestrictionSpec(restriction=Restriction.CANNOT_MAKE_SPECIAL_ATTACKS),
                RestrictionSpec(restriction=Restriction.CANNOT_MAKE_POWER_ATTACKS),
            ),
            duration=Duration.ROUND,
        ),
    )


class Annihilation(ModelSpecialAction):
    """Annihilation (Magic Ability).

    RNG 10, AOE 2, POW 10/10 arcane attack. Models destroyed by
    Annihilation are removed from play and do not generate corpse tokens.
    When a living enemy model is destroyed by Annihilation, the spellcaster
    gains the destroyed model's soul token regardless of the proximity of
    other models.
    """

    name = "Annihilation"
    action_type = SpecialActionType.SPECIAL_ATTACK
    is_magic_ability = True
    is_arcane_attack = True
    range = 10.0
    area_of_effect = 2
    power = 10
    blast_power = 10
    destroyed_removed_from_play = True
    no_corpse_tokens = True
    caster_gains_souls = True


class CombatDrugs(ModelSpecialAction):
    """Combat Drugs.

    RNG 5. Target Cohort model in this model's battlegroup gains
    Aggressive for one turn.
    """

    name = "Combat Drugs"
    range = 5.0
    target = MF(relationship=Relationship.FRIENDLY, in_battlegroup=True, keywords=("Cohort",))
    target_text = "Cohort model in this model's battlegroup"
    duration = Duration.TURN_PLAYER
    grants = ("Aggressive",)


class Vitalizer(ModelSpecialAction):
    """Vitalizer.

    RNG 6. Target friendly monstrosity. If target monstrosity is in range,
    it gains 1 focus point.
    """

    name = "Vitalizer"
    range = 6.0
    target = MF(relationship=Relationship.FRIENDLY, basic_types=("Monstrosity",))
    target_text = "friendly monstrosity"
    effects = (
        RuleEffect(resource_changes=(ResourceChange(resource=Resource.FOCUS, amount=1),)),
    )


class HarmoniousExaltation(ModelSpecialAction):
    """Harmonious Exaltation (Magic Ability).

    RNG 5. Target this model's Leader. If it is in range, once this turn
    when the Leader casts a spell, reduce the COST of the spell by 1.
    """

    name = "Harmonious Exaltation"
    is_magic_ability = True
    range = 5.0
    target = MF(relationship=Relationship.FRIENDLY, notes="this model's Leader")
    target_text = "this model's Leader"
    effects = (
        RuleEffect(
            resource_changes=(ResourceChange(resource=Resource.SPELL_COST, amount=-1),),
            usage_limit=UsageLimit(per_turn=1),
        ),
    )


class SpellSlave(ModelSpecialAction):
    """Spell Slave (Magic Ability).

    This model must be in its Leader's control range to make the Spell
    Slave special action. When it does, it casts one of the spells on its
    Leader's card with a COST of 3 or less. This model cannot cast upkeep
    spells or spells with a RNG of SELF or CTRL. When casting an offensive
    spell, Spell Slave is an arcane attack.
    """

    name = "Spell Slave"
    action_type = SpecialActionType.SPECIAL_ACTION
    is_magic_ability = True
    target_text = "itself, while within its Leader's control range"


class HexBlast(ModelSpecialAction):
    """Hex Blast (Magic Ability).

    RNG 10, AOE 2, POW 13/8 arcane attack. Enemy upkeep spells and animi on
    the model/unit directly hit by Hex Blast immediately expire.
    """

    name = "Hex Blast"
    action_type = SpecialActionType.SPECIAL_ATTACK
    is_magic_ability = True
    is_arcane_attack = True
    range = 10.0
    area_of_effect = 2
    power = 13
    blast_power = 8
    expires_upkeeps = True


class Marionnette(ModelSpecialAction):
    """Marionnette (Magic Ability).

    RNG 10 arcane attack. Target enemy model/unit. You can have one
    affected model reroll one attack or damage roll, then Marionette
    expires. Marionette lasts for one round.
    """

    name = "Marionnette"
    action_type = SpecialActionType.SPECIAL_ATTACK
    is_magic_ability = True
    is_arcane_attack = True
    range = 10.0
    target = MF(relationship=Relationship.ENEMY)
    target_text = "enemy model/unit"
    on_hit = (
        RuleEffect(
            roll_modifiers=(
                RM(RollType.ATTACK, RollModKind.REROLL, once_per_roll=True),
            ),
            duration=Duration.ROUND,
            notes="One affected model rerolls one attack or damage roll, then expires",
        ),
    )


class PuppetMaster(ModelSpecialAction):
    """Puppet Master (Magic Ability).

    RNG 6. Target friendly model/unit. If the target model/unit is in
    range, you can have one affected model reroll one attack or damage
    roll, then Puppet Master expires. Puppet Master lasts for one round.
    """

    name = "Puppet Master"
    is_magic_ability = True
    range = 6.0
    target = MF(relationship=Relationship.FRIENDLY)
    target_text = "friendly model/unit"
    effects = (
        RuleEffect(
            roll_modifiers=(
                RM(RollType.ATTACK, RollModKind.REROLL, once_per_roll=True),
            ),
            duration=Duration.ROUND,
            notes="One affected model rerolls one attack or damage roll, then expires",
        ),
    )


class GripOfShadows(ModelSpecialAction):
    """Grip of Shadows (Magic Ability).

    This model gains Telemetry for one round.
    """

    name = "Grip of Shadows"
    is_magic_ability = True
    duration = Duration.ROUND
    grants = ("Telemetry",)


class WhispersAtTheGate(ModelSpecialAction):
    """Whispers at the Gate (Magic Ability).

    Remove 1 essence point from each enemy infernal model currently within
    5" of this model. Add 1 essence point to each friendly infernal model
    currently within 5" of this model.
    """

    name = "Whispers at the Gate"
    is_magic_ability = True
    range = 5.0
    effects = (
        RuleEffect(
            scope=EffectScope(kind=ScopeKind.PULSE, radius=5.0, filter=MF(relationship=Relationship.ENEMY, keywords=("Infernal",))),
            resource_changes=(ResourceChange(resource=Resource.ESSENCE, amount=-1),),
        ),
        RuleEffect(
            scope=EffectScope(kind=ScopeKind.PULSE, radius=5.0, filter=MF(relationship=Relationship.FRIENDLY, keywords=("Infernal",))),
            resource_changes=(ResourceChange(resource=Resource.ESSENCE, amount=1),),
        ),
    )


class WordOfRuin(ModelSpecialAction):
    """Word of Ruin (Magic Ability).

    This model gains Master of Ruin for one round.
    """

    name = "Word of Ruin"
    is_magic_ability = True
    duration = Duration.ROUND
    grants = ("Master of Ruin",)


class DarkCalling(ModelSpecialAction):
    """Dark Calling (Magic Ability).

    RNG 3. Target friendly horror. If the horror is in range, it
    immediately makes one basic melee or ranged attack. A model can be
    targeted by Dark Calling special action only once per turn.
    """

    name = "Dark Calling"
    action_type = SpecialActionType.SPECIAL_ACTION
    is_magic_ability = True
    range = 3.0
    target = MF(relationship=Relationship.FRIENDLY, basic_types=("Horror",))
    target_text = "friendly horror"
    effects = (
        RuleEffect(additional_action=AdditionalAction(action_type=ActionType.BASIC_MELEE_OR_RANGED_ATTACK)),
    )
    usage_limit = UsageLimit(per_turn=1)


class FlysKiss(ModelSpecialAction):
    """Fly's Kiss (Magic Ability).

    RNG 8, POW 12 arcane attack. If this attack boxes an enemy model,
    models within 2" of the boxed model suffer an unboostable POW 10
    corrosion blast damage roll, then the boxed model is removed from
    play.
    """

    name = "Fly's Kiss"
    action_type = SpecialActionType.SPECIAL_ATTACK
    is_magic_ability = True
    is_arcane_attack = True
    range = 8.0
    power = 12
    blast_power = 10
    damage_type = "Corrosion"
    blast_unboostable = True
    destroyed_removed_from_play = True
    notes = 'Models within 2" of the boxed model suffer an unboostable POW 10 corrosion blast damage roll'


class InvocationOfBitterestNight(ModelSpecialAction):
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

_SPECIAL_ACTION_CLASSES: list[type[ModelSpecialAction]] = [
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

_REGISTRY: dict[str, type[ModelSpecialAction]] = {
    cls.name: cls for cls in _SPECIAL_ACTION_CLASSES
}


def all_special_action_names() -> list[str]:
    """Return the sorted list of all registered model special action names."""
    return sorted(_REGISTRY.keys())


def model_special_action_from_name(name: str) -> ModelSpecialAction:
    """Instantiate a :class:`ModelSpecialAction` by its registered name.

    Args:
        name: The ``name`` attribute of the desired special action class.

    Returns:
        A new instance of the matching special action class.

    Raises:
        ValueError: If *name* does not match any registered special action.
    """
    cls = _REGISTRY.get(name)
    if cls is None:
        raise ValueError(f"Unknown model special action: {name!r}")
    return cls()


# --- Backward-compat aliases (deprecated, use the new names above) ---

ModelSpecialAttack = ModelSpecialAction


def all_special_attack_names() -> list[str]:
    """Backward-compat alias for :func:`all_special_action_names`."""
    return all_special_action_names()


def model_special_attack_from_name(name: str) -> ModelSpecialAction:
    """Backward-compat alias for :func:`model_special_action_from_name`."""
    return model_special_action_from_name(name)
