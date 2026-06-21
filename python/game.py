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

"""Warmachine game - TTGA port for the tabletop miniatures wargame Warmachine.

This game provides augmented reality support for Warmachine matches played on
a physical table, using camera and projector calibration to overlay game
information on the play area.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional

import numpy as np
import yaml
from PySide6 import QtCore, QtWidgets

if TYPE_CHECKING:
    from ttga.main_core import MainCore

from ttga.game_base import GameBase
from ttga.game_dialog import GameDialog, ZoneRequirement
from ttga.narration_engine import NarrationEngine
from ttga.qr_detection import QRDetector

from .event_manager import GameEventManager
from .match import Match
from .model_database import ModelDatabase
from .model_editor_dialog import ModelEditorDialog
from .model_stat_card import BasicType, ModelStatCard
from .persona import WARMACHINE_PERSONA

_MODELS_DB_DIR = Path(__file__).parent.parent / "models_db"
_MAX_LOG_DISPLAY_LINES = 100

_SORT_OPTIONS: list[tuple[str, Optional[Callable]]] = [
    ("(None)", None),
    ("Name", lambda m: m.name.lower()),
    ("Short Name", lambda m: m.short_name.lower()),
    ("Faction", lambda m: m.faction.value),
    ("Basic Type", lambda m: m.basic_type.value),
    ("Cost", lambda m: m.cost),
    ("FA", lambda m: m.fa),
    ("Base Size", lambda m: m.base_size),
    ("Is Character", lambda m: 0 if m.is_character else 1),
]


class WarmachineDialog(GameDialog):
    """Custom dialog for the Warmachine game."""

    def __init__(
        self,
        core: MainCore,
        game_name: str,
        zone_requirements: list[ZoneRequirement],
        settings: dict,
        game_instance,
        parent: Optional[QtWidgets.QWidget] = None,
        *,
        event_manager: Optional[GameEventManager] = None,
    ) -> None:
        """Initialize the Warmachine dialog.

        Args:
            core: MainCore instance.
            game_name: Name of the game.
            zone_requirements: List of zone requirements.
            settings: Game settings from YAML.
            game_instance: Reference to the Game instance.
            parent: Parent widget.
        """
        self.settings = settings
        self.game_instance = game_instance
        self._current_db: Optional[ModelDatabase] = None
        self._event_manager = event_manager
        self._match: Optional[Match] = None
        super().__init__(core, game_name, zone_requirements, parent)

        # Add extra tabs after base class has built the tab widget
        models_tab = self._create_models_tab()
        self.tabs.addTab(models_tab, "Models")

        ingame_tab = self._create_ingame_tab()
        self._ingame_tab_index = self.tabs.addTab(ingame_tab, "In-game")

        log_tab = self._create_log_tab()
        self._log_tab_index = self.tabs.addTab(log_tab, "Log")

        self._populate_database_combo()

    def _create_main_tab(self) -> QtWidgets.QWidget:
        """Create the main tab with Start/Stop game buttons.

        Returns:
            Widget containing main game controls.
        """
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(widget)

        # Instructions
        instructions = QtWidgets.QLabel(
            "Start the game to begin a Warmachine match. "
            "Make sure zones are validated and a models database is selected before starting."
        )
        instructions.setWordWrap(True)
        layout.addWidget(instructions)

        layout.addSpacing(10)

        # Game Mode
        mode_row = QtWidgets.QHBoxLayout()
        mode_row.addWidget(QtWidgets.QLabel("Game Mode:"))
        self.game_mode_combo = QtWidgets.QComboBox()
        self.game_mode_combo.addItem("Single Match", "single_match")
        mode_row.addWidget(self.game_mode_combo, stretch=1)
        layout.addLayout(mode_row)

        # Options (empty placeholder for now)
        self.options_group = QtWidgets.QGroupBox("Options")
        options_layout = QtWidgets.QVBoxLayout(self.options_group)
        self._options_placeholder = QtWidgets.QLabel(
            "No options available for this game mode."
        )
        self._options_placeholder.setStyleSheet("color: #888;")
        options_layout.addWidget(self._options_placeholder)
        layout.addWidget(self.options_group)

        layout.addSpacing(10)

        # Game status
        self.game_status_label = QtWidgets.QLabel("Game Status: Not Started")
        self.game_status_label.setStyleSheet(
            "QLabel { font-weight: bold; padding: 10px; background-color: #f0f0f0; }"
        )
        layout.addWidget(self.game_status_label)

        layout.addSpacing(10)

        # Start/Stop buttons
        button_layout = QtWidgets.QHBoxLayout()

        self.start_game_button = QtWidgets.QPushButton("Start Game")
        self.start_game_button.clicked.connect(self._on_start_game)
        button_layout.addWidget(self.start_game_button)

        self.stop_game_button = QtWidgets.QPushButton("Stop Game")
        self.stop_game_button.clicked.connect(self._on_stop_game)
        self.stop_game_button.setEnabled(False)
        button_layout.addWidget(self.stop_game_button)

        layout.addLayout(button_layout)

        layout.addStretch()

        return widget

    # ------------------------------------------------------------------
    # In-game tab
    # ------------------------------------------------------------------

    def _create_ingame_tab(self) -> QtWidgets.QWidget:
        """Create the In-game tab with phase display and army lists."""
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(widget)

        # Phase title
        self.phase_title_label = QtWidgets.QLabel("No match in progress.")
        self.phase_title_label.setStyleSheet(
            "QLabel { font-size: 16px; font-weight: bold; padding: 6px; }"
        )
        layout.addWidget(self.phase_title_label)

        # Status / instruction line
        self.ingame_status_label = QtWidgets.QLabel("")
        self.ingame_status_label.setWordWrap(True)
        self.ingame_status_label.setStyleSheet(
            "QLabel { padding: 4px; color: #555; }"
        )
        layout.addWidget(self.ingame_status_label)

        # Army lists (side by side)
        armies_row = QtWidgets.QHBoxLayout()

        p1_group = QtWidgets.QGroupBox("Player 1 Army")
        p1_layout = QtWidgets.QVBoxLayout(p1_group)
        self.p1_army_list = QtWidgets.QListWidget()
        self.p1_army_list.setAlternatingRowColors(True)
        p1_layout.addWidget(self.p1_army_list)
        self.p1_points_label = QtWidgets.QLabel("Total: 0 pts")
        self.p1_points_label.setStyleSheet(
            "QLabel { font-weight: bold; padding: 4px; }"
        )
        self.p1_points_label.setAlignment(QtCore.Qt.AlignRight)
        p1_layout.addWidget(self.p1_points_label)
        armies_row.addWidget(p1_group)

        p2_group = QtWidgets.QGroupBox("Player 2 Army")
        p2_layout = QtWidgets.QVBoxLayout(p2_group)
        self.p2_army_list = QtWidgets.QListWidget()
        self.p2_army_list.setAlternatingRowColors(True)
        p2_layout.addWidget(self.p2_army_list)
        self.p2_points_label = QtWidgets.QLabel("Total: 0 pts")
        self.p2_points_label.setStyleSheet(
            "QLabel { font-weight: bold; padding: 4px; }"
        )
        self.p2_points_label.setAlignment(QtCore.Qt.AlignRight)
        p2_layout.addWidget(self.p2_points_label)
        armies_row.addWidget(p2_group)

        layout.addLayout(armies_row, stretch=1)

        # General-purpose content area for future phases
        self.ingame_content_area = QtWidgets.QStackedWidget()
        empty_page = QtWidgets.QWidget()
        self.ingame_content_area.addWidget(empty_page)
        layout.addWidget(self.ingame_content_area)

        return widget

    # ------------------------------------------------------------------
    # Log tab
    # ------------------------------------------------------------------

    def _create_log_tab(self) -> QtWidgets.QWidget:
        """Create the Log tab showing the latest narrator / player lines."""
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(widget)

        self.log_text = QtWidgets.QPlainTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumBlockCount(_MAX_LOG_DISPLAY_LINES)
        self.log_text.setStyleSheet(
            "QPlainTextEdit { font-family: 'Segoe UI', sans-serif; "
            "font-size: 12px; line-height: 1.4; }"
        )
        layout.addWidget(self.log_text)

        return widget

    def _create_models_tab(self) -> QtWidgets.QWidget:
        """Create the Models tab with full database management UI.

        Returns:
            Widget containing models configuration UI.
        """
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(widget)

        # --- Row 1: database selector + New / Save / Revert ---
        db_row = QtWidgets.QHBoxLayout()
        db_row.addWidget(QtWidgets.QLabel("Models Database"))
        self.models_database_combo = QtWidgets.QComboBox()
        self.models_database_combo.addItem("-- Choose a database --", None)
        self.models_database_combo.currentIndexChanged.connect(
            self._on_models_database_changed
        )
        db_row.addWidget(self.models_database_combo, stretch=1)

        db_btn_col = QtWidgets.QVBoxLayout()
        self.new_db_btn = QtWidgets.QPushButton("New")
        self.new_db_btn.clicked.connect(self._on_new_database)
        self.save_db_btn = QtWidgets.QPushButton("Save")
        self.save_db_btn.clicked.connect(self._on_save_database)
        self.save_db_btn.setEnabled(False)
        self.revert_db_btn = QtWidgets.QPushButton("Revert")
        self.revert_db_btn.clicked.connect(self._on_revert_database)
        self.revert_db_btn.setEnabled(False)
        for btn in (self.new_db_btn, self.save_db_btn, self.revert_db_btn):
            db_btn_col.addWidget(btn)
        db_row.addLayout(db_btn_col)
        layout.addLayout(db_row)

        # --- Row 2: search ---
        search_row = QtWidgets.QHBoxLayout()
        search_row.addWidget(QtWidgets.QLabel("Search:"))
        self.search_edit = QtWidgets.QLineEdit()
        self.search_edit.setPlaceholderText("Filter models…")
        self.search_edit.textChanged.connect(self._refresh_models_list)
        search_row.addWidget(self.search_edit, stretch=1)
        self.search_mode_combo = QtWidgets.QComboBox()
        self.search_mode_combo.addItems(["And", "Or"])
        self.search_mode_combo.currentIndexChanged.connect(self._refresh_models_list)
        search_row.addWidget(self.search_mode_combo)
        layout.addLayout(search_row)

        # --- Row 2b: filters ---
        filter_row = QtWidgets.QHBoxLayout()
        self.hide_troopers_cb = QtWidgets.QCheckBox("Hide Troopers")
        self.hide_troopers_cb.setChecked(True)
        self.hide_troopers_cb.stateChanged.connect(self._refresh_models_list)
        filter_row.addWidget(self.hide_troopers_cb)
        filter_row.addStretch()
        layout.addLayout(filter_row)

        # --- Row 3: sort ---
        sort_row = QtWidgets.QHBoxLayout()
        sort_row.addWidget(QtWidgets.QLabel("Sort by:"))
        _DEFAULT_SORT = ["Faction", "Basic Type", "Base Size", "Is Character", "Name"]
        self.sort_combos: list[QtWidgets.QComboBox] = []
        for default_label in _DEFAULT_SORT:
            combo = QtWidgets.QComboBox()
            for label, key_fn in _SORT_OPTIONS:
                combo.addItem(label, key_fn)
            idx = combo.findText(default_label)
            if idx >= 0:
                combo.setCurrentIndex(idx)
            combo.currentIndexChanged.connect(self._refresh_models_list)
            sort_row.addWidget(combo)
            self.sort_combos.append(combo)
        sort_row.addStretch()
        layout.addLayout(sort_row)

        # --- Row 4: models list + action buttons ---
        models_row = QtWidgets.QHBoxLayout()
        self.models_list = QtWidgets.QListWidget()
        self.models_list.setSelectionMode(
            QtWidgets.QAbstractItemView.ExtendedSelection
        )
        self.models_list.itemSelectionChanged.connect(
            self._on_models_selection_changed
        )
        self.models_list.itemDoubleClicked.connect(self._on_edit_model)
        models_row.addWidget(self.models_list, stretch=1)

        model_btn_col = QtWidgets.QVBoxLayout()
        self.create_model_btn = QtWidgets.QPushButton("Create Model")
        self.create_model_btn.clicked.connect(self._on_create_model)
        self.create_model_btn.setEnabled(False)
        self.edit_model_btn = QtWidgets.QPushButton("Edit Selected")
        self.edit_model_btn.clicked.connect(self._on_edit_model)
        self.edit_model_btn.setEnabled(False)
        self.delete_models_btn = QtWidgets.QPushButton("Delete Selected")
        self.delete_models_btn.clicked.connect(self._on_delete_models)
        self.delete_models_btn.setEnabled(False)
        for btn in (self.create_model_btn, self.edit_model_btn, self.delete_models_btn):
            model_btn_col.addWidget(btn)
        model_btn_col.addStretch()
        models_row.addLayout(model_btn_col)
        layout.addLayout(models_row)

        return widget

    def _on_start_game(self) -> None:
        """Handle start game button click."""
        self._on_validate_zones()

        if not self.is_validated():
            QtWidgets.QMessageBox.warning(
                self,
                "Validation Failed",
                "Please fix zone validation errors before starting the game."
            )
            return

        if self._current_db is None:
            QtWidgets.QMessageBox.warning(
                self,
                "No Database",
                "Please select a models database before starting the game."
            )
            return

        zone_mapping = self.get_zone_mapping()
        success = self.game_instance.start_game(zone_mapping)
        if not success:
            QtWidgets.QMessageBox.critical(
                self,
                "Game Start Failed",
                "Failed to start the game. Check console for errors."
            )
            return

        # Create a Match based on game mode
        core = self.game_instance.core
        narrator = getattr(core, "narrator", None)
        # The LLM client is optional and owned at core level (added in a later
        # step). When absent or unavailable, NarrationEngine falls back to the
        # scripted lines, so the game runs identically without an LLM.
        llm_client = getattr(core, "llm_client", None)
        narration_engine = NarrationEngine(
            llm_client=llm_client, persona=WARMACHINE_PERSONA
        )
        self._match = Match(
            db=self._current_db,
            event_manager=self._event_manager,
            narrator=narrator,
            narration_engine=narration_engine,
            parent=self,
        )

        # Wire match signals
        self._match.phase_changed.connect(self._on_phase_changed)
        self._match.match_ended.connect(self._on_match_ended)
        self._match.log.line_added.connect(self._on_log_line)

        # Wire army creation signals once the phase starts
        self._match.phase_changed.connect(self._wire_army_creation)

        # Update UI
        self.game_status_label.setText("Game Status: Running")
        self.game_status_label.setStyleSheet(
            "QLabel { font-weight: bold; padding: 10px; "
            "background-color: #ccffcc; color: #008800; }"
        )
        self.start_game_button.setEnabled(False)
        self.stop_game_button.setEnabled(True)

        # Clear In-game tab
        self.p1_army_list.clear()
        self.p2_army_list.clear()
        self.log_text.clear()

        # Switch to In-game tab and start the match
        self.tabs.setCurrentIndex(self._ingame_tab_index)
        self._match.start()

    def _on_stop_game(self) -> None:
        """Handle stop game button click."""
        if self._match is not None:
            self._match.stop()
            self._match = None

        self.game_instance.stop_game()

        self.game_status_label.setText("Game Status: Stopped")
        self.game_status_label.setStyleSheet(
            "QLabel { font-weight: bold; padding: 10px; "
            "background-color: #ffcccc; color: #cc0000; }"
        )
        self.start_game_button.setEnabled(True)
        self.stop_game_button.setEnabled(False)
        self.phase_title_label.setText("No match in progress.")
        self.ingame_status_label.setText("")
        self.p1_army_list.clear()
        self.p2_army_list.clear()
        self._update_army_points()

    # ------------------------------------------------------------------
    # Match signal handlers
    # ------------------------------------------------------------------

    @QtCore.Slot(str)
    def _on_phase_changed(self, phase_value: str) -> None:
        self.phase_title_label.setText(phase_value)

    @QtCore.Slot()
    def _on_match_ended(self) -> None:
        self.phase_title_label.setText("Match ended.")
        self.ingame_status_label.setText("")

    @QtCore.Slot(str)
    def _on_log_line(self, text: str) -> None:
        self.log_text.appendPlainText(text)

    @QtCore.Slot(str)
    def _wire_army_creation(self, phase_value: str) -> None:
        """Connect army-creation signals when that phase starts."""
        if self._match is None or self._match.army_creation is None:
            return
        # A fresh army-building session is starting: clear any previous lists.
        self.p1_army_list.clear()
        self.p2_army_list.clear()
        self._update_army_points()
        ac = self._match.army_creation
        ac.model_added.connect(self._on_army_model_added)
        ac.qr_progress.connect(self._on_army_qr_progress)
        ac.model_cancelled.connect(self._on_army_model_cancelled)
        ac.status_changed.connect(self._on_ingame_status)

    @staticmethod
    def _format_army_entry(
        model_name: str, codes: list, required: int
    ) -> str:
        """Two-line army item: name + status, then per-trooper QR values."""
        line1 = f"{model_name} — {len(codes)}/{required} QRs"
        if required <= 1:
            line2 = f"QR: {codes[0] if codes else '-'}"
        else:
            parts = []
            for i in range(required):
                letter = chr(ord("A") + i) if i < 26 else f"#{i + 1}"
                value = codes[i] if i < len(codes) else "-"
                parts.append(f"{letter}: {value}")
            line2 = ", ".join(parts)
        return f"{line1}\n{line2}"

    def _update_army_points(self) -> None:
        """Recompute and display each army's total point cost."""
        ac = self._match.army_creation if self._match is not None else None
        labels = (self.p1_points_label, self.p2_points_label)
        for idx, label in enumerate(labels):
            if ac is None:
                label.setText("Total: 0 pts")
                continue
            total = sum(getattr(card, "cost", 0) for card in ac.armies[idx])
            label.setText(f"Total: {total} pts")

    @QtCore.Slot(int, str, int)
    def _on_army_model_added(
        self, player_index: int, model_name: str, required_qr: int
    ) -> None:
        target = self.p1_army_list if player_index == 0 else self.p2_army_list
        item = QtWidgets.QListWidgetItem(
            self._format_army_entry(model_name, [], required_qr)
        )
        item.setData(QtCore.Qt.UserRole, (model_name, required_qr))
        target.addItem(item)
        target.scrollToItem(item)
        self._update_army_points()

    @QtCore.Slot(int, list, int)
    def _on_army_qr_progress(
        self, player_index: int, codes: list, required: int
    ) -> None:
        target = self.p1_army_list if player_index == 0 else self.p2_army_list
        item = target.item(target.count() - 1)
        if item is None:
            return
        data = item.data(QtCore.Qt.UserRole)
        model_name = data[0] if data else "?"
        item.setText(self._format_army_entry(model_name, list(codes), required))

    @QtCore.Slot(int)
    def _on_army_model_cancelled(self, player_index: int) -> None:
        target = self.p1_army_list if player_index == 0 else self.p2_army_list
        if target.count() > 0:
            target.takeItem(target.count() - 1)
        self._update_army_points()

    @QtCore.Slot(str)
    def _on_ingame_status(self, text: str) -> None:
        self.ingame_status_label.setText(text)

    # ------------------------------------------------------------------
    # Database combo helpers
    # ------------------------------------------------------------------

    def _populate_database_combo(self) -> None:
        """Scan the models_db folder and populate the database combo."""
        self.models_database_combo.blockSignals(True)
        current_path = (
            self._current_db.path if self._current_db else None
        )
        self.models_database_combo.clear()
        self.models_database_combo.addItem("-- Choose a database --", None)
        _MODELS_DB_DIR.mkdir(parents=True, exist_ok=True)
        restore_idx = 0
        for i, p in enumerate(sorted(_MODELS_DB_DIR.glob("*.json")), start=1):
            self.models_database_combo.addItem(p.stem, p)
            if current_path and p == current_path:
                restore_idx = i
        self.models_database_combo.blockSignals(False)
        self.models_database_combo.setCurrentIndex(restore_idx)

    def _set_db_controls_enabled(self, has_db: bool) -> None:
        self.save_db_btn.setEnabled(has_db)
        self.revert_db_btn.setEnabled(has_db)
        self.create_model_btn.setEnabled(has_db)

    def _update_db_title(self) -> None:
        """Mark the combo item with an asterisk when the database is dirty."""
        idx = self.models_database_combo.currentIndex()
        if idx <= 0 or self._current_db is None:
            return
        name = self._current_db.name
        label = f"*{name}" if self._current_db.is_dirty else name
        self.models_database_combo.setItemText(idx, label)

    def _check_unsaved_and_confirm(self) -> bool:
        """Return True if it is safe to proceed (no unsaved changes or user confirmed).

        Shows a warning dialog if the current database has unsaved changes.
        """
        if self._current_db is None or not self._current_db.is_dirty:
            return True
        reply = QtWidgets.QMessageBox.warning(
            self,
            "Unsaved Changes",
            f"The database '{self._current_db.name}' has unsaved changes.\n"
            "Do you want to discard them and continue?",
            QtWidgets.QMessageBox.Discard | QtWidgets.QMessageBox.Cancel,
            QtWidgets.QMessageBox.Cancel,
        )
        return reply == QtWidgets.QMessageBox.Discard

    # ------------------------------------------------------------------
    # Database slots
    # ------------------------------------------------------------------

    @QtCore.Slot(int)
    def _on_models_database_changed(self, index: int) -> None:
        """Load the selected database, warning if the current one is dirty."""
        path: Optional[Path] = self.models_database_combo.currentData()
        if path is None:
            self._current_db = None
            self.models_list.clear()
            self._set_db_controls_enabled(False)
            return
        if not self._check_unsaved_and_confirm():
            # Revert the combo to the previously loaded db
            self._populate_database_combo()
            return
        try:
            self._current_db = ModelDatabase.load(path)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(
                self, "Load Error", f"Could not load database:\n{exc}"
            )
            self._current_db = None
            self._populate_database_combo()
            return
        self._set_db_controls_enabled(True)
        self._refresh_models_list()

    @QtCore.Slot()
    def _on_new_database(self) -> None:
        """Create a new, empty database after confirming any unsaved changes."""
        if not self._check_unsaved_and_confirm():
            return
        name, ok = QtWidgets.QInputDialog.getText(
            self, "New Database", "Enter database name:"
        )
        if not ok or not name.strip():
            return
        name = name.strip()
        path = _MODELS_DB_DIR / f"{name}.json"
        if path.exists():
            QtWidgets.QMessageBox.warning(
                self,
                "Already Exists",
                f"A database named '{name}' already exists.",
            )
            return
        self._current_db = ModelDatabase.new(path)
        self.models_database_combo.blockSignals(True)
        self.models_database_combo.addItem(f"*{name}", path)
        self.models_database_combo.setCurrentIndex(self.models_database_combo.count() - 1)
        self.models_database_combo.blockSignals(False)
        self._set_db_controls_enabled(True)
        self._refresh_models_list()

    @QtCore.Slot()
    def _on_save_database(self) -> None:
        """Save the current database to disk."""
        if self._current_db is None:
            return
        try:
            self._current_db.save()
        except Exception as exc:
            QtWidgets.QMessageBox.critical(
                self, "Save Error", f"Could not save database:\n{exc}"
            )
            return
        self._update_db_title()

    @QtCore.Slot()
    def _on_revert_database(self) -> None:
        """Revert the current database to its last saved state."""
        if self._current_db is None:
            return
        reply = QtWidgets.QMessageBox.question(
            self,
            "Revert",
            f"Discard all unsaved changes to '{self._current_db.name}'?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if reply != QtWidgets.QMessageBox.Yes:
            return
        try:
            self._current_db.revert()
        except Exception as exc:
            QtWidgets.QMessageBox.critical(
                self, "Revert Error", f"Could not revert database:\n{exc}"
            )
            return
        self._update_db_title()
        self._refresh_models_list()

    # ------------------------------------------------------------------
    # Model list management
    # ------------------------------------------------------------------

    @QtCore.Slot()
    def _on_models_selection_changed(self) -> None:
        selected = self.models_list.selectedItems()
        self.edit_model_btn.setEnabled(len(selected) == 1)
        self.delete_models_btn.setEnabled(len(selected) >= 1)

    @QtCore.Slot()
    def _refresh_models_list(self) -> None:
        """Re-filter and re-sort the models list from the current database."""
        self.models_list.clear()
        if self._current_db is None:
            return
        models = self._current_db.all_models()
        models = self._apply_search(models)
        models = self._apply_sort(models)
        for m in models:
            suffix = f", C={m.short_name}" if m.is_character and m.short_name else ""
            label = (
                f"[{m.faction.value}]  {m.name}"
                f"  ({m.basic_type.value}, {m.cost} pts{suffix})"
            )
            item = QtWidgets.QListWidgetItem(label)
            item.setData(QtCore.Qt.UserRole, m.name)
            self.models_list.addItem(item)
        self._on_models_selection_changed()

    def _apply_search(
        self, models: list[ModelStatCard]
    ) -> list[ModelStatCard]:
        if self.hide_troopers_cb.isChecked():
            models = [m for m in models if m.basic_type != BasicType.TROOPER]
        query = self.search_edit.text().strip()
        if not query:
            return models
        words = query.lower().split()
        use_and = self.search_mode_combo.currentText() == "And"

        def searchable(m: ModelStatCard) -> str:
            parts = [
                m.name,
                m.short_name,
                m.faction.value,
                *[a.value for a in m.armies],
                *[k.value for k in m.keywords],
                *[f"{w.location.value}" for w in m.melee_weapons + m.range_weapons],
            ]
            return " ".join(parts).lower()

        def matches(m: ModelStatCard) -> bool:
            text = searchable(m)
            hits = (w in text for w in words)
            return all(hits) if use_and else any(hits)

        return [m for m in models if matches(m)]

    def _apply_sort(self, models: list[ModelStatCard]) -> list[ModelStatCard]:
        key_fns = [
            combo.currentData()
            for combo in self.sort_combos
            if combo.currentData() is not None
        ]
        if not key_fns:
            return models
        return sorted(models, key=lambda m: tuple(fn(m) for fn in key_fns))

    # ------------------------------------------------------------------
    # Model CRUD slots
    # ------------------------------------------------------------------

    @QtCore.Slot()
    def _on_create_model(self) -> None:
        if self._current_db is None:
            return
        dlg = ModelEditorDialog(card=None, event_manager=self._event_manager, db=self._current_db, parent=self)
        dlg.exec()
        card = dlg.result_card
        if card is None:
            return
        if self._current_db.get_model(card.name):
            reply = QtWidgets.QMessageBox.question(
                self,
                "Duplicate Name",
                f"A model named '{card.name}' already exists. Overwrite?",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                QtWidgets.QMessageBox.No,
            )
            if reply != QtWidgets.QMessageBox.Yes:
                return
        self._current_db.add_model(card)
        self._update_db_title()
        self._refresh_models_list()

    @QtCore.Slot()
    def _on_edit_model(self) -> None:
        if self._current_db is None:
            return
        items = self.models_list.selectedItems()
        if len(items) != 1:
            return
        original_name: str = items[0].data(QtCore.Qt.UserRole)
        card = self._current_db.get_model(original_name)
        if card is None:
            return
        dlg = ModelEditorDialog(card=card, event_manager=self._event_manager, db=self._current_db, parent=self)
        dlg.exec()
        if dlg.result_card:
            self._current_db.update_model(original_name, dlg.result_card)
            self._update_db_title()
            self._refresh_models_list()

    @QtCore.Slot()
    def _on_delete_models(self) -> None:
        if self._current_db is None:
            return
        names = [
            it.data(QtCore.Qt.UserRole) for it in self.models_list.selectedItems()
        ]
        if not names:
            return
        reply = QtWidgets.QMessageBox.question(
            self,
            "Delete Models",
            f"Delete {len(names)} model(s)? This cannot be undone.",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if reply != QtWidgets.QMessageBox.Yes:
            return
        self._current_db.remove_models(names)
        self._update_db_title()
        self._refresh_models_list()


class Game(GameBase):
    """Warmachine game - TTGA port for the tabletop miniatures wargame.

    Provides augmented reality overlays for Warmachine matches using camera
    and projector calibration on the physical play area.
    """

    def __init__(self, core: MainCore) -> None:
        """Initialize the Warmachine game.

        Args:
            core: MainCore instance.
        """
        super().__init__(core)

        # Load configuration from YAML (game.yaml is one level up from python/)
        config_path = Path(__file__).parent.parent / "game.yaml"
        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)

        # Parse zone requirements
        self.zone_requirements = []
        for zone_config in self.config.get('zones', []):
            req = ZoneRequirement(
                internal_name=zone_config['internal_name'],
                display_name=zone_config['display_name'],
                requires_camera=zone_config.get('requires_camera', False),
                requires_projector=zone_config.get('requires_projector', False),
                units=zone_config.get('units')
            )
            self.zone_requirements.append(req)

        self.event_manager = GameEventManager()
        self.dialog: Optional[WarmachineDialog] = None
        self.is_running = False

        # Overlay images for visualization (zone_name -> BGRA image)
        self.camera_overlays: dict[str, np.ndarray] = {}
        self.projector_overlays: dict[str, np.ndarray] = {}
        self.zone_mapping: dict[str, str] = {}

        # QR detectors (internal_name -> QRDetector) and their signal
        # connections, kept for clean disconnection on stop.
        self.qr_detectors: dict[str, QRDetector] = {}
        self.qr_detector_connections: dict[str, Callable] = {}

    def get_metadata(self) -> dict[str, str]:
        """Get game metadata from YAML configuration.

        Returns:
            Dictionary with game information.
        """
        return {
            'name': self.config.get('name', 'Warmachine'),
            'version': self.config.get('version', '1.0.0'),
            'author': self.config.get('author', 'Unknown'),
            'description': self.config.get('description', '')
        }

    def on_speech_command(self, text: str) -> None:
        """Route recognised speech to the event manager."""
        self.event_manager.route_speech(text)

    def on_load(self) -> None:
        """Called when the game is loaded."""
        print("[Warmachine] Game loaded")

    def on_unload(self) -> None:
        """Called when the game is unloaded."""
        if self.is_running:
            self.stop_game()

        if self.dialog:
            self.dialog.close()
            self.dialog = None

        print("[Warmachine] Game unloaded")

    def show_dialog(self, parent=None) -> None:
        """Show the Warmachine configuration dialog.

        Args:
            parent: Parent widget for the dialog.
        """
        if self.dialog is None:
            self.dialog = WarmachineDialog(
                self.core,
                self.config.get('name', 'Warmachine'),
                self.zone_requirements,
                self.config.get('settings', {}),
                self,
                parent,
                event_manager=self.event_manager,
            )

        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()

    def start_game(self, zone_mapping: dict[str, str]) -> bool:
        """Start the game with validated zones.

        Args:
            zone_mapping: Dictionary mapping internal zone names to actual zone names.

        Returns:
            True if game started successfully, False otherwise.
        """
        if self.is_running:
            print("[Warmachine] Game is already running")
            return False

        print("[Warmachine] Starting game...")
        self.zone_mapping = zone_mapping.copy()

        for internal_name, zone_name in zone_mapping.items():
            if zone_name:
                zone = self.core.zone_manager.get_zone(zone_name)
                if zone:
                    width_px = int(zone.width * zone.resolution)
                    height_px = int(zone.height * zone.resolution)

                    if zone.camera_mapping and zone.camera_mapping.enabled:
                        self.camera_overlays[zone_name] = np.zeros((height_px, width_px, 4), dtype=np.uint8)
                        print(f"[Warmachine] Created camera overlay for zone '{zone_name}' ({width_px}x{height_px})")

                    if zone.projector_mapping and zone.projector_mapping.enabled:
                        self.projector_overlays[zone_name] = np.zeros((height_px, width_px, 4), dtype=np.uint8)
                        print(f"[Warmachine] Created projector overlay for zone '{zone_name}' ({width_px}x{height_px})")

        # Create QR detectors for zones flagged with enable_qr_detector and
        # route their detections through the shared event manager.
        for zone_config in self.config.get('zones', []):
            if not zone_config.get('enable_qr_detector', False):
                continue
            internal_name = zone_config['internal_name']
            zone_name = zone_mapping.get(internal_name)
            if not zone_name:
                continue
            zone = self.core.zone_manager.get_zone(zone_name)
            if zone is None:
                continue
            detector = QRDetector(
                zone, self.core.camera_manager, self.core.qr_code_refresh_rate
            )
            connection = (
                lambda dets, zn=zone_name:
                self.event_manager.route_detection(dets, zn)
            )  # noqa: E731
            detector.detections_updated.connect(connection)
            detector.start()
            self.qr_detectors[internal_name] = detector
            self.qr_detector_connections[internal_name] = connection
            print(
                f"[Warmachine] Started QR detector for zone '{zone_name}' "
                f"at {self.core.qr_code_refresh_rate} Hz"
            )

        self.is_running = True
        print("[Warmachine] Game started successfully")
        return True

    def stop_game(self) -> None:
        """Stop the game and clean up resources."""
        if not self.is_running:
            return

        print("[Warmachine] Stopping game...")

        # Stop and disconnect QR detectors.
        for internal_name, detector in self.qr_detectors.items():
            detector.stop()
            connection = self.qr_detector_connections.get(internal_name)
            if connection is not None:
                try:
                    detector.detections_updated.disconnect(connection)
                except (RuntimeError, TypeError):
                    pass
        self.qr_detectors.clear()
        self.qr_detector_connections.clear()

        self.camera_overlays.clear()
        self.projector_overlays.clear()
        self.zone_mapping.clear()

        self.is_running = False
        print("[Warmachine] Game stopped")

    def get_camera_overlay(self, zone_name: str) -> Optional[np.ndarray]:
        """Get the camera overlay image for a specific zone.

        Args:
            zone_name: Name of the zone to get overlay for.

        Returns:
            numpy.ndarray with shape (height, width, 4) in BGRA format,
            or None if no overlay for this zone.
        """
        return self.camera_overlays.get(zone_name)

    def get_projector_overlay(self, zone_name: str) -> Optional[np.ndarray]:
        """Get the projector overlay image for a specific zone.

        Args:
            zone_name: Name of the zone to get overlay for.

        Returns:
            numpy.ndarray with shape (height, width, 4) in BGRA format,
            or None if no overlay for this zone.
        """
        return self.projector_overlays.get(zone_name)
