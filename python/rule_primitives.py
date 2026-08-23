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

"""Shared primitive types for model special rules and special attacks.

Defines the reusable data structures (enums, dataclasses) that replace the
ad-hoc booleans, composite ``Timing`` values, and free-text targets previously
spread across :mod:`model_special_rule` and :mod:`model_special_attack`.

A ``context: tuple[AttackKind, ...]`` field elsewhere in this module means the
attack must match **all** listed kinds (logical AND). The disjunctive pairing
that actually occurs in rules text has its own member (e.g.
``CHARGE_OR_SLAM``). An empty tuple means the effect applies to all attacks.

``RuleEffect.trigger is None`` indicates a continuous effect (always-on while
the rule is active).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from .model_statistics import ModelStatistics
from .weapon_special_rule import Duration


# ---------------------------------------------------------------------------
# Attack kind
# ---------------------------------------------------------------------------


class AttackKind(str, Enum):
    """Kind of attack, used to qualify when an effect applies.

    A ``context: tuple[AttackKind, ...]`` elsewhere means the attack must
    match **all** listed kinds (AND). Empty tuple = applies to all attacks.
    """

    MELEE = "Melee"
    RANGED = "Ranged"
    ARCANE = "Arcane"
    MAGIC_ABILITY = "Magic Ability"
    BASIC = "Basic"
    SPECIAL = "Special"
    CHARGE = "Charge"
    SLAM = "Slam"
    CHARGE_OR_SLAM = "Charge Or Slam"
    POWER_ATTACK = "Power Attack"
    COMBINED_RANGED = "Combined Ranged"
    SPRAY = "Spray"
    BLAST = "Blast"
    NON_SPRAY = "Non Spray"


# ---------------------------------------------------------------------------
# Relationship and model filtering
# ---------------------------------------------------------------------------


class Relationship(str, Enum):
    """Relationship between the source model and the models being filtered."""

    FRIENDLY = "Friendly"
    ENEMY = "Enemy"
    ANY = "Any"


@dataclass
class ModelFilter:
    """A predicate over models on the table.

    All fields optional/empty = matches everything.

    Attributes:
        relationship: Friend/enemy relationship to the source model.
        basic_types: Model basic types to match (match ANY listed).
        keywords: Keywords the model must have (must have ALL listed).
        exclude_keywords: Keywords the model must NOT have.
        advantages: Advantages the model must have (must have ALL listed).
        lacks_advantages: Advantages the model must NOT have.
        resistances_excluded: Resistances the model must NOT have.
        is_living: If not ``None``, whether the model must be living.
        is_undead: If not ``None``, whether the model must be undead.
        in_same_unit: If ``True``, model must be in the same unit as the
            source.
        in_battlegroup: If ``True``, model must be in the source's
            battlegroup.
        is_faction: If ``True``, model must be friendly Faction.
        is_warrior: If ``True``, model must be a warrior model.
        notes: Free-text qualifier for anything not expressible above.
    """

    relationship: Relationship = Relationship.ANY
    basic_types: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()
    exclude_keywords: tuple[str, ...] = ()
    advantages: tuple[str, ...] = ()
    lacks_advantages: tuple[str, ...] = ()
    resistances_excluded: tuple[str, ...] = ()
    is_living: Optional[bool] = None
    is_undead: Optional[bool] = None
    in_same_unit: bool = False
    in_battlegroup: bool = False
    is_faction: bool = False
    is_warrior: bool = False
    notes: str = ""


# ---------------------------------------------------------------------------
# Roll modification
# ---------------------------------------------------------------------------


class RollType(str, Enum):
    """Which kind of roll is being modified."""

    ATTACK = "Attack"
    DAMAGE = "Damage"


class RollModKind(str, Enum):
    """How a roll is modified."""

    FLAT = "Flat"
    ADDITIONAL_DIE = "Additional Die"
    BOOST = "Boost"
    REROLL = "Reroll"
    REMOVE_DIE = "Remove Die"
    REPLACE = "Replace"
    UNBOOSTABLE = "Unboostable"


class RollScope(str, Enum):
    """Whose roll is being modified.

    Attributes:
        OWN: Rolls made BY the affected model.
        INCOMING: Rolls made AGAINST the affected model.
    """

    OWN = "Own"
    INCOMING = "Incoming"


@dataclass
class RollModifier:
    """A modifier applied to an attack or damage roll.

    Attributes:
        roll: Which roll type is modified.
        kind: How the roll is modified.
        amount: Flat delta, additional-die count, or fixed replacement
            damage.
        scope: Whether this affects the model's own rolls or incoming rolls.
        context: Attack kinds that must match for this modifier to apply.
        damage_type: Damage type restriction (e.g. ``"Electricity"``).
        discard_lowest: For ``ADDITIONAL_DIE``, discard the lowest die.
        once_per_roll: For ``REROLL``, each roll can only be rerolled once.
    """

    roll: RollType
    kind: RollModKind
    amount: int = 0
    scope: RollScope = RollScope.OWN
    context: tuple[AttackKind, ...] = ()
    damage_type: str = ""
    discard_lowest: bool = False
    once_per_roll: bool = False


# ---------------------------------------------------------------------------
# Statuses, restrictions, permissions
# ---------------------------------------------------------------------------


class StatusEffect(str, Enum):
    """Status conditions a model can suffer or be immune to."""

    KNOCKED_DOWN = "Knocked Down"
    STATIONARY = "Stationary"
    BLIND = "Blind"
    FIRE = "Fire"
    CORROSION = "Corrosion"
    DISRUPTION = "Disruption"


class Restriction(str, Enum):
    """A limitation placed on a model by a rule effect."""

    CANNOT_MAKE_SPECIAL_ACTIONS = "Cannot Make Special Actions"
    CANNOT_MAKE_SPECIAL_ATTACKS = "Cannot Make Special Attacks"
    CANNOT_MAKE_POWER_ATTACKS = "Cannot Make Power Attacks"
    CANNOT_CAST_SPELLS = "Cannot Cast Spells"
    CANNOT_CHANNEL_SPELLS = "Cannot Channel Spells"
    CANNOT_BE_FORCED = "Cannot Be Forced"
    CANNOT_MAKE_TOUGH_ROLLS = "Cannot Make Tough Rolls"
    CANNOT_HAVE_DAMAGE_REMOVED = "Cannot Have Damage Removed"
    CANNOT_BE_TARGETED = "Cannot Be Targeted"
    CANNOT_GIVE_ORDERS = "Cannot Give Orders"
    CANNOT_RUN = "Cannot Run"
    CANNOT_CHARGE = "Cannot Charge"


class RestrictionTarget(str, Enum):
    """Who a restriction applies to.

    Attributes:
        SELF: The restriction limits the affected model itself.
        SCOPED_MODELS: Applies to models selected by the effect's scope.
        TARGETS_OF_SELF: Applies to models this model attacks.
    """

    SELF = "Self"
    SCOPED_MODELS = "Scoped Models"
    TARGETS_OF_SELF = "Targets Of Self"


@dataclass
class RestrictionSpec:
    """A restriction with targeting and context qualifiers.

    Attributes:
        restriction: The restriction being applied.
        who: Who the restriction applies to.
        context: Attack kinds that must match for the restriction.
        by: Filter describing which models the restriction is caused by.
    """

    restriction: Restriction
    who: RestrictionTarget = RestrictionTarget.SELF
    context: tuple[AttackKind, ...] = ()
    by: Optional[ModelFilter] = None


class MovementPermission(str, Enum):
    """A movement or LOS permission granted by a rule."""

    MOVE_THROUGH_MODELS = "Move Through Models"
    MOVE_THROUGH_FRIENDLY_MODELS = "Move Through Friendly Models"
    MOVE_THROUGH_OBSTRUCTIONS = "Move Through Obstructions"
    IGNORE_FRIENDLY_FOR_LOS = "Ignore Friendly For LOS"
    IGNORE_TERRAIN_PENALTIES = "Ignore Terrain Penalties"
    IGNORE_INTERVENING_WHEN_CHARGING = "Ignore Intervening When Charging"


# ---------------------------------------------------------------------------
# Scope (replaces AuraEffect and AuraTarget)
# ---------------------------------------------------------------------------


class ScopeKind(str, Enum):
    """How widely an effect spreads from its source.

    Attributes:
        SELF: Affects only the source model.
        UNIT: Affects all models in the source's unit.
        BATTLEGROUP: Affects all models in the source's battlegroup.
        AURA: Continuously rechecked "while within X" of this model.
        PULSE: One-shot snapshot of "models currently within X".
    """

    SELF = "Self"
    UNIT = "Unit"
    BATTLEGROUP = "Battlegroup"
    AURA = "Aura"
    PULSE = "Pulse"


@dataclass
class EffectScope:
    """The set of models an effect applies to.

    Attributes:
        kind: The scope type.
        radius: Required for ``AURA`` / ``PULSE``; the radius in inches.
        filter: Which models within the scope are affected.
    """

    kind: ScopeKind = ScopeKind.SELF
    radius: Optional[float] = None
    filter: Optional[ModelFilter] = None


# ---------------------------------------------------------------------------
# Events (replaces composite Timing values)
# ---------------------------------------------------------------------------


class GameEvent(str, Enum):
    """A game event that can trigger a rule effect.

    Events are self-relative unless a subject filter says otherwise.
    """

    DESTROYS_MODEL = "Destroys Model"
    DAMAGES_MODEL = "Damages Model"
    MISSES_ATTACK = "Misses Attack"
    IS_MISSED = "Is Missed"
    IS_DIRECTLY_HIT = "Is Directly Hit"
    IS_DISABLED = "Is Disabled"
    IS_DESTROYED = "Is Destroyed"
    IS_REMOVED_FROM_PLAY = "Is Removed From Play"
    DAMAGE_ROLL_EXCEEDS_ARM = "Damage Roll Exceeds ARM"
    MODEL_SUFFERS_DAMAGE_ROLL = "Model Suffers Damage Roll"
    DECLARES_CHARGE = "Declares Charge"
    CASTS_SPELL = "Casts Spell"
    ENEMY_ENTERS_MELEE_RANGE = "Enemy Enters Melee Range"
    FRIENDLY_DIRECTLY_HIT = "Friendly Directly Hit"
    MAINTENANCE_PHASE_START = "Maintenance Phase Start"
    ACTIVATION_END = "Activation End"
    AFTER_NORMAL_MOVEMENT = "After Normal Movement"
    UNIT_ACTIVATION_ANY_TIME = "Unit Activation Any Time"


@dataclass
class EventTrigger:
    """An event that triggers a rule effect, with qualifiers.

    Attributes:
        event: The game event that fires this trigger.
        subject: Who the event happens to/by, when not the source model.
        context: Attack-type qualifier of the event.
        radius: Proximity qualifier ("within X" of this model).
        description: Verbatim-ish trigger text from the original rule.
    """

    event: GameEvent
    subject: Optional[ModelFilter] = None
    context: tuple[AttackKind, ...] = ()
    radius: Optional[float] = None
    description: str = ""


# ---------------------------------------------------------------------------
# Usage limits, resources, redirection
# ---------------------------------------------------------------------------


@dataclass
class UsageLimit:
    """How many times an effect can be used within a given period.

    Attributes:
        per_activation: Max uses per activation, or ``None`` if unlimited.
        per_turn: Max uses per turn, or ``None`` if unlimited.
        per_round: Max uses per round, or ``None`` if unlimited.
        per_game: Max uses per game, or ``None`` if unlimited.
        per_attack: Max uses per attack, or ``None`` if unlimited.
    """

    per_activation: Optional[int] = None
    per_turn: Optional[int] = None
    per_round: Optional[int] = None
    per_game: Optional[int] = None
    per_attack: Optional[int] = None


class Resource(str, Enum):
    """A game resource that can be gained or lost."""

    FOCUS = "Focus"
    FURY = "Fury"
    ESSENCE = "Essence"
    SOUL_TOKEN = "Soul Token"
    CORPSE_TOKEN = "Corpse Token"
    DAMAGE = "Damage"
    SPELL_COST = "Spell Cost"


@dataclass
class ResourceChange:
    """A change to a resource pool.

    Attributes:
        resource: The resource being changed.
        amount: Signed amount; for ``DAMAGE``, negative = remove damage
            (heal).
        dice: Dice expression (e.g. ``"d3"``); when set, ``amount`` acts as
            sign/multiplier.
        all_points: If ``True``, remove all points of the resource.
        target: Which model(s) are affected; ``None`` = the effect's
            affected model(s).
    """

    resource: Resource
    amount: int = 0
    dice: str = ""
    all_points: bool = False
    target: Optional[ModelFilter] = None


class RedirectKind(str, Enum):
    """What kind of outcome is being redirected."""

    HIT = "Hit"
    DISABLE = "Disable"
    DESTRUCTION = "Destruction"


@dataclass
class Redirection:
    """Redirects an outcome onto another model.

    Attributes:
        what: The kind of outcome being redirected.
        to_self: If ``True``, redirect onto this model (the source).
        to: Filter describing which model to redirect to (when not self).
        radius: Proximity limit for the redirect target.
        heal_self: Damage points to remove from the source on redirect.
    """

    what: RedirectKind
    to_self: bool = False
    to: Optional[ModelFilter] = None
    radius: Optional[float] = None
    heal_self: int = 0


# ---------------------------------------------------------------------------
# Slim StatBonus (kept, reduced)
# ---------------------------------------------------------------------------


@dataclass
class StatBonus:
    """A modifier to combat statistics granted while a condition holds.

    Attributes:
        stats: Delta applied to this model's combat statistics.
        context: Attack kinds that must match for the bonus to apply.
    """

    stats: ModelStatistics = field(default_factory=ModelStatistics)
    context: tuple[AttackKind, ...] = ()


# ---------------------------------------------------------------------------
# The shared effect type
# ---------------------------------------------------------------------------


@dataclass
class RuleEffect:
    """A single discrete effect produced by a rule or special attack.

    A ``trigger`` of ``None`` indicates a continuous (always-on) effect.

    Attributes:
        scope: Which models this effect applies to.
        trigger: Event that fires this effect, or ``None`` if continuous.
        condition: Qualifying prose text.
        stat_bonus: Stat modifier granted by this effect, if any.
        roll_modifiers: Roll modifiers applied by this effect.
        status_immunities: Status effects the target is immune to.
        cures: Status effects removed from the target.
        restrictions: Restrictions placed on models.
        permissions: Movement/LOS permissions granted.
        grants: Names of rules/advantages/resistances granted.
        removes: Names of rules/advantages removed.
        additional_action: Extra action granted by this effect, if any.
        resource_changes: Resource changes applied by this effect.
        redirection: Damage/outcome redirection, if any.
        expires_upkeeps: If ``True``, enemy upkeep spells expire.
        usage_limit: Usage limits for this effect.
        duration: How long this effect lasts once triggered.
        notes: Anything not expressible structurally.
    """

    scope: EffectScope = field(default_factory=EffectScope)
    trigger: Optional[EventTrigger] = None
    condition: str = ""
    stat_bonus: Optional[StatBonus] = None
    roll_modifiers: tuple[RollModifier, ...] = ()
    status_immunities: tuple[StatusEffect, ...] = ()
    cures: tuple[StatusEffect, ...] = ()
    restrictions: tuple[RestrictionSpec, ...] = ()
    permissions: tuple[MovementPermission, ...] = ()
    grants: tuple[str, ...] = ()
    removes: tuple[str, ...] = ()
    additional_action: Optional[AdditionalAction] = None
    resource_changes: tuple[ResourceChange, ...] = ()
    redirection: Optional[Redirection] = None
    expires_upkeeps: bool = False
    usage_limit: Optional[UsageLimit] = None
    duration: Optional[Duration] = None
    notes: str = ""


# ---------------------------------------------------------------------------
# ActionType and AdditionalAction (moved from model_special_rule)
# ---------------------------------------------------------------------------


class ActionType(str, Enum):
    """Kind of extra action a model may perform as a result of a special
    rule.
    """

    BASIC_MELEE_ATTACK = "Basic Melee Attack"
    BASIC_RANGED_ATTACK = "Basic Ranged Attack"
    BASIC_MELEE_OR_RANGED_ATTACK = "Basic Melee Or Ranged Attack"
    MAGIC_ABILITY = "Magic Ability"
    ADVANCE = "Advance"
    FULL_ADVANCE = "Full Advance"
    PLACEMENT = "Placement"
    VENGEANCE_MOVE = "Vengeance Move"


@dataclass
class AdditionalAction:
    """An extra action granted by a special rule.

    Attributes:
        action_type: Kind of action granted.
        max_distance: Maximum advance/placement distance in inches, or
            ``None`` if not applicable.
        target: Filter describing the valid target, or ``None`` if
            unrestricted.
        target_is_trigger_source: If ``True``, the target is the model that
            triggered the event.
        then_activation_ends: If ``True``, the model's activation ends after
            this action.
    """

    action_type: ActionType
    max_distance: Optional[float] = None
    target: Optional[ModelFilter] = None
    target_is_trigger_source: bool = False
    then_activation_ends: bool = False
