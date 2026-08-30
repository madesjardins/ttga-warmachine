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

"""Shareable match settings loaded from YAML files.

Each YAML file under the ``match_settings`` folder defines one complete,
shareable match configuration for the Warmachine game: a display name shown
in the Game Mode dropdown, the army points value, and the deployment zone
depth for whichever player deploys first vs. second. Keeping one file per
configuration lets players author and share their own house-rule presets.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

NEMESIS_PLAYER_INDEX = 1
"""Player index (0-based) that always represents Nemesis, the CPU opponent.

The game is played by one human player (index 0) against Nemesis (index 1).
Nemesis has no physical presence, so the human player always physically
places its models and registers their QR codes, even when Nemesis is the
one deciding its army list and/or deployment positions.
"""


@dataclass
class MatchSettings:
    """A single match configuration loaded from a YAML file.

    The game is played by one human player against "Nemesis", a CPU
    opponent. The narrator is not Nemesis itself -- it reports Nemesis's
    decisions like a commentator would. Since Nemesis has no physical
    presence, the human player always physically places Nemesis's models
    (with their tracking QR codes) on the table, even when Nemesis is the
    one deciding the army list and/or deployment positions.

    Attributes:
        id: Canonical identifier for the setting (defaults to the filename
            stem if not specified in the YAML).
        display_name: Human-readable name shown in the Game Mode dropdown.
        points: Army points value each player builds to.
        first_player_depth_in: Deployment zone depth (inches) for whichever
            player deploys first.
        second_player_depth_in: Deployment zone depth (inches) for the
            player who deploys second (often deeper, to compensate).
        nemesis_chooses_army: If True, Nemesis picks its own army list
            (the player still physically registers each model's QR code).
            If False, the player picks Nemesis's army by voice, as usual.
        nemesis_chooses_deployment: If True, Nemesis decides where its own
            models deploy (per ``nemesis_deployment_strategy``); the player
            still physically places the models. If False, the player freely
            places Nemesis's models themselves.
        nemesis_deployment_strategy: Name of the strategy Nemesis uses to
            pick deployment positions when ``nemesis_chooses_deployment`` is
            True. Only ``"random"`` is implemented for now; more strategies
            (possibly authored as their own YAML files) may be added later.
        path: Source YAML file path, if loaded from disk.
    """

    id: str
    display_name: str
    points: int
    first_player_depth_in: float
    second_player_depth_in: float
    nemesis_chooses_army: bool = False
    nemesis_chooses_deployment: bool = False
    nemesis_deployment_strategy: str = "random"
    path: Optional[Path] = None


def load_match_settings(folder: Path) -> list[MatchSettings]:
    """Load all match settings YAML files from *folder*.

    Args:
        folder: Directory containing one ``.yaml`` file per match setting.
            Created automatically if it does not yet exist.

    Returns:
        List of :class:`MatchSettings`, sorted by display name. Files that
        are missing required fields or fail to parse are skipped silently.
    """
    folder.mkdir(parents=True, exist_ok=True)
    results: list[MatchSettings] = []
    for p in sorted(folder.glob("*.yaml")):
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            deployment = data.get("deployment", {})
            nemesis = data.get("nemesis", {})
            results.append(
                MatchSettings(
                    id=str(data.get("id", p.stem)),
                    display_name=str(data.get("display_name", p.stem)),
                    points=int(data["points"]),
                    first_player_depth_in=float(
                        deployment["first_player_depth_in"]
                    ),
                    second_player_depth_in=float(
                        deployment["second_player_depth_in"]
                    ),
                    nemesis_chooses_army=bool(
                        nemesis.get("chooses_army", False)
                    ),
                    nemesis_chooses_deployment=bool(
                        nemesis.get("chooses_deployment", False)
                    ),
                    nemesis_deployment_strategy=str(
                        nemesis.get("deployment_strategy", "random")
                    ),
                    path=p,
                )
            )
        except (OSError, yaml.YAMLError, KeyError, TypeError, ValueError):
            continue
    results.sort(key=lambda m: m.display_name.lower())
    return results
