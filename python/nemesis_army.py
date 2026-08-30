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

"""Nemesis army auto-builder.

When a match's settings enable ``nemesis.chooses_army``, Nemesis (the CPU
opponent) picks its own army list instead of the player choosing it by
voice. The player still needs to physically place each model's tracking QR
code on the table, exactly as with a player-chosen army.
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .model_database import ModelDatabase
    from .model_stat_card import ModelStatCard


def build_random_army(
    db: ModelDatabase,
    faction: str,
    points: int,
    *,
    rng: Optional[random.Random] = None,
) -> list[ModelStatCard]:
    """Randomly build a legal army list for *faction* within *points*.

    Greedily and repeatedly adds a random affordable entry (respecting
    Field Allowance limits) until nothing more fits in the remaining
    budget, or the faction's model pool is empty.

    Args:
        db: Model database to pick entries from.
        faction: Faction name to filter models by (Mercenaries included).
        points: Maximum total point cost of the army.
        rng: Optional deterministic random source (useful for tests).

    Returns:
        List of :class:`ModelStatCard` entries whose total cost does not
        exceed *points*. Empty if no affordable entry exists.
    """
    rng = rng or random.Random()
    pool = db.models_by_faction(faction, include_mercenaries=True)
    if not pool or points <= 0:
        return []

    army: list[ModelStatCard] = []
    fa_used: dict[str, int] = {}
    remaining = points

    added_any = True
    while remaining > 0 and added_any:
        added_any = False
        candidates = list(pool)
        rng.shuffle(candidates)
        for card in candidates:
            if card.cost <= 0 or card.cost > remaining:
                continue
            if card.fa != -1 and fa_used.get(card.name, 0) >= card.fa:
                continue
            army.append(card)
            fa_used[card.name] = fa_used.get(card.name, 0) + 1
            remaining -= card.cost
            added_any = True
            break

    return army
