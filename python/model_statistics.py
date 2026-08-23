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

"""Combat statistics type for the Warmachine game.

Defines :class:`ModelStatistics`, the single bundle of the ten Warmachine
combat statistics (SPD, AAT, MAT, RAT, DEF, ARM, ARC, FURY, CTRL, THR).
The same type is used for both roles:

* an *absolute* stat line, as printed on a model's stat card, where ``0``
  means the statistic does not apply to that model (e.g. ARC for a
  non-caster) and is displayed as ``"-"`` in the model editor;
* a *signed delta*, i.e. a bonus or penalty applied to some or all of a
  model's statistics (e.g. a special rule's stat bonus, or an aura's
  penalty to nearby models), where ``0`` means "no change" and negative
  values are penalties.

Both roles share the same default of ``0``, so the two meanings coincide:
a statistic a model does not have and a statistic that is not modified are
both simply absent from the block.

Absolute stat lines are constrained to non-negative values by whatever
creates them (the model editor's spin boxes have a minimum of ``0``), not
by this class, since deltas legitimately need negative values.

This is intentionally a standalone module (no dependency on
:mod:`model_stat_card` or :mod:`model_special_rule`) so that it can be
imported by both without creating a circular import.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ModelStatistics:
    """The ten combat statistics of a Warmachine model.

    Used both as an absolute stat line and as a delta applied to one; see
    the module docstring. All statistics default to ``0``.

    Attributes:
        spd: Speed.
        aat: Arcane Attack.
        mat: Melee Attack.
        rat: Ranged Attack.
        def_: Defense. Named ``def_`` and serialised as ``"def"`` because
            ``def`` is a Python keyword.
        arm: Armor.
        arc: Arcana.
        fury: Fury.
        ctrl: Control Range.
        thr: Threshold.
    """

    spd: int = 0
    aat: int = 0
    mat: int = 0
    rat: int = 0
    def_: int = 0
    arm: int = 0
    arc: int = 0
    fury: int = 0
    ctrl: int = 0
    thr: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-compatible dictionary.

        Returns:
            Dictionary representation suitable for direct use with
            :func:`json.dumps`. Uses ``"def"`` as the key for :attr:`def_`.
        """
        return {
            "spd": self.spd,
            "aat": self.aat,
            "mat": self.mat,
            "rat": self.rat,
            "def": self.def_,
            "arm": self.arm,
            "arc": self.arc,
            "fury": self.fury,
            "ctrl": self.ctrl,
            "thr": self.thr,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ModelStatistics:
        """Deserialise from a dictionary produced by :meth:`to_dict`.

        Args:
            data: Dictionary as returned by :meth:`to_dict`.

        Returns:
            New :class:`ModelStatistics` instance, with any negative value
            clamped to ``0``.
        """

        def _get(key: str) -> int:
            value = int(data.get(key, 0))
            return max(0, value)

        return cls(
            spd=_get("spd"),
            aat=_get("aat"),
            mat=_get("mat"),
            rat=_get("rat"),
            def_=_get("def"),
            arm=_get("arm"),
            arc=_get("arc"),
            fury=_get("fury"),
            ctrl=_get("ctrl"),
            thr=_get("thr"),
        )

    def __add__(self, other: ModelStatistics) -> ModelStatistics:
        """Sum two stat blocks statistic by statistic.

        Args:
            other: Stat block to add, typically a delta.

        Returns:
            A new :class:`ModelStatistics` holding the sums. Results are
            not clamped, so combining deltas can yield negative values; use
            :meth:`clamped` when an absolute stat line is expected.
        """
        if not isinstance(other, ModelStatistics):
            return NotImplemented
        return ModelStatistics(
            spd=self.spd + other.spd,
            aat=self.aat + other.aat,
            mat=self.mat + other.mat,
            rat=self.rat + other.rat,
            def_=self.def_ + other.def_,
            arm=self.arm + other.arm,
            arc=self.arc + other.arc,
            fury=self.fury + other.fury,
            ctrl=self.ctrl + other.ctrl,
            thr=self.thr + other.thr,
        )

    def clamped(self) -> ModelStatistics:
        """Return a copy with every negative statistic replaced by ``0``.

        Returns:
            New :class:`ModelStatistics` suitable for use as an absolute
            stat line, e.g. after applying penalties that would take a
            statistic below zero.
        """
        return ModelStatistics(
            spd=max(0, self.spd),
            aat=max(0, self.aat),
            mat=max(0, self.mat),
            rat=max(0, self.rat),
            def_=max(0, self.def_),
            arm=max(0, self.arm),
            arc=max(0, self.arc),
            fury=max(0, self.fury),
            ctrl=max(0, self.ctrl),
            thr=max(0, self.thr),
        )
