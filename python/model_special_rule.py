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

Defines the :class:`ModelSpecialRule` base class, the :class:`GrantScope`
enum, and all concrete rule implementations.  Shared primitive types
(:class:`~.rule_primitives.RuleEffect`,
:class:`~.rule_primitives.StatBonus`,
:class:`~.rule_primitives.AdditionalAction`, etc.) are imported from
:mod:`rule_primitives`.  The :class:`~.weapon_special_rule.Duration` enum
is reused as-is from :mod:`weapon_special_rule` for effects that last a
fixed game duration (e.g. "for one round").

Design notes
------------
Model special rules are far less mechanically uniform than weapon special
rules: some are always-on conditional bonuses, some trigger once on a
specific event, some grant an extra action, some grant *other* rules, and a
few restrict what other models may do.  Each rule stores:

- A verbatim rules-text docstring (the source of truth for anything not
  captured structurally).
- One or more :class:`~.rule_primitives.RuleEffect` entries in
  :attr:`effects`, giving *best-effort* structured metadata using the
  shared primitives from :mod:`rule_primitives`.

A :attr:`~.rule_primitives.RuleEffect.trigger` of ``None`` indicates a
continuous (always-on) effect.  A non-``None``
:class:`~.rule_primitives.EventTrigger` specifies the
:class:`~.rule_primitives.GameEvent` that fires the effect, along with
optional subject/context/radius qualifiers.

Most rules have exactly one effect.  A few real rules bundle several
distinct effects into a single named rule; those define more than one entry
in :attr:`effects`.

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
2. Define one (or more) :class:`~.rule_primitives.RuleEffect` in
   ``effects``, filling in whichever primitive fields apply.  Fields that
   don't cleanly generalise can be left at their defaults — the docstring
   remains the authoritative definition.
3. Register the class by adding it to the ``_RULE_CLASSES`` list near the
   bottom of this module.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from .model_statistics import ModelStatistics
from .rule_primitives import (
    ActionType,
    AdditionalAction,
    AttackKind as AK,
    EffectScope,
    EventTrigger,
    GameEvent,
    ModelFilter as MF,
    MovementPermission,
    Redirection,
    RedirectKind,
    Relationship,
    Resource,
    ResourceChange,
    Restriction,
    RestrictionSpec,
    RestrictionTarget,
    RollModifier as RM,
    RollModKind,
    RollScope,
    RollType,
    RuleEffect,
    ScopeKind,
    StatBonus,
    StatusEffect,
    UsageLimit,
)
from .weapon_special_rule import Duration

ModelSpecialRuleEffect = RuleEffect


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class GrantScope(str, Enum):
    """How a special rule's benefit is shared with other models.

    See the module docstring for the precise meaning of each value.
    """

    SELF = "Self"
    GRANTED = "Granted"
    DRIVE = "Drive"
    FIELD_MARSHAL = "Field Marshal"


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
            model. May be a float (distance) or a string (keyword).
        grant_scope: How this rule's benefit is shared. Defaults to
            :attr:`GrantScope.SELF` (the model itself has the rule).
            Reconfigure per instance to represent a "Granted:", "Drive:",
            or "Field Marshal:" prefixed rule on a specific model card.
        grant_radius: Aura radius in inches used with
            :attr:`GrantScope.DRIVE` (e.g. "while within 10\" of this
            model..."). ``None`` for other scopes or when not applicable.
        effects: The discrete effect(s) produced by this rule. Most rules
            define exactly one; a few define several.  Each effect is a
            :class:`~.rule_primitives.RuleEffect` using shared primitives.
            Aura radii live in ``EffectScope.radius``; trigger proximities
            in ``EventTrigger.radius``.
    """

    name: str = ""
    argument: Optional[float | str] = None
    grant_scope: GrantScope = GrantScope.SELF
    grant_radius: Optional[float] = None
    effects: tuple[RuleEffect, ...] = ()


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
        RuleEffect(
            trigger=EventTrigger(
                event=GameEvent.DESTROYS_MODEL,
                context=(AK.MELEE,),
                description="Destroys one or more enemy models with a melee attack during its Combat Action",
            ),
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
        RuleEffect(
            condition="While B2B with a friendly Faction Cohort model",
            stat_bonus=StatBonus(stats=ModelStatistics(def_=2, arm=2)),
            status_immunities=(StatusEffect.KNOCKED_DOWN,),
        ),
    )


class PolarityField(ModelSpecialRule):
    """Polarity Field.

    This model cannot be targeted by a charge or slam power attack made by
    a construct model.
    """

    name = "Polarity Field"
    effects = (
        RuleEffect(
            restrictions=(
                RestrictionSpec(
                    restriction=Restriction.CANNOT_BE_TARGETED,
                    context=(AK.CHARGE_OR_SLAM,),
                    by=MF(advantages=("Construct",)),
                ),
            ),
        ),
    )


class SetDefense(ModelSpecialRule):
    """Set Defense.

    Models suffer -2 on charge and slam power attack rolls against this
    model.
    """

    name = "Set Defense"
    effects = (
        RuleEffect(
            roll_modifiers=(
                RM(RollType.ATTACK, RollModKind.FLAT, -2, scope=RollScope.INCOMING, context=(AK.CHARGE_OR_SLAM,)),
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
        RuleEffect(
            trigger=EventTrigger(
                event=GameEvent.IS_DESTROYED,
                description='Destroyed by an effect other than "Take Up"',
            ),
            redirection=Redirection(
                what=RedirectKind.DESTRUCTION,
                to=MF(relationship=Relationship.FRIENDLY, in_same_unit=True, notes="a grunt"),
                radius=1.0,
            ),
            notes="This model has the same number of unmarked damage boxes as the chosen grunt.",
        ),
    )


class ForceBarrier(ModelSpecialRule):
    """Force Barrier.

    This model gains +2 DEF against ranged attack rolls and gains
    "Resistance: Blast".
    """

    name = "Force Barrier"
    effects = (
        RuleEffect(
            stat_bonus=StatBonus(stats=ModelStatistics(def_=2), context=(AK.RANGED,)),
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
        RuleEffect(
            trigger=EventTrigger(
                event=GameEvent.MAINTENANCE_PHASE_START,
                description="Knocked down at the beginning of your Maintenance Phase",
            ),
            cures=(StatusEffect.KNOCKED_DOWN,),
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
        RuleEffect(
            trigger=EventTrigger(
                event=GameEvent.DESTROYS_MODEL,
                context=(AK.BASIC, AK.MELEE),
                description="Destroys one or more enemy models with a basic melee attack during its Combat Action",
            ),
            additional_action=AdditionalAction(action_type=ActionType.BASIC_MELEE_ATTACK),
            usage_limit=UsageLimit(per_activation=1),
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
        RuleEffect(
            trigger=EventTrigger(
                event=GameEvent.ACTIVATION_END,
                context=(AK.MELEE,),
                description="Destroyed or removed from play one or more enemy models with melee attacks this activation",
            ),
            additional_action=AdditionalAction(action_type=ActionType.FULL_ADVANCE, then_activation_ends=True),
        ),
    )


class Ionization(ModelSpecialRule):
    """Ionization [X].

    When a model without Resistance: Electricity suffers an electrical
    damage roll while within X" of this model, add +2 to the roll.
    """

    name = "Ionization [X]"
    effects = (
        RuleEffect(
            scope=EffectScope(kind=ScopeKind.AURA, radius=None, filter=MF(resistances_excluded=("Electricity",))),
            roll_modifiers=(
                RM(RollType.DAMAGE, RollModKind.FLAT, 2, scope=RollScope.INCOMING, damage_type="Electricity"),
            ),
            notes='Radius is resolved from argument; adds +2 to electrical damage rolls within X" of this model',
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
        RuleEffect(
            trigger=EventTrigger(
                event=GameEvent.ACTIVATION_END,
                description="Did not run or fail a charge this activation",
            ),
            condition="Did not run or fail a charge this activation",
            additional_action=AdditionalAction(action_type=ActionType.ADVANCE, then_activation_ends=True),
            notes="Advance distance is resolved from argument",
        ),
    )


class Dodge(ModelSpecialRule):
    """Dodge.

    This model can advance up to 2" immediately after an enemy attack that
    missed it is resolved.
    """

    name = "Dodge"
    effects = (
        RuleEffect(
            trigger=EventTrigger(
                event=GameEvent.IS_MISSED,
                subject=MF(relationship=Relationship.ENEMY),
                description="An enemy attack that missed this model is resolved",
            ),
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
        RuleEffect(
            trigger=EventTrigger(
                event=GameEvent.MAINTENANCE_PHASE_START,
                subject=MF(relationship=Relationship.FRIENDLY, is_faction=True, is_warrior=True),
                radius=5.0,
                description=(
                    'One or more friendly Faction warrior models were destroyed '
                    'or removed from play by enemy attacks within 5" of this '
                    'model during the last round'
                ),
            ),
            additional_action=AdditionalAction(
                action_type=ActionType.VENGEANCE_MOVE,
                max_distance=3.0,
            ),
            usage_limit=UsageLimit(per_turn=1),
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
        RuleEffect(
            trigger=EventTrigger(
                event=GameEvent.IS_MISSED,
                subject=MF(relationship=Relationship.ENEMY),
                context=(AK.MELEE,),
                description="Missed by an enemy melee attack",
            ),
            additional_action=AdditionalAction(
                action_type=ActionType.BASIC_MELEE_ATTACK,
                target_is_trigger_source=True,
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
        RuleEffect(
            trigger=EventTrigger(
                event=GameEvent.AFTER_NORMAL_MOVEMENT,
                description="Made a full advance during its Normal Movement",
            ),
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
    effects = (
        RuleEffect(
            scope=EffectScope(kind=ScopeKind.AURA, radius=10.0, filter=MF(relationship=Relationship.FRIENDLY)),
            permissions=(
                MovementPermission.IGNORE_FRIENDLY_FOR_LOS,
                MovementPermission.MOVE_THROUGH_FRIENDLY_MODELS,
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
        RuleEffect(
            condition="While B2B with one or more models in its unit",
            stat_bonus=StatBonus(stats=ModelStatistics(arm=2)),
            status_immunities=(StatusEffect.KNOCKED_DOWN,),
        ),
    )


class Prowl(ModelSpecialRule):
    """Prowl.

    While this model has concealment, it gains Stealth.
    """

    name = "Prowl"
    effects = (
        RuleEffect(
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
        RuleEffect(
            trigger=EventTrigger(
                event=GameEvent.DAMAGES_MODEL,
                subject=MF(basic_types=("Warjack", "Warbeast")),
                context=(AK.RANGED,),
                description="Damages a warjack or warbeast with a ranged attack",
            ),
            notes="Choose which column or branch suffers the damage",
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
        RuleEffect(
            roll_modifiers=(
                RM(RollType.DAMAGE, RollModKind.REPLACE, amount=1, context=(AK.RANGED,)),
            ),
            restrictions=(
                RestrictionSpec(
                    restriction=Restriction.CANNOT_MAKE_TOUGH_ROLLS,
                    who=RestrictionTarget.TARGETS_OF_SELF,
                    context=(AK.RANGED,),
                ),
            ),
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
        RuleEffect(
            trigger=EventTrigger(
                event=GameEvent.MISSES_ATTACK,
                context=(AK.COMBINED_RANGED,),
                description="Misses an attack roll for a combined ranged attack",
            ),
            roll_modifiers=(
                RM(RollType.ATTACK, RollModKind.REROLL, context=(AK.COMBINED_RANGED,), once_per_roll=True),
            ),
        ),
    )


class Repairable(ModelSpecialRule):
    """Repairable.

    This model can be targeted with Repair special actions as if it were a
    construct model.
    """

    name = "Repairable"
    effects = (
        RuleEffect(
            notes="Can be targeted with Repair special actions as if it were a construct model",
        ),
    )


class BattleWizard(ModelSpecialRule):
    """Battle Wizard.

    Once per turn, when this model destroys or removes from play one or
    more enemy models with a melee attack during its activation,
    immediately after the attack is resolved it can make one Magic Ability
    special attack or special action.
    """

    name = "Battle Wizard"
    effects = (
        RuleEffect(
            trigger=EventTrigger(
                event=GameEvent.DESTROYS_MODEL,
                context=(AK.MELEE,),
                description="Destroys or removes from play one or more enemy models with a melee attack during its activation",
            ),
            additional_action=AdditionalAction(action_type=ActionType.MAGIC_ABILITY),
            usage_limit=UsageLimit(per_turn=1),
        ),
    )


class Gang(ModelSpecialRule):
    """Gang.

    When making a melee attack targeting an enemy model in the melee range
    of another model in this unit, this model gains +2 to melee attack and
    melee damage rolls.
    """

    name = "Gang"
    effects = (
        RuleEffect(
            condition="Targeting an enemy model in the melee range of another model in this unit",
            roll_modifiers=(
                RM(RollType.ATTACK, RollModKind.FLAT, 2, context=(AK.MELEE,)),
                RM(RollType.DAMAGE, RollModKind.FLAT, 2, context=(AK.MELEE,)),
            ),
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
        RuleEffect(
            trigger=EventTrigger(
                event=GameEvent.UNIT_ACTIVATION_ANY_TIME,
                description="At any time during its unit's activation",
            ),
            scope=EffectScope(kind=ScopeKind.UNIT),
            grants=("Snipe",),
            duration=Duration.ACTIVATION,
            usage_limit=UsageLimit(per_game=1),
        ),
    )


class MarkedSoul(ModelSpecialRule):
    """Marked Soul.

    This model is a Marked Soul.
    """

    name = "Marked Soul"
    effects = (
        RuleEffect(
            notes="This model is a Marked Soul",
        ),
    )


class WillingVessel(ModelSpecialRule):
    """Willing Vessel.

    When an infernal master summons a horror and chooses this model to
    remove from play, the infernal master does not need to spend any
    essence points to summon the horror.
    """

    name = "Willing Vessel"
    effects = (
        RuleEffect(
            trigger=EventTrigger(
                event=GameEvent.IS_REMOVED_FROM_PLAY,
                description="Chosen by an infernal master to be removed from play to summon a horror",
            ),
            notes="The infernal master does not need to spend any essence points to summon the horror",
        ),
    )


class ArcanePulse(ModelSpecialRule):
    """Arcane Pulse.

    When this model is destroyed by an enemy attack, enemy upkeep spells on
    models within 8" of it expire.
    """

    name = "Arcane Pulse"
    effects = (
        RuleEffect(
            trigger=EventTrigger(
                event=GameEvent.IS_DESTROYED,
                subject=MF(relationship=Relationship.ENEMY),
                description="Destroyed by an enemy attack",
            ),
            scope=EffectScope(kind=ScopeKind.PULSE, radius=8.0, filter=MF(relationship=Relationship.ENEMY)),
            expires_upkeeps=True,
        ),
    )


class DarkPower(ModelSpecialRule):
    """Dark Power.

    This model gains an additional die on arcane attack and arcane attack
    damage rolls. Discard the lowest die in each roll.
    """

    name = "Dark Power"
    effects = (
        RuleEffect(
            roll_modifiers=(
                RM(RollType.ATTACK, RollModKind.ADDITIONAL_DIE, 1, context=(AK.ARCANE,), discard_lowest=True),
                RM(RollType.DAMAGE, RollModKind.ADDITIONAL_DIE, 1, context=(AK.ARCANE,), discard_lowest=True),
            ),
        ),
    )


class GateWalker(ModelSpecialRule):
    """Gate Walker.

    Once per activation, immediately after this model casts a spell, you
    can place this model anywhere completely within 5" of its current
    location.
    """

    name = "Gate Walker"
    effects = (
        RuleEffect(
            trigger=EventTrigger(
                event=GameEvent.CASTS_SPELL,
                description="Immediately after this model casts a spell",
            ),
            additional_action=AdditionalAction(action_type=ActionType.PLACEMENT, max_distance=5.0),
            usage_limit=UsageLimit(per_activation=1),
        ),
    )


class AncientShroud(ModelSpecialRule):
    """Ancient Shroud.

    When a damage roll against this model exceeds its ARM, it suffers 1
    damage point instead of the total rolled.
    """

    name = "Ancient Shroud"
    effects = (
        RuleEffect(
            trigger=EventTrigger(
                event=GameEvent.DAMAGE_ROLL_EXCEEDS_ARM,
                description="A damage roll against this model exceeds its ARM",
            ),
            roll_modifiers=(
                RM(RollType.DAMAGE, RollModKind.REPLACE, amount=1, scope=RollScope.INCOMING),
            ),
        ),
    )


class DarkProphecy(ModelSpecialRule):
    """Dark Prophecy.

    When this model is destroyed by an enemy attack, enemy models within 8"
    lose their essence points and cannot cast spells, channel spells, or be
    forced for one round.
    """

    name = "Dark Prophecy"
    effects = (
        RuleEffect(
            trigger=EventTrigger(
                event=GameEvent.IS_DESTROYED,
                subject=MF(relationship=Relationship.ENEMY),
                description="Destroyed by an enemy attack",
            ),
            scope=EffectScope(kind=ScopeKind.PULSE, radius=8.0, filter=MF(relationship=Relationship.ENEMY)),
            resource_changes=(
                ResourceChange(resource=Resource.ESSENCE, all_points=True, amount=-1),
            ),
            restrictions=(
                RestrictionSpec(restriction=Restriction.CANNOT_CAST_SPELLS, who=RestrictionTarget.SCOPED_MODELS),
                RestrictionSpec(restriction=Restriction.CANNOT_CHANNEL_SPELLS, who=RestrictionTarget.SCOPED_MODELS),
                RestrictionSpec(restriction=Restriction.CANNOT_BE_FORCED, who=RestrictionTarget.SCOPED_MODELS),
            ),
            duration=Duration.ROUND,
        ),
    )


class Telemetry(ModelSpecialRule):
    """Telemetry.

    Other friendly models gain +2 to arcane attack rolls against enemy
    models within 8" of this model.
    """

    name = "Telemetry"
    effects = (
        RuleEffect(
            scope=EffectScope(kind=ScopeKind.AURA, radius=8.0, filter=MF(relationship=Relationship.ENEMY)),
            roll_modifiers=(
                RM(RollType.ATTACK, RollModKind.FLAT, 2, scope=RollScope.INCOMING, context=(AK.ARCANE,)),
            ),
            notes="Bonus applies to other friendly models' arcane attack rolls",
        ),
    )


class MasterOfRuin(ModelSpecialRule):
    """Master of Ruin.

    Other models suffer -2 ARM while within 5" of this model.
    """

    name = "Master of Ruin"
    effects = (
        RuleEffect(
            scope=EffectScope(kind=ScopeKind.AURA, radius=5.0, filter=MF(relationship=Relationship.ANY)),
            stat_bonus=StatBonus(stats=ModelStatistics(arm=-2)),
        ),
    )


class Acrobatics(ModelSpecialRule):
    """Acrobatics.

    This model can advance through other models if it has enough movement
    to move completely past their bases. This model ignores intervening
    models when declaring its charge target.
    """

    name = "Acrobatics"
    effects = (
        RuleEffect(
            permissions=(
                MovementPermission.MOVE_THROUGH_MODELS,
                MovementPermission.IGNORE_INTERVENING_WHEN_CHARGING,
            ),
        ),
    )


class RunAndGun(ModelSpecialRule):
    """Run & Gun.

    At the end of its activation, if this model destroyed one or more
    enemy models with a ranged attack that activation, it can make a full
    advance.
    """

    name = "Run & Gun"
    effects = (
        RuleEffect(
            trigger=EventTrigger(
                event=GameEvent.ACTIVATION_END,
                context=(AK.RANGED,),
                description="Destroyed one or more enemy models with a ranged attack this activation",
            ),
            additional_action=AdditionalAction(action_type=ActionType.FULL_ADVANCE),
        ),
    )


class EntropicForce(ModelSpecialRule):
    """Entropic Force.

    While within 5" of this model, enemy models lose Tough and cannot have
    damage removed from them.
    """

    name = "Entropic Force"
    effects = (
        RuleEffect(
            scope=EffectScope(kind=ScopeKind.AURA, radius=5.0, filter=MF(relationship=Relationship.ENEMY)),
            removes=("Tough",),
            restrictions=(
                RestrictionSpec(restriction=Restriction.CANNOT_HAVE_DAMAGE_REMOVED, who=RestrictionTarget.SCOPED_MODELS),
            ),
        ),
    )


class DefensiveStrike(ModelSpecialRule):
    """Defensive Strike.

    Once per turn, when an enemy model advances into and ends its movement
    or is placed in this model's melee range, this model can immediately
    make one basic melee attack against it.
    """

    name = "Defensive Strike"
    effects = (
        RuleEffect(
            trigger=EventTrigger(
                event=GameEvent.ENEMY_ENTERS_MELEE_RANGE,
                description="An enemy model advances into and ends its movement, or is placed, in this model's melee range",
            ),
            additional_action=AdditionalAction(
                action_type=ActionType.BASIC_MELEE_ATTACK,
                target_is_trigger_source=True,
            ),
            usage_limit=UsageLimit(per_turn=1),
        ),
    )


class Ghostly(ModelSpecialRule):
    """Ghostly.

    This model can advance through terrain and obstacles without penalty
    and can advance through obstructions and models if it has enough
    movement to move completely past them.
    """

    name = "Ghostly"
    effects = (
        RuleEffect(
            permissions=(
                MovementPermission.IGNORE_TERRAIN_PENALTIES,
                MovementPermission.MOVE_THROUGH_OBSTRUCTIONS,
                MovementPermission.MOVE_THROUGH_MODELS,
            ),
        ),
    )


class ShadowGuardian(ModelSpecialRule):
    """Shadow Guardian.

    You can choose not to deploy this model at the start of the game. If it
    is not deployed normally, you can put it into play when a friendly
    non-Umbral Faction model is directly hit by an enemy ranged attack.
    Place this model completely within 3" of the hit model. This model is
    automatically hit by the ranged attack instead and suffers all damage
    and effects.
    """

    name = "Shadow Guardian"
    effects = (
        RuleEffect(
            trigger=EventTrigger(
                event=GameEvent.FRIENDLY_DIRECTLY_HIT,
                subject=MF(relationship=Relationship.FRIENDLY, is_faction=True, exclude_keywords=("Umbral",)),
                context=(AK.RANGED,),
                description="A friendly non-Umbral Faction model is directly hit by an enemy ranged attack while this model has not been deployed",
            ),
            condition="While this model has not been deployed",
            additional_action=AdditionalAction(action_type=ActionType.PLACEMENT, max_distance=3.0),
            redirection=Redirection(what=RedirectKind.HIT, to_self=True),
        ),
    )


class ShieldGuard(ModelSpecialRule):
    """Shield Guard.

    When a friendly model is directly hit by a non-spray ranged attack
    while within 3" of a model with Shield Guard, you can choose to have
    the model with Shield Guard be directly hit instead. That model is
    automatically hit and suffers all damage and effects. A model can use
    Shield Guard only once per round and cannot use Shield Guard if it is
    incorporeal, knocked down, or stationary. Shield Guard can only be used
    once per attack.
    """

    name = "Shield Guard"
    effects = (
        RuleEffect(
            trigger=EventTrigger(
                event=GameEvent.FRIENDLY_DIRECTLY_HIT,
                subject=MF(relationship=Relationship.FRIENDLY),
                context=(AK.RANGED, AK.NON_SPRAY),
                radius=3.0,
                description='A friendly model is directly hit by a non-spray ranged attack while within 3" of this model',
            ),
            condition="Cannot use while incorporeal, knocked down, or stationary",
            redirection=Redirection(what=RedirectKind.HIT, to_self=True),
            usage_limit=UsageLimit(per_round=1, per_attack=1),
        ),
    )


class Bloodthirst(ModelSpecialRule):
    """Bloodthirst.

    When it charges a living or undead model, this model gains +2 SPD.
    """

    name = "Bloodthirst"
    effects = (
        RuleEffect(
            trigger=EventTrigger(
                event=GameEvent.DECLARES_CHARGE,
                subject=MF(notes="living or undead model"),
                description="Charges a living or undead model",
            ),
            stat_bonus=StatBonus(stats=ModelStatistics(spd=2)),
        ),
    )


class Vengeance(ModelSpecialRule):
    """Vengeance.

    During your Maintenance Phase, if one or more models in this unit were
    damaged by enemy attacks during the last round, each model in the unit
    can make a Vengeance Move. Each model making a Vengeance Move can
    advance 3". After all models in the unit have moved, each model can
    then make one basic melee attack. A model can only make one Vengeance
    Move each turn.
    """

    name = "Vengeance"
    effects = (
        RuleEffect(
            trigger=EventTrigger(
                event=GameEvent.MAINTENANCE_PHASE_START,
                description="One or more models in this unit were damaged by enemy attacks during the last round",
            ),
            scope=EffectScope(kind=ScopeKind.UNIT),
            additional_action=AdditionalAction(
                action_type=ActionType.VENGEANCE_MOVE,
                max_distance=3.0,
            ),
            usage_limit=UsageLimit(per_turn=1),
            notes="After all models in the unit have moved, each can make one basic melee attack",
        ),
    )


class SelfSacrifice(ModelSpecialRule):
    """Self-Sacrifice.

    When this model is disabled by an enemy attack, you can choose a
    non-disabled model in its unit within 3" of this model to be destroyed
    instead and this model removes 1 damage point.
    """

    name = "Self-Sacrifice"
    effects = (
        RuleEffect(
            trigger=EventTrigger(
                event=GameEvent.IS_DISABLED,
                subject=MF(relationship=Relationship.ENEMY),
                description="Disabled by an enemy attack",
            ),
            redirection=Redirection(
                what=RedirectKind.DISABLE,
                to=MF(relationship=Relationship.FRIENDLY, in_same_unit=True, notes="non-disabled"),
                radius=3.0,
                heal_self=1,
            ),
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
    BattleWizard,
    Gang,
    MarkedSoul,
    WillingVessel,
    ArcanePulse,
    DarkPower,
    GateWalker,
    AncientShroud,
    DarkProphecy,
    Telemetry,
    MasterOfRuin,
    Acrobatics,
    RunAndGun,
    EntropicForce,
    DefensiveStrike,
    Ghostly,
    ShadowGuardian,
    ShieldGuard,
    Bloodthirst,
    Vengeance,
    SelfSacrifice,
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
