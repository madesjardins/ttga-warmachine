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

"""Damage system module for the Warmachine game.

Defines the four damage system types used by Warmachine models (box, grid,
spiral and web) together with all supporting enums and dataclasses.  Every
class is JSON-serializable via its :meth:`to_dict` / :meth:`from_dict` pair.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, Union


GRID_SIZE: int = 6
"""Side length (in cells) of a damage grid."""


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class DamageSystemType(str, Enum):
    """Discriminator tag identifying which damage system a model uses.

    Values are intentionally kept as human-readable strings so they
    serialise cleanly to JSON without a custom encoder.
    """

    BOX = "box"
    GRID = "grid"
    SPIRAL = "spiral"
    WEB = "web"


class DamageKey(str, Enum):
    """Cell type within a 6×6 damage grid.

    Values are intentionally kept as human-readable strings so they
    serialise cleanly to JSON without a custom encoder.

    Attributes:
        NA: Cell is not applicable for this model.
        BLANK: Empty / undamaged cell.
        A: Arcane system.
        F: Fire system.
        C: Cortex system.
        L: Left arm system.
        G: Gun system.
        R: Right arm system.
        H: Head system.
        M: Movement system.
    """

    NA = "NA"
    BLANK = "BLANK"
    A = "A"
    F = "F"
    C = "C"
    L = "L"
    G = "G"
    R = "R"
    H = "H"
    M = "M"
    S = "S"


# ---------------------------------------------------------------------------
# Grid factory helper
# ---------------------------------------------------------------------------


def _default_grid() -> list[list[DamageKey]]:
    """Return a fresh GRID_SIZE × GRID_SIZE grid filled with BLANK cells."""
    return [[DamageKey.BLANK] * GRID_SIZE for _ in range(GRID_SIZE)]


def _grid_to_list(grid: list[list[DamageKey]]) -> list[list[str]]:
    """Serialise a damage grid to a nested list of strings."""
    return [[cell.value for cell in row] for row in grid]


def _grid_from_list(data: list[list[str]]) -> list[list[DamageKey]]:
    """Deserialise a damage grid from a nested list of strings."""
    return [[DamageKey(cell) for cell in row] for row in data]


# ---------------------------------------------------------------------------
# Box damage system
# ---------------------------------------------------------------------------


@dataclass
class BoxDamageSystem:
    """Simple box damage system: a single integer hit-point pool.

    Attributes:
        boxes: Total number of damage boxes. Must be >= 1.
    """

    boxes: int = 1

    def __post_init__(self) -> None:
        """Validate that boxes is at least 1.

        Raises:
            ValueError: If boxes < 1.
        """
        if self.boxes < 1:
            raise ValueError(f"boxes must be >= 1, got {self.boxes}")

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-compatible dictionary.

        Returns:
            Dictionary representation suitable for direct use with
            :func:`json.dumps`.
        """
        return {"boxes": self.boxes}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BoxDamageSystem:
        """Deserialise from a dictionary produced by :meth:`to_dict`.

        Args:
            data: Dictionary as returned by :meth:`to_dict`.

        Returns:
            New :class:`BoxDamageSystem` instance.
        """
        return cls(boxes=int(data.get("boxes", 1)))


# ---------------------------------------------------------------------------
# Grid damage system
# ---------------------------------------------------------------------------


@dataclass
class GridDamageSystem:
    """Damage grid system: one or two 6×6 grids of :class:`DamageKey` cells.

    When a model has two damage grids they represent the left and right
    halves of the model (e.g. a warjack chassis).  A single-grid model
    stores its grid in :attr:`left_grid` and leaves :attr:`right_grid` as
    ``None``.

    Attributes:
        left_grid: Primary (or only) damage grid.  Must be
            :data:`GRID_SIZE` × :data:`GRID_SIZE`.
        right_grid: Optional second damage grid.  When present must also be
            :data:`GRID_SIZE` × :data:`GRID_SIZE`.
    """

    left_grid: list[list[DamageKey]] = field(default_factory=_default_grid)
    right_grid: Optional[list[list[DamageKey]]] = None

    def __post_init__(self) -> None:
        """Validate grid dimensions.

        Raises:
            ValueError: If either grid does not have the expected dimensions.
        """
        self._validate_grid(self.left_grid, "left_grid")
        if self.right_grid is not None:
            self._validate_grid(self.right_grid, "right_grid")

    @staticmethod
    def _validate_grid(grid: list[list[DamageKey]], name: str) -> None:
        """Raise ValueError if *grid* is not GRID_SIZE × GRID_SIZE.

        Args:
            grid: Grid to validate.
            name: Attribute name used in the error message.

        Raises:
            ValueError: If the grid dimensions are incorrect.
        """
        if len(grid) != GRID_SIZE:
            raise ValueError(
                f"{name} must have {GRID_SIZE} rows, got {len(grid)}"
            )
        for i, row in enumerate(grid):
            if len(row) != GRID_SIZE:
                raise ValueError(
                    f"{name} row {i} must have {GRID_SIZE} cells, got {len(row)}"
                )

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-compatible dictionary.

        Returns:
            Dictionary representation suitable for direct use with
            :func:`json.dumps`.
        """
        result: dict[str, Any] = {"left_grid": _grid_to_list(self.left_grid)}
        if self.right_grid is not None:
            result["right_grid"] = _grid_to_list(self.right_grid)
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GridDamageSystem:
        """Deserialise from a dictionary produced by :meth:`to_dict`.

        Args:
            data: Dictionary as returned by :meth:`to_dict`.

        Returns:
            New :class:`GridDamageSystem` instance.
        """
        left = _grid_from_list(data.get("left_grid", _default_grid()))
        right_data = data.get("right_grid")
        right = _grid_from_list(right_data) if right_data is not None else None
        return cls(left_grid=left, right_grid=right)


# ---------------------------------------------------------------------------
# Spiral damage system
# ---------------------------------------------------------------------------


@dataclass
class SpiralAspect:
    """One of the three aspects (Mind, Body, Spirit) in a life spiral.

    Each aspect is divided into two branches and a shared common section,
    all represented as integer capacities.

    Attributes:
        branch1: First branch capacity.
        branch2: Second branch capacity.
        common: Shared / central section capacity.
    """

    branch1: int = 0
    branch2: int = 0
    common: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-compatible dictionary.

        Returns:
            Dictionary representation suitable for direct use with
            :func:`json.dumps`.
        """
        return {
            "branch1": self.branch1,
            "branch2": self.branch2,
            "common": self.common,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SpiralAspect:
        """Deserialise from a dictionary produced by :meth:`to_dict`.

        Args:
            data: Dictionary as returned by :meth:`to_dict`.

        Returns:
            New :class:`SpiralAspect` instance.
        """
        return cls(
            branch1=int(data.get("branch1", 0)),
            branch2=int(data.get("branch2", 0)),
            common=int(data.get("common", 0)),
        )


@dataclass
class SpiralDamageSystem:
    """Life-spiral damage system used by warlocks and warbeasts.

    The spiral consists of three aspects—Mind, Body and Spirit—each
    represented by a :class:`SpiralAspect`.

    Attributes:
        mind: Mind aspect.
        body: Body aspect.
        spirit: Spirit aspect.
    """

    mind: SpiralAspect = field(default_factory=SpiralAspect)
    body: SpiralAspect = field(default_factory=SpiralAspect)
    spirit: SpiralAspect = field(default_factory=SpiralAspect)

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-compatible dictionary.

        Returns:
            Dictionary representation suitable for direct use with
            :func:`json.dumps`.
        """
        return {
            "mind": self.mind.to_dict(),
            "body": self.body.to_dict(),
            "spirit": self.spirit.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SpiralDamageSystem:
        """Deserialise from a dictionary produced by :meth:`to_dict`.

        Args:
            data: Dictionary as returned by :meth:`to_dict`.

        Returns:
            New :class:`SpiralDamageSystem` instance.
        """
        return cls(
            mind=SpiralAspect.from_dict(data.get("mind", {})),
            body=SpiralAspect.from_dict(data.get("body", {})),
            spirit=SpiralAspect.from_dict(data.get("spirit", {})),
        )


# ---------------------------------------------------------------------------
# Web damage system
# ---------------------------------------------------------------------------


@dataclass
class WebDamageSystem:
    """Damage-web system made up of three concentric rings.

    Attributes:
        outer: Outer ring capacity.
        middle: Middle ring capacity.
        center: Center ring capacity.
    """

    outer: int = 0
    middle: int = 0
    center: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-compatible dictionary.

        Returns:
            Dictionary representation suitable for direct use with
            :func:`json.dumps`.
        """
        return {
            "outer": self.outer,
            "middle": self.middle,
            "center": self.center,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WebDamageSystem:
        """Deserialise from a dictionary produced by :meth:`to_dict`.

        Args:
            data: Dictionary as returned by :meth:`to_dict`.

        Returns:
            New :class:`WebDamageSystem` instance.
        """
        return cls(
            outer=int(data.get("outer", 0)),
            middle=int(data.get("middle", 0)),
            center=int(data.get("center", 0)),
        )


# ---------------------------------------------------------------------------
# Union type alias and factory helper
# ---------------------------------------------------------------------------


AnyDamageSystem = Union[BoxDamageSystem, GridDamageSystem, SpiralDamageSystem, WebDamageSystem]
"""Type alias for any concrete damage system."""


def damage_system_from_dict(
    system_type: DamageSystemType, data: dict[str, Any]
) -> AnyDamageSystem:
    """Deserialise a damage system using a type discriminator.

    Args:
        system_type: The :class:`DamageSystemType` that identifies which
            concrete class to instantiate.
        data: Serialised damage system dictionary as returned by the
            corresponding ``to_dict`` method.

    Returns:
        Concrete damage system instance matching *system_type*.

    Raises:
        ValueError: If *system_type* is not a recognised value.
    """
    if system_type == DamageSystemType.BOX:
        return BoxDamageSystem.from_dict(data)
    if system_type == DamageSystemType.GRID:
        return GridDamageSystem.from_dict(data)
    if system_type == DamageSystemType.SPIRAL:
        return SpiralDamageSystem.from_dict(data)
    if system_type == DamageSystemType.WEB:
        return WebDamageSystem.from_dict(data)
    raise ValueError(f"Unknown damage system type: {system_type!r}")
