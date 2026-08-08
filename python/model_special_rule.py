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

Defines the :class:`ModelSpecialRule` base class and all concrete rule
implementations.

Adding a new rule
------------------
1. Subclass :class:`ModelSpecialRule` and set the ``name`` and ``trigger``
   class attributes.
2. Register the class by adding it to the ``_RULE_CLASSES`` list near the
   bottom of this module.
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------


class ModelSpecialRule:
    """Base class for all model special rules.

    Attributes:
        name: Human-readable name of the rule, used for serialisation and
            display. Must be unique across all registered rules.
        trigger: Description of the condition that triggers this rule.
    """

    name: str = ""
    trigger: str = ""


# ---------------------------------------------------------------------------
# Concrete rules
# ---------------------------------------------------------------------------


class QuickWork(ModelSpecialRule):
    """Quick Work model special rule."""

    name = "Quick Work"
    trigger = "Destroy one or more enemy models"


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_RULE_CLASSES: list[type[ModelSpecialRule]] = [
    QuickWork,
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
