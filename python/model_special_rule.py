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

"""Model special rules for the Warmachine game.

Defines the :class:`ModelSpecialRule` base class, its supporting enums and
value types (:class:`Timing`, :class:`GrantScope`, :class:`ActionType`,
:class:`StatBonus`, :class:`AdditionalAction`,
:class:`ModelSpecialRuleEffect`), and all concrete rule implementations.

Design notes
------------
Model special rules are far less mechanically uniform than weapon special
rules: some are always-on conditional bonuses, some trigger once on a
specific event, some grant an extra action, some grant *other* rules, and a
few restrict what other models may do. Rather than modelling every nuance
precisely, each rule stores:

- A verbatim rules-text docstring (the source of truth for anything not
  captured structurally).
- One or more :class:`ModelSpecialRuleEffect` entries in :attr:`effects`,
  giving *best-effort* structured metadata (:class:`Timing`, a short
  ``trigger``/``condition`` description, an optional :class:`StatBonus`,
  an optional :class:`AdditionalAction`, and any rules/advantages/
  resistances ``granted`` by name).

Most rules have exactly one effect. A few real rules (e.g. Alchemical Mask)
bundle several distinct effects into a single named rule; those define more
than one entry in :attr:`effects`.

"Granted", "Drive", and "Field Marshal" are not separate rules themselves —
they are prefixes that can be applied to *any* rule on a specific model
card to change who benefits from it:

- **Granted**: while this model is in play, models in its unit receive the
  rule (in addition to, or instead of, this model itself, depending on the
  rule).
- **Drive**: while within a radius of this model, a warjack under its
  control gains the rule. This model does not have the rule itself.
- **Field Marshal**: cohort models in this model's battlegroup gain the
  rule. This model does not have the rule itself.

These are represented as the *instance* attributes :attr:`~ModelSpecialRule.
grant_scope` and :attr:`~ModelSpecialRule.grant_radius` on
:class:`ModelSpecialRule`, left at their ``GrantScope.SELF`` default and
reconfigured per model card when a "Granted:", "Drive:", or "Field
Marshal:" prefix applies.

Bracketed values such as ``Ionization [X]`` or ``Reposition [X]`` are
represented by the instance attribute :attr:`~ModelSpecialRule.argument`,
left ``None`` on the class and set per model card to the resolved value.

Adding a new rule
------------------
1. Subclass :class:`ModelSpecialRule`, set the ``name`` class attribute, and
   write the verbatim rule text as the class docstring.
2. Define one (or more) :class:`ModelSpecialRuleEffect` in ``effects``,
   filling in whichever of ``timing`` / ``trigger`` / ``condition`` /
   ``stat_bonus`` / ``additional_action`` / ``grants`` apply. Fields that
   don't cleanly generalise can be left at their defaults — the docstring
   remains the authoritative definition.
3. Register the class by adding it to the ``_RULE_CLASSES`` list near the
   bottom of this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class Timing(str, Enum):
    """When a special rule's effect takes place relative to the game
    sequence.
    """

    CONTINUOUS = "Continuous"
    ON_MELEE_ATTACK_DESTROYS_MODEL = "On Melee Attack Destroys Model"
    ON_MODEL_DESTROYED = "On Model Destroyed"
    ON_ATTACK_MISSED_SELF = "On Attack Missed Self"
    ON_DAMAGE_ROLL = "On Damage Roll"
    REPLACES_DAMAGE_ROLL = "Replaces Damage Roll"
    ON_COMBINED_ATTACK_MISSED = "On Combined Attack Missed"
    START_OF_MAINTENANCE_PHASE = "Start Of Maintenance Phase"
    END_OF_ACTIVATION = "End Of Activation"
    AFTER_ADVANCE_BEFORE_COMBAT_ACTION = "After Advance Before Combat Action"
    ONCE_PER_GAME = "Once Per Game"


class GrantScope(str, Enum):
    """How a special rule's benefit is shared with other models.

    See the module docstring for the precise meaning of each value.
    """

    SELF = "Self"
    GRANTED = "Granted"
    DRIVE = "Drive"
    FIELD_MARSHAL = "Field Marshal"


class ActionType(str, Enum):
    """Kind of extra action a model may perform as a result of a special
    rule.
    """

    BASIC_MELEE_ATTACK = "Basic Melee Attack"
    BASIC_RANGED_ATTACK = "Basic Ranged Attack"
    ADVANCE = "Advance"
    FULL_ADVANCE = "Full Advance"
    PLACEMENT = "Placement"
    VENGEANCE_MOVE = "Vengeance Move"


# ---------------------------------------------------------------------------
# Value types
# ---------------------------------------------------------------------------


@dataclass
class StatBonus:
    """A modifier to combat statistics or attack rolls granted while a
    special rule's condition holds.

    Attributes:
        def_bonus: Bonus applied to this model's DEF.
        arm_bonus: Bonus applied to this model's ARM.
        attack_roll_bonus: Bonus (or penalty, if negative) applied to attack
            rolls. Combined with :attr:`against_attacker` to determine
            whose roll it applies to.
        against_attacker: If ``True``, ``attack_roll_bonus`` applies to
            rolls made by the *attacker* targeting this model, rather than
            to a roll made by this model (e.g. Set Defense's penalty to
            attackers).
        ranged_only: Restrict the bonus to ranged attacks.
        melee_only: Restrict the bonus to melee attacks.
        charge_or_slam_only: Restrict the bonus to charge or slam power
            attacks.
        immune_to_knockdown: If ``True``, this model cannot be knocked down
            while the condition holds.
    """

    def_bonus: int = 0
    arm_bonus: int = 0
    attack_roll_bonus: int = 0
    against_attacker: bool = False
    ranged_only: bool = False
    melee_only: bool = False
    charge_or_slam_only: bool = False
    immune_to_knockdown: bool = False


@dataclass
class AdditionalAction:
    """An extra action granted by a special rule.

    Attributes:
        action_type: Kind of action granted.
        max_distance: Maximum advance/placement distance in inches, or
            ``None`` if not applicable / not a fixed value (e.g. resolved
            from :attr:`ModelSpecialRule.argument` at runtime).
        target: Description of the valid target for an attack action (e.g.
            ``"the attacking model"``), or ``""`` if unrestricted.
        max_per_activation: Maximum number of times this action can be
            granted per activation, or ``None`` if unlimited.
        max_per_turn: Maximum number of times this action can be granted
            per turn, or ``None`` if unlimited.
        max_per_game: Maximum number of times this action can be granted
            per game, or ``None`` if unlimited.
    """

    action_type: ActionType
    max_distance: Optional[float] = None
    target: str = ""
    max_per_activation: Optional[int] = None
    max_per_turn: Optional[int] = None
    max_per_game: Optional[int] = None


@dataclass
class ModelSpecialRuleEffect:
    """A single discrete effect produced by a model special rule.

    A rule with only one effect (the common case) defines a single-item
    :attr:`ModelSpecialRule.effects` tuple. Rules with multiple distinct
    effects (e.g. Alchemical Mask) define more than one.

    Attributes:
        timing: When this effect takes place.
        trigger: Short description of the event that causes this effect to
            be checked, for discrete (non-continuous) timings.
        condition: Additional qualifying condition text, e.g. an ongoing
            state that must hold (used mainly for ``Timing.CONTINUOUS``
            effects), or descriptive text for effects that don't cleanly
            map onto the structured fields below.
        stat_bonus: Stat / roll modifier granted by this effect, if any.
        additional_action: Extra action granted by this effect, if any.
        grants: Names of other special rules, advantages, or resistances
            granted to this model while this effect applies. Resolved by
            name against the relevant registries by the caller.
    """

    timing: Timing = Timing.CONTINUOUS
    trigger: str = ""
    condition: str = ""
    stat_bonus: Optional[StatBonus] = None
    additional_action: Optional[AdditionalAction] = None
    grants: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------


class ModelSpecialRule:
    """Base class for all model special rules.

    Attributes:
        name: Human-readable name of the rule, used for serialisation and
            display. Must be unique across all registered rules.
        argument: Resolved value of a bracketed ``[X]`` parameter in the
            rule's name (e.g. the distance for ``Ionization [X]``). ``None``
            on the class; set per instance to the value used by a specific
            model.
        radius: Fixed aura radius in inches for continuous, distance-based
            effects (e.g. Tactician's 10"). ``None`` if not applicable.
        grant_scope: How this rule's benefit is shared. Defaults to
            :attr:`GrantScope.SELF` (the model itself has the rule).
            Reconfigure per instance to represent a "Granted:", "Drive:",
            or "Field Marshal:" prefixed rule on a specific model card.
        grant_radius: Aura radius in inches used with
            :attr:`GrantScope.DRIVE` (e.g. "while within 10\" of this
            model..."). ``None`` for other scopes or when not applicable.
        effects: The discrete effect(s) produced by this rule. Most rules
            define exactly one; a few define several.
    """

    name: str = ""
    argument: Optional[float] = None
    radius: Optional[float] = None
    grant_scope: GrantScope = GrantScope.SELF
    grant_radius: Optional[float] = None
    effects: tuple[ModelSpecialRuleEffect, ...] = ()


# ---------------------------------------------------------------------------
# Concrete rules
# ---------------------------------------------------------------------------


class QuickWork(ModelSpecialRule):
    """Quick Work.

    When this model destroys one or more enemy models with a melee attack
    during its Combat Action, immediately after that attack is resolved
    this model can make one basic ranged attack.
    """

    name = "Quick Work"
    effects = (
        ModelSpecialRuleEffect(
            timing=Timing.ON_MELEE_ATTACK_DESTROYS_MODEL,
            trigger="Destroys one or more enemy models with a melee attack during its Combat Action",
            additional_action=AdditionalAction(action_type=ActionType.BASIC_RANGED_ATTACK),
        ),
    )


class IronSentinel(ModelSpecialRule):
    """Iron Sentinel.

    While B2B (base to base) with a friendly Faction Cohort model, this
    model gains +2 DEF and ARM and cannot be knocked down.
    """

    name = "Iron Sentinel"
    effects = (
        ModelSpecialRuleEffect(
            timing=Timing.CONTINUOUS,
            condition="While B2B with a friendly Faction Cohort model",
            stat_bonus=StatBonus(def_bonus=2, arm_bonus=2, immune_to_knockdown=True),
        ),
    )


class PolarityField(ModelSpecialRule):
    """Polarity Field.

    This model cannot be targeted by a charge or slam power attack made by
    a construct model.
    """

    name = "Polarity Field"
    effects = (
        ModelSpecialRuleEffect(
            timing=Timing.CONTINUOUS,
            condition="Cannot be targeted by a charge or slam power attack made by a construct model",
        ),
    )


class SetDefense(ModelSpecialRule):
    """Set Defense.

    Models suffer -2 on charge and slam power attack rolls against this
    model.
    """

    name = "Set Defense"
    effects = (
        ModelSpecialRuleEffect(
            timing=Timing.CONTINUOUS,
            stat_bonus=StatBonus(
                attack_roll_bonus=-2, against_attacker=True, charge_or_slam_only=True
            ),
        ),
    )


class TakeUp(ModelSpecialRule):
    """Take Up.

    If this model is destroyed by an effect other than "Take Up", you can
    choose a grunt in this unit within 1" of it to be destroyed instead.
    Remove that grunt from the table instead of this model. This model has
    the same number of unmarked damage boxes as the chosen grunt.
    """

    name = "Take Up"
    effects = (
        ModelSpecialRuleEffect(
            timing=Timing.ON_MODEL_DESTROYED,
            trigger='Destroyed by an effect other than "Take Up"',
            condition='A grunt in this unit is within 1" of this model',
        ),
    )


class ForceBarrier(ModelSpecialRule):
    """Force Barrier.

    This model gains +2 DEF against ranged attack rolls and gains
    "Resistance: Blast".
    """

    name = "Force Barrier"
    effects = (
        ModelSpecialRuleEffect(
            timing=Timing.CONTINUOUS,
            stat_bonus=StatBonus(def_bonus=2, ranged_only=True),
            grants=("Resistance: Blast",),
        ),
    )


class Rise(ModelSpecialRule):
    """Rise.

    If model is knocked down at the beginning of your maintenance phase, it
    stands up.
    """

    name = "Rise"
    effects = (
        ModelSpecialRuleEffect(
            timing=Timing.START_OF_MAINTENANCE_PHASE,
            trigger="Knocked down at the beginning of your Maintenance Phase",
        ),
    )


class Cleave(ModelSpecialRule):
    """Cleave.

    When a model with Cleave destroys one or more enemy models with a basic
    melee attack during its Combat Action, immediately after the attack is
    resolved the model can make one additional melee attack. A model can
    only gain one additional attack from Cleave per activation.
    """

    name = "Cleave"
    effects = (
        ModelSpecialRuleEffect(
            timing=Timing.ON_MELEE_ATTACK_DESTROYS_MODEL,
            trigger="Destroys one or more enemy models with a basic melee attack during its Combat Action",
            additional_action=AdditionalAction(
                action_type=ActionType.BASIC_MELEE_ATTACK, max_per_activation=1
            ),
        ),
    )


class Sprint(ModelSpecialRule):
    """Sprint.

    At the end of an activation in which it destroyed or removed from play
    one or more enemy models with melee attacks, this model can immediately
    make a full advance, then its activation ends.
    """

    name = "Sprint"
    effects = (
        ModelSpecialRuleEffect(
            timing=Timing.END_OF_ACTIVATION,
            trigger="Destroyed or removed from play one or more enemy models with melee attacks this activation",
            additional_action=AdditionalAction(action_type=ActionType.FULL_ADVANCE),
        ),
    )


class Ionization(ModelSpecialRule):
    """Ionization [X].

    When a model without Resistance: Electricity suffers an electrical
    damage roll while within X" of this model, add +2 to the roll.
    """

    name = "Ionization [X]"
    effects = (
        ModelSpecialRuleEffect(
            timing=Timing.ON_DAMAGE_ROLL,
            trigger=(
                'A model without Resistance: Electricity suffers an '
                'electrical damage roll within X" of this model'
            ),
            condition="Adds +2 to that damage roll",
        ),
    )


class Reposition(ModelSpecialRule):
    """Reposition [X].

    At the end of this model/unit's activation in which it did not run or
    fail a charge, this model can advance up to X", then its activation
    ends.
    """

    name = "Reposition [X]"
    effects = (
        ModelSpecialRuleEffect(
            timing=Timing.END_OF_ACTIVATION,
            trigger="Did not run or fail a charge this activation",
            additional_action=AdditionalAction(action_type=ActionType.ADVANCE),
        ),
    )


class Dodge(ModelSpecialRule):
    """Dodge.

    This model can advance up to 2" immediately after an enemy attack that
    missed it is resolved.
    """

    name = "Dodge"
    effects = (
        ModelSpecialRuleEffect(
            timing=Timing.ON_ATTACK_MISSED_SELF,
            trigger="An enemy attack that missed this model is resolved",
            additional_action=AdditionalAction(action_type=ActionType.ADVANCE, max_distance=2.0),
        ),
    )


class RighteousVengeance(ModelSpecialRule):
    """Righteous Vengeance.

    If one or more friendly Faction warrior models were destroyed or
    removed from play by enemy attacks while within 5" of this model
    during the last round, during your Maintenance Phase this model can
    make a Vengeance Move. A model making a Vengeance Move can advance 3"
    and make one basic melee attack. A model can only make one Vengeance
    Move each turn.
    """

    name = "Righteous Vengeance"
    effects = (
        ModelSpecialRuleEffect(
            timing=Timing.START_OF_MAINTENANCE_PHASE,
            trigger=(
                'One or more friendly Faction warrior models were destroyed '
                'or removed from play by enemy attacks within 5" of this '
                'model during the last round'
            ),
            additional_action=AdditionalAction(
                action_type=ActionType.VENGEANCE_MOVE,
                max_distance=3.0,
                max_per_turn=1,
            ),
        ),
    )


class Riposte(ModelSpecialRule):
    """Riposte.

    When it is missed by an enemy melee attack, immediately after the
    attack is resolved this model can make one basic melee attack against
    the attacking model.
    """

    name = "Riposte"
    effects = (
        ModelSpecialRuleEffect(
            timing=Timing.ON_ATTACK_MISSED_SELF,
            trigger="Missed by an enemy melee attack",
            additional_action=AdditionalAction(
                action_type=ActionType.BASIC_MELEE_ATTACK,
                target="the attacking model",
            ),
        ),
    )


class Jump(ModelSpecialRule):
    """Jump.

    After it makes a full advance during its Normal Movement but before it
    performs its Combat Action, you can place this model anywhere
    completely within 5" of its current location.
    """

    name = "Jump"
    effects = (
        ModelSpecialRuleEffect(
            timing=Timing.AFTER_ADVANCE_BEFORE_COMBAT_ACTION,
            trigger="Made a full advance during its Normal Movement",
            additional_action=AdditionalAction(action_type=ActionType.PLACEMENT, max_distance=5.0),
        ),
    )


class Tactician(ModelSpecialRule):
    """Tactician.

    While within 10" of this model, friendly models ignore other friendly
    models when determining LOS. Friendly models can advance through other
    friendly models within 10" of this model if they have enough movement
    to move completely past them.
    """

    name = "Tactician"
    radius = 10.0
    effects = (
        ModelSpecialRuleEffect(
            timing=Timing.CONTINUOUS,
            condition=(
                'While within 10" of this model, friendly models ignore '
                "other friendly models for LOS and can advance through them"
            ),
        ),
    )


class ShieldWall(ModelSpecialRule):
    """Shield Wall.

    While this model is B2B (base to base) with one or more models in its
    unit, it gains +2 ARM and cannot be knocked down.
    """

    name = "Shield Wall"
    effects = (
        ModelSpecialRuleEffect(
            timing=Timing.CONTINUOUS,
            condition="While B2B with one or more models in its unit",
            stat_bonus=StatBonus(arm_bonus=2, immune_to_knockdown=True),
        ),
    )


class Prowl(ModelSpecialRule):
    """Prowl.

    While this model has concealment, it gains Stealth.
    """

    name = "Prowl"
    effects = (
        ModelSpecialRuleEffect(
            timing=Timing.CONTINUOUS,
            condition="While this model has concealment",
            grants=("Stealth",),
        ),
    )


class Marksman(ModelSpecialRule):
    """Marksman.

    When damaging a warjack or warbeast with ranged attack, choose which
    column or branch suffers damage.
    """

    name = "Marksman"
    effects = (
        ModelSpecialRuleEffect(
            timing=Timing.ON_DAMAGE_ROLL,
            trigger="Damages a warjack or warbeast with a ranged attack",
            condition="Choose which column or branch suffers the damage",
        ),
    )


class Sniper(ModelSpecialRule):
    """Sniper.

    Instead of making a damage roll to resolve a ranged attack, this model
    can inflict 1 damage point. A model disabled by a ranged attack made by
    this model cannot make a Tough roll.
    """

    name = "Sniper"
    effects = (
        ModelSpecialRuleEffect(
            timing=Timing.REPLACES_DAMAGE_ROLL,
            trigger="Resolving a ranged attack made by this model",
            condition="Inflict 1 damage point instead; disabled models cannot make a Tough roll",
        ),
    )


class CombinedArms(ModelSpecialRule):
    """Combined Arms.

    When this model misses an attack roll for a combined ranged attack, it
    can reroll that attack roll. Each attack roll can be rerolled only once
    as a result of Combined Arms.
    """

    name = "Combined Arms"
    effects = (
        ModelSpecialRuleEffect(
            timing=Timing.ON_COMBINED_ATTACK_MISSED,
            trigger="Misses an attack roll for a combined ranged attack",
            condition="Can reroll that attack roll once",
        ),
    )


class Repairable(ModelSpecialRule):
    """Repairable.

    This model can be targeted with Repair special actions as if it were a
    construct model.
    """

    name = "Repairable"
    effects = (
        ModelSpecialRuleEffect(
            timing=Timing.CONTINUOUS,
            condition="Can be targeted with Repair special actions as if it were a construct model",
        ),
    )


class ExtendedFire(ModelSpecialRule):
    """Extended Fire.

    This model can use Extended Fire once per game at any time during its
    unit's activation. This activation, the ranged weapons of models in
    this unit gain Snipe.
    """

    name = "Extended Fire"
    effects = (
        ModelSpecialRuleEffect(
            timing=Timing.ONCE_PER_GAME,
            trigger="At any time during its unit's activation",
            condition="Ranged weapons of models in this unit gain Snipe this activation",
            grants=("Snipe",),
        ),
    )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_RULE_CLASSES: list[type[ModelSpecialRule]] = [
    QuickWork,
    IronSentinel,
    PolarityField,
    SetDefense,
    TakeUp,
    ForceBarrier,
    Rise,
    Cleave,
    Sprint,
    Ionization,
    Reposition,
    Dodge,
    RighteousVengeance,
    Riposte,
    Jump,
    Tactician,
    ShieldWall,
    Prowl,
    Marksman,
    Sniper,
    CombinedArms,
    Repairable,
    ExtendedFire,
]

_REGISTRY: dict[str, type[ModelSpecialRule]] = {
    cls.name: cls for cls in _RULE_CLASSES
}


def all_rule_names() -> list[str]:
    """Return the sorted list of all registered model special rule names."""
    return sorted(_REGISTRY.keys())


def model_special_rule_from_name(name: str) -> ModelSpecialRule:
    """Instantiate a :class:`ModelSpecialRule` by its registered name.

    Args:
        name: The ``name`` attribute of the desired rule class.

    Returns:
        A new instance of the matching rule class.

    Raises:
        ValueError: If *name* does not match any registered rule.
    """
    cls = _REGISTRY.get(name)
    if cls is None:
        raise ValueError(f"Unknown model special rule: {name!r}")
    return cls()
