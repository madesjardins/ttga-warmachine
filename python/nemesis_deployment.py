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

"""Nemesis deployment strategies.

When a match's settings enable ``nemesis.chooses_deployment``, Nemesis (the
CPU opponent) decides where its own models deploy. Since Nemesis has no
physical presence, a strategy only *proposes* legal positions -- shown to
the player as ghost markers on the projector -- for the player to physically
place Nemesis's models at. The actual placement is still validated against
the real deployment rules once QR codes are detected (see
:mod:`deployment`), so a strategy's suggestions do not need to be perfect.

Strategies are registered by name so match settings YAML can select one via
``nemesis.deployment_strategy``. Only ``"random"`` is implemented for now;
more strategies (possibly authored as their own YAML files) may be added
later.
"""

from __future__ import annotations

import math
import random
from typing import Callable, Optional

_UNIT_COHESION_IN = 3.0


def _distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def random_strategy(
    zone_rect: tuple[float, float, float, float],
    units: list[list[float]],
    *,
    max_attempts_per_model: int = 300,
    rng: Optional[random.Random] = None,
) -> list[list[tuple[float, float]]]:
    """Propose random legal positions for every physical model in *units*.

    For each unit, the first model is placed anywhere in the zone; every
    subsequent model in the same unit is anchored near a random unit-mate
    (within the 3" cohesion distance). Every candidate is checked against
    all previously placed models (across all units) to avoid base overlap,
    and clamped so its base stays fully inside the zone.

    This is a best-effort placement: if no valid spot is found within
    *max_attempts_per_model* tries, the last sampled candidate is used
    anyway (clamped to the zone). Real placement is validated separately
    once the player places the physical models, so this only affects the
    quality of the suggested ghost markers.

    Args:
        zone_rect: ``(x_min, y_min, x_max, y_max)`` deployment zone, inches.
        units: One inner list per army entry; each value is a physical
            model's base radius in inches. A single-model entry is a unit
            of length 1.
        max_attempts_per_model: Random retries before falling back to the
            last sampled (possibly imperfect) candidate.
        rng: Optional deterministic random source (useful for tests).

    Returns:
        Positions parallel to *units*: one ``(x, y)`` tuple per physical
        model.
    """
    rng = rng or random.Random()
    x_min, y_min, x_max, y_max = zone_rect
    placed: list[tuple[float, float, float]] = []  # (x, y, radius)
    result: list[list[tuple[float, float]]] = []

    def clamp_to_zone(x: float, y: float, r: float) -> tuple[float, float]:
        lo_x, hi_x = x_min + r, x_max - r
        lo_y, hi_y = y_min + r, y_max - r
        if hi_x < lo_x:
            lo_x = hi_x = (x_min + x_max) / 2.0
        if hi_y < lo_y:
            lo_y = hi_y = (y_min + y_max) / 2.0
        return min(max(x, lo_x), hi_x), min(max(y, lo_y), hi_y)

    def random_in_zone(r: float) -> tuple[float, float]:
        lo_x, hi_x = x_min + r, x_max - r
        lo_y, hi_y = y_min + r, y_max - r
        if hi_x < lo_x:
            lo_x = hi_x = (x_min + x_max) / 2.0
        if hi_y < lo_y:
            lo_y = hi_y = (y_min + y_max) / 2.0
        return rng.uniform(lo_x, hi_x), rng.uniform(lo_y, hi_y)

    def overlaps_any(x: float, y: float, r: float) -> bool:
        return any(
            _distance((x, y), (px, py)) < (r + pr) for px, py, pr in placed
        )

    def cohesion_ok(
        x: float, y: float, members: list[tuple[float, float, float]]
    ) -> bool:
        return all(
            _distance((x, y), (mx, my)) <= _UNIT_COHESION_IN
            for mx, my, _ in members
        )

    for radii in units:
        unit_members: list[tuple[float, float, float]] = []
        unit_positions: list[tuple[float, float]] = []
        for r in radii:
            best: Optional[tuple[float, float]] = None
            x = y = 0.0
            for _ in range(max_attempts_per_model):
                if not unit_members:
                    x, y = random_in_zone(r)
                else:
                    ax, ay, ar = rng.choice(unit_members)
                    angle = rng.uniform(0.0, 2.0 * math.pi)
                    min_dist = ar + r
                    max_dist = max(min_dist, _UNIT_COHESION_IN)
                    dist = rng.uniform(min_dist, max_dist)
                    x = ax + dist * math.cos(angle)
                    y = ay + dist * math.sin(angle)
                    x, y = clamp_to_zone(x, y, r)
                if not overlaps_any(x, y, r) and cohesion_ok(
                    x, y, unit_members
                ):
                    best = (x, y)
                    break
            if best is None:
                best = clamp_to_zone(x, y, r)
            unit_members.append((best[0], best[1], r))
            placed.append((best[0], best[1], r))
            unit_positions.append(best)
        result.append(unit_positions)

    return result


_STRATEGIES: dict[
    str, Callable[..., list[list[tuple[float, float]]]]
] = {
    "random": random_strategy,
}


def get_strategy(
    name: str,
) -> Callable[..., list[list[tuple[float, float]]]]:
    """Look up a registered Nemesis deployment strategy by name.

    Args:
        name: Strategy name, as configured by
            ``MatchSettings.nemesis_deployment_strategy``.

    Returns:
        The strategy function, callable as
        ``strategy(zone_rect, units, **kwargs)``.

    Raises:
        KeyError: If *name* is not a registered strategy.
    """
    return _STRATEGIES[name]
