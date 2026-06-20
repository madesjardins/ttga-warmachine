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

"""ModelDatabase: in-memory store for ModelStatCard objects with load/save."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .model_stat_card import Army, Keyword, ModelStatCard

_DEFAULT_ARMIES: list[str] = [a.value for a in Army]
_DEFAULT_KEYWORDS: list[str] = [k.value for k in Keyword]


class ModelDatabase:
    """In-memory database of :class:`ModelStatCard` objects.

    Models are keyed by their :attr:`~ModelStatCard.name` attribute.  Unsaved
    changes are tracked via the :attr:`is_dirty` property; call :meth:`save`
    to persist them to disk and :meth:`revert` to discard them.
    """

    def __init__(self, path: Optional[Path] = None) -> None:
        self._path: Optional[Path] = path
        self._models: dict[str, ModelStatCard] = {}
        self._armies: list[str] = list(_DEFAULT_ARMIES)
        self._keywords: list[str] = list(_DEFAULT_KEYWORDS)
        self._dirty: bool = False

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def path(self) -> Optional[Path]:
        """File path associated with this database, or ``None`` if unsaved."""
        return self._path

    @property
    def name(self) -> str:
        """Database name (file stem), or ``"Untitled"`` if no path is set."""
        return self._path.stem if self._path else "Untitled"

    @property
    def is_dirty(self) -> bool:
        """``True`` if there are unsaved changes."""
        return self._dirty

    @property
    def armies(self) -> list[str]:
        """Ordered list of army names defined in this database."""
        return self._armies

    @property
    def keywords(self) -> list[str]:
        """Ordered list of keywords defined in this database."""
        return self._keywords

    # ------------------------------------------------------------------
    # Factory helpers
    # ------------------------------------------------------------------

    @classmethod
    def new(cls, path: Path) -> ModelDatabase:
        """Create a new, empty database targeting *path*.

        The database is immediately marked dirty because it has not yet been
        written to disk.

        Args:
            path: Target file path for future :meth:`save` calls.

        Returns:
            New, empty :class:`ModelDatabase`.
        """
        db = cls(path=path)
        db._dirty = True
        return db

    @classmethod
    def load(cls, path: Path) -> ModelDatabase:
        """Load a database from a JSON file on disk.

        Args:
            path: Path to the ``.json`` database file.

        Returns:
            :class:`ModelDatabase` populated with the file's contents.

        Raises:
            FileNotFoundError: If *path* does not exist.
            json.JSONDecodeError: If the file is not valid JSON.
            ValueError: If a model record cannot be deserialised.
        """
        db = cls(path=path)
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            models_data = data
        else:
            db._armies = list(data.get("armies", _DEFAULT_ARMIES))
            db._keywords = list(data.get("keywords", _DEFAULT_KEYWORDS))
            models_data = data.get("models", [])
        for item in models_data:
            card = ModelStatCard.from_dict(item)
            db._models[card.name] = card
        db._dirty = False
        return db

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self) -> None:
        """Write the database to :attr:`path`.

        Raises:
            ValueError: If :attr:`path` is ``None``.
        """
        if self._path is None:
            raise ValueError("No path set; cannot save the database.")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "armies": self._armies,
            "keywords": self._keywords,
            "models": [card.to_dict() for card in self._models.values()],
        }
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        self._dirty = False

    def revert(self) -> None:
        """Discard all unsaved changes.

        If :attr:`path` points to an existing file the database is reloaded
        from disk.  If the file does not yet exist (newly created database
        that was never saved) the model list is simply cleared.
        """
        self._models.clear()
        self._armies = list(_DEFAULT_ARMIES)
        self._keywords = list(_DEFAULT_KEYWORDS)
        if self._path and self._path.exists():
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                models_data = data
            else:
                self._armies = list(data.get("armies", _DEFAULT_ARMIES))
                self._keywords = list(data.get("keywords", _DEFAULT_KEYWORDS))
                models_data = data.get("models", [])
            for item in models_data:
                card = ModelStatCard.from_dict(item)
                self._models[card.name] = card
        self._dirty = False

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def add_model(self, card: ModelStatCard) -> None:
        """Add or replace a model in the database.

        Args:
            card: Model to add.  If a model with the same
                :attr:`~ModelStatCard.name` already exists it is overwritten.
        """
        self._models[card.name] = card
        self._dirty = True

    def update_model(self, original_name: str, card: ModelStatCard) -> None:
        """Replace an existing model, handling renames transparently.

        Args:
            original_name: Name of the model before editing.
            card: Updated model card (may carry a different name).
        """
        if original_name in self._models and original_name != card.name:
            del self._models[original_name]
        self._models[card.name] = card
        self._dirty = True

    def remove_models(self, names: list[str]) -> None:
        """Remove one or more models by name.

        Missing names are silently ignored.

        Args:
            names: Names of models to remove.
        """
        for name in names:
            self._models.pop(name, None)
        if names:
            self._dirty = True

    def add_army(self, name: str) -> bool:
        """Add *name* to the database's army list if not already present.

        Args:
            name: Army name to add.

        Returns:
            ``True`` if added, ``False`` if it already existed.
        """
        name = name.strip()
        if not name or name in self._armies:
            return False
        self._armies.append(name)
        self._armies.sort()
        self._dirty = True
        return True

    def add_keyword(self, name: str) -> bool:
        """Add *name* to the database's keyword list if not already present.

        Args:
            name: Keyword to add.

        Returns:
            ``True`` if added, ``False`` if it already existed.
        """
        name = name.strip()
        if not name or name in self._keywords:
            return False
        self._keywords.append(name)
        self._keywords.sort()
        self._dirty = True
        return True

    def get_model(self, name: str) -> Optional[ModelStatCard]:
        """Return the model with *name*, or ``None`` if not found."""
        return self._models.get(name)

    def all_models(self) -> list[ModelStatCard]:
        """Return all models as a list in insertion order."""
        return list(self._models.values())

    def __len__(self) -> int:
        return len(self._models)
