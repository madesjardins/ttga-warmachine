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

"""Model editor dialog for the Warmachine game database manager."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional, Union

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

if TYPE_CHECKING:
    from .event_manager import GameEventManager
    from .model_database import ModelDatabase

from .damage_system import (
    GRID_SIZE,
    BoxDamageSystem,
    DamageKey,
    DamageSystemType,
    GridDamageSystem,
    SpiralAspect,
    SpiralDamageSystem,
    WebDamageSystem,
)
from .model_stat_card import (
    BASE_SIZES,
    BasicType,
    Faction,
    ModelAdvantage,
    ModelResistance,
    ModelStatCard,
    ModelStatistics,
)
from .weapon import (
    ContinuousEffect,
    CriticalEffect,
    DamageType,
    Hardpoint,
    MeleeWeapon,
    RangeWeapon,
    RangeWeaponType,
    WeaponLocation,
    WeaponQuality,
)


# ---------------------------------------------------------------------------
# _FlowLayout – wrapping flow layout helper
# ---------------------------------------------------------------------------


class _FlowLayout(QtWidgets.QLayout):
    """Left-to-right wrapping layout (like CSS flex-wrap)."""

    def __init__(self, parent=None, spacing: int = 4) -> None:
        super().__init__(parent)
        self.setSpacing(spacing)
        self._items: list = []

    def addItem(self, item) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientations(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QtCore.QRect(0, 0, width, 0), test=True)

    def setGeometry(self, rect: QtCore.QRect) -> None:
        super().setGeometry(rect)
        self._do_layout(rect, test=False)

    def sizeHint(self) -> QtCore.QSize:
        return self.minimumSize()

    def minimumSize(self) -> QtCore.QSize:
        size = QtCore.QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        return size + QtCore.QSize(m.left() + m.right(), m.top() + m.bottom())

    def _do_layout(self, rect: QtCore.QRect, test: bool) -> int:
        m = self.contentsMargins()
        sp = max(self.spacing(), 4)
        x = rect.x() + m.left()
        y = rect.y() + m.top()
        right = rect.right() - m.right()
        line_h = 0
        for item in self._items:
            sh = item.sizeHint()
            if x + sh.width() > right and line_h > 0:
                x = rect.x() + m.left()
                y += line_h + sp
                line_h = 0
            if not test:
                item.setGeometry(QtCore.QRect(QtCore.QPoint(x, y), sh))
            x += sh.width() + sp
            line_h = max(line_h, sh.height())
        return y + line_h - rect.y() + m.bottom()


# ---------------------------------------------------------------------------
# TagInputWidget – chip-style enum selector
# ---------------------------------------------------------------------------


class TagInputWidget(QtWidgets.QFrame):
    """Type-to-filter autocomplete widget that stores selections as chips.

    *  Type in the search box → dropdown shows matching unselected values.
    *  Click a suggestion → value added as a coloured chip.
    *  Click the × on a chip → value removed.
    """

    changed = QtCore.Signal()

    def __init__(self, enum_cls=None, *, str_values=None, on_add=None, initial=None, parent=None) -> None:
        super().__init__(parent)
        if enum_cls is not None:
            self._all_values: list[str] = [e.value for e in enum_cls]
        else:
            self._all_values = str_values if str_values is not None else []
        self._on_add = on_add
        self._selected: list[str] = []
        self._chip_widgets: dict[str, QtWidgets.QFrame] = {}
        self._setup_ui()
        for v in (initial or []):
            label = v.value if hasattr(v, 'value') else str(v)
            self._add_chip(label)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def selected_values(self) -> list[str]:
        return list(self._selected)

    def set_values(self, values) -> None:
        self.clear()
        for v in values:
            label = v.value if hasattr(v, 'value') else str(v)
            self._add_chip(label)

    def clear(self) -> None:
        for i in range(self._chips_layout.count() - 1, -1, -1):
            item = self._chips_layout.takeAt(i)
            if item and item.widget():
                item.widget().deleteLater()
        self._chip_widgets.clear()
        self._selected.clear()
        self._chips_layout.invalidate()
        self._chips_container.adjustSize()

    # ------------------------------------------------------------------
    # UI setup
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        self.setFrameShape(QtWidgets.QFrame.StyledPanel)
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(4)

        self._chips_container = QtWidgets.QWidget()
        self._chips_container.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Minimum
        )
        self._chips_layout = _FlowLayout(self._chips_container, spacing=4)

        chips_scroll = QtWidgets.QScrollArea()
        chips_scroll.setWidget(self._chips_container)
        chips_scroll.setWidgetResizable(True)
        chips_scroll.setFixedHeight(66)
        chips_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        chips_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        chips_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        root.addWidget(chips_scroll)

        self._search = QtWidgets.QLineEdit()
        self._search.setPlaceholderText("Type to filter…")
        self._search.textChanged.connect(self._on_text_changed)
        root.addWidget(self._search)

        self._popup = QtWidgets.QFrame(
            self, Qt.Tool | Qt.FramelessWindowHint
        )
        self._popup.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self._popup.setFrameShadow(QtWidgets.QFrame.Plain)
        self._popup.setLineWidth(1)
        pop_layout = QtWidgets.QVBoxLayout(self._popup)
        pop_layout.setContentsMargins(0, 0, 0, 0)
        self._dropdown = QtWidgets.QListWidget()
        self._dropdown.setFrameShape(QtWidgets.QFrame.NoFrame)
        self._dropdown.itemClicked.connect(self._on_suggestion_clicked)
        pop_layout.addWidget(self._dropdown)
        self._popup.hide()

        self._search.installEventFilter(self)
        self._dropdown.installEventFilter(self)

    # ------------------------------------------------------------------
    # Chips
    # ------------------------------------------------------------------

    def _add_chip(self, value) -> None:
        if value in self._selected:
            return
        self._selected.append(value)

        chip = QtWidgets.QFrame()
        chip.setFrameShape(QtWidgets.QFrame.StyledPanel)
        chip.setStyleSheet(
            "QFrame { background: #2d6fa8; border-radius: 8px; border: none; }"
        )
        row = QtWidgets.QHBoxLayout(chip)
        row.setContentsMargins(6, 2, 3, 2)
        row.setSpacing(2)

        lbl = QtWidgets.QLabel(value)
        lbl.setStyleSheet(
            "color: white; font-size: 11px; background: transparent; border: none;"
        )
        row.addWidget(lbl)

        btn = QtWidgets.QToolButton()
        btn.setText("×")
        btn.setFixedSize(14, 14)
        btn.setStyleSheet(
            "QToolButton { color: white; border: none; background: transparent;"
            " font-weight: bold; font-size: 12px; }"
            "QToolButton:hover { color: #ffaaaa; }"
        )
        btn.clicked.connect(lambda _=False, v=value: self._remove_chip(v))
        row.addWidget(btn)

        self._chip_widgets[value] = chip
        self._chips_layout.addWidget(chip)
        self._chips_layout.invalidate()
        self._chips_container.adjustSize()
        self.changed.emit()

    def _remove_chip(self, value) -> None:
        chip = self._chip_widgets.pop(value, None)
        if chip is None:
            return
        if value in self._selected:
            self._selected.remove(value)
        for i in range(self._chips_layout.count()):
            item = self._chips_layout.itemAt(i)
            if item and item.widget() is chip:
                self._chips_layout.takeAt(i)
                break
        chip.deleteLater()
        self._chips_layout.invalidate()
        self._chips_container.adjustSize()
        self.changed.emit()
        self._on_text_changed(self._search.text())

    # ------------------------------------------------------------------
    # Dropdown
    # ------------------------------------------------------------------

    def eventFilter(self, obj, event) -> bool:
        if obj is self._search:
            if event.type() == QtCore.QEvent.FocusOut:
                QtCore.QTimer.singleShot(120, self._maybe_hide_popup)
            elif event.type() == QtCore.QEvent.KeyPress:
                key = event.key()
                if key == Qt.Key_Escape:
                    self._search.clear()
                    return True
                if key == Qt.Key_Down and self._popup.isVisible():
                    self._dropdown.setFocus()
                    if self._dropdown.count():
                        self._dropdown.setCurrentRow(0)
                    return True
        if obj is self._dropdown:
            if event.type() == QtCore.QEvent.KeyPress:
                key = event.key()
                if key in (Qt.Key_Return, Qt.Key_Enter):
                    cur = self._dropdown.currentItem()
                    if cur:
                        self._on_suggestion_clicked(cur)
                    return True
                if key == Qt.Key_Escape:
                    self._search.clear()
                    self._search.setFocus()
                    return True
        return super().eventFilter(obj, event)

    def _maybe_hide_popup(self) -> None:
        fw = QtWidgets.QApplication.focusWidget()
        if fw is not self._search and fw is not self._dropdown:
            self._popup.hide()

    def hideEvent(self, event) -> None:
        self._popup.hide()
        super().hideEvent(event)

    @QtCore.Slot(str)
    def _on_text_changed(self, text: str) -> None:
        self._dropdown.clear()
        query = text.strip()
        if not query:
            self._popup.hide()
            return
        q_lower = query.lower()
        matches = [
            v for v in self._all_values
            if q_lower in v.lower() and v not in self._selected
        ]
        for v in matches:
            item = QtWidgets.QListWidgetItem(v)
            item.setData(Qt.UserRole, v)
            self._dropdown.addItem(item)
        if self._on_add and not any(v.lower() == q_lower for v in self._all_values):
            add_item = QtWidgets.QListWidgetItem(f'+ Add "{query}"')
            add_item.setData(Qt.UserRole, None)
            add_item.setData(Qt.UserRole + 1, query)
            add_item.setForeground(QtGui.QColor("#4aaa77"))
            self._dropdown.addItem(add_item)
        visible = self._dropdown.count()
        if visible:
            row_h = self._dropdown.sizeHintForRow(0)
            popup_h = min(visible * row_h + 4, 160)
            pos = self._search.mapToGlobal(
                QtCore.QPoint(0, self._search.height())
            )
            self._popup.setFixedSize(self._search.width(), popup_h)
            self._popup.move(pos)
            self._popup.show()
            self._popup.raise_()
        else:
            self._popup.hide()

    @QtCore.Slot(QtWidgets.QListWidgetItem)
    def _on_suggestion_clicked(self, item: QtWidgets.QListWidgetItem) -> None:
        new_name = item.data(Qt.UserRole + 1)
        if new_name is not None:
            if self._on_add(new_name):
                self._add_chip(new_name)
        else:
            self._add_chip(item.data(Qt.UserRole))
        self._search.clear()
        self._popup.hide()
        self._search.setFocus()


# ---------------------------------------------------------------------------
# WeaponEditorDialog
# ---------------------------------------------------------------------------


class WeaponEditorDialog(QtWidgets.QDialog):
    """Dialog to create or edit a single melee or ranged weapon."""

    def __init__(
        self,
        weapon: Optional[Union[MeleeWeapon, RangeWeapon]] = None,
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._result: Optional[Union[MeleeWeapon, RangeWeapon]] = None
        self._setup_ui()
        if weapon is not None:
            self._load_weapon(weapon)
        else:
            self._on_type_changed()

    @property
    def result_weapon(self) -> Optional[Union[MeleeWeapon, RangeWeapon]]:
        """The weapon produced by the dialog, or ``None`` if cancelled."""
        return self._result

    @staticmethod
    def _make_checkbox_row(enum_cls) -> tuple[dict, QtWidgets.QWidget]:
        """Build a horizontal row of checkboxes for every member of *enum_cls*.

        Returns a ``(dict, widget)`` tuple where the dict maps each enum member
        to its :class:`QCheckBox`.
        """
        widget = QtWidgets.QWidget()
        h = QtWidgets.QHBoxLayout(widget)
        h.setContentsMargins(0, 0, 0, 0)
        cbs: dict = {}
        for member in enum_cls:
            cb = QtWidgets.QCheckBox(member.value)
            h.addWidget(cb)
            cbs[member] = cb
        h.addStretch()
        return cbs, widget

    def _setup_ui(self) -> None:
        self.setWindowTitle("Weapon Editor")
        self.setMinimumWidth(400)
        layout = QtWidgets.QVBoxLayout(self)
        self._form = QtWidgets.QFormLayout()

        self.weapon_name_edit = QtWidgets.QLineEdit()
        self._form.addRow("Name:", self.weapon_name_edit)

        self.type_combo = QtWidgets.QComboBox()
        self.type_combo.addItem("Melee", "melee")
        self.type_combo.addItem("Ranged", "range")
        self.type_combo.currentIndexChanged.connect(self._on_type_changed)
        self._form.addRow("Type:", self.type_combo)

        self.two_x_cb = QtWidgets.QCheckBox("Model carries two of this weapon (2x)")
        self._form.addRow("", self.two_x_cb)

        _loc_display = {WeaponLocation.S: "Superstructure"}
        self.location_combo = QtWidgets.QComboBox()
        for loc in WeaponLocation:
            self.location_combo.addItem(_loc_display.get(loc, loc.value), loc)
        self.location_combo.setCurrentIndex(
            self.location_combo.findData(WeaponLocation.ANY)
        )
        self._form.addRow("Location:", self.location_combo)

        self.rwtype_combo = QtWidgets.QComboBox()
        for rt in RangeWeaponType:
            self.rwtype_combo.addItem(rt.value, rt)
        self.rwtype_combo.currentIndexChanged.connect(self._on_ammo_type_changed)
        self._form.addRow("Ammunition Type:", self.rwtype_combo)

        self.range_spin = QtWidgets.QSpinBox()
        self.range_spin.setRange(0, 99)
        self._form.addRow("Range (RNG):", self.range_spin)

        rof_widget = QtWidgets.QWidget()
        rof_h = QtWidgets.QHBoxLayout(rof_widget)
        rof_h.setContentsMargins(0, 0, 0, 0)
        self.rof_dice_spin = QtWidgets.QSpinBox()
        self.rof_dice_spin.setRange(0, 9)
        self.rof_dice_spin.setFixedWidth(40)
        self.rof_flat_spin = QtWidgets.QSpinBox()
        self.rof_flat_spin.setRange(0, 99)
        self.rof_flat_spin.setFixedWidth(40)
        rof_h.addWidget(self.rof_dice_spin)
        rof_h.addWidget(QtWidgets.QLabel("D3 +"))
        rof_h.addWidget(self.rof_flat_spin)
        rof_h.addStretch()
        self._form.addRow("Rate of Fire (ROF):", rof_widget)
        self._rof_widget = rof_widget

        self.aoe_spin = QtWidgets.QSpinBox()
        self.aoe_spin.setRange(0, 10)
        self._form.addRow("Area of Effect (AOE):", self.aoe_spin)

        self.power_spin = QtWidgets.QSpinBox()
        self.power_spin.setRange(0, 99)
        self._form.addRow("Power (POW):", self.power_spin)

        self.blast_spin = QtWidgets.QSpinBox()
        self.blast_spin.setRange(0, 99)
        self._form.addRow("Blast Power:", self.blast_spin)

        self.qualities_tag = TagInputWidget(enum_cls=WeaponQuality)
        self._form.addRow("Qualities:", self.qualities_tag)

        self._cont_effect_cbs, cont_row = self._make_checkbox_row(ContinuousEffect)
        self._form.addRow("Continuous Effects:", cont_row)

        self._crit_effect_cbs, crit_row = self._make_checkbox_row(CriticalEffect)
        self._form.addRow("Critical Effects:", crit_row)

        self._damage_type_cbs, dmg_row = self._make_checkbox_row(DamageType)
        self._form.addRow("Damage Types:", dmg_row)

        layout.addLayout(self._form)

        btn_box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        btn_box.accepted.connect(self._on_accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    @QtCore.Slot()
    def _on_type_changed(self) -> None:
        is_range = self.type_combo.currentData() == "range"
        self._form.setRowVisible(self.rwtype_combo, is_range)
        self._form.setRowVisible(self._rof_widget, is_range)
        if not is_range:
            self._form.setRowVisible(self.aoe_spin, False)
            self._form.setRowVisible(self.blast_spin, False)
        else:
            self._on_ammo_type_changed()
        self.adjustSize()

    @QtCore.Slot()
    def _on_ammo_type_changed(self) -> None:
        is_aoe = self.rwtype_combo.currentData() == RangeWeaponType.AREA_OF_EFFECT
        self._form.setRowVisible(self.aoe_spin, is_aoe)
        self._form.setRowVisible(self.blast_spin, is_aoe)
        self.adjustSize()

    def _load_weapon(self, weapon: Union[MeleeWeapon, RangeWeapon]) -> None:
        self.weapon_name_edit.setText(weapon.name)
        self.two_x_cb.setChecked(weapon.two_x)
        if isinstance(weapon, RangeWeapon):
            self.type_combo.setCurrentIndex(1)
            self.rof_dice_spin.setValue(weapon.rof_dice)
            self.rof_flat_spin.setValue(weapon.rof_flat)
            idx = self.rwtype_combo.findData(weapon.range_weapon_type)
            if idx >= 0:
                self.rwtype_combo.setCurrentIndex(idx)
            self.aoe_spin.setValue(weapon.area_of_effect)
            self.blast_spin.setValue(weapon.blast_power)
        else:
            self.type_combo.setCurrentIndex(0)
        idx = self.location_combo.findData(weapon.location)
        if idx >= 0:
            self.location_combo.setCurrentIndex(idx)
        self.range_spin.setValue(weapon.range)
        self.power_spin.setValue(weapon.power)
        self.qualities_tag.set_values(weapon.weapon_qualities)
        for e, cb in self._cont_effect_cbs.items():
            cb.setChecked(e in weapon.continuous_effects)
        for e, cb in self._crit_effect_cbs.items():
            cb.setChecked(e in weapon.critical_effects)
        for t, cb in self._damage_type_cbs.items():
            cb.setChecked(t in weapon.damage_types)
        self._on_type_changed()

    @QtCore.Slot()
    def _on_accept(self) -> None:
        location = WeaponLocation(self.location_combo.currentData())
        rng = self.range_spin.value()
        power = self.power_spin.value()
        wname = self.weapon_name_edit.text().strip()
        two_x = self.two_x_cb.isChecked()
        qualities = [WeaponQuality(v) for v in self.qualities_tag.selected_values()]
        cont_effects = [e for e, cb in self._cont_effect_cbs.items() if cb.isChecked()]
        crit_effects = [e for e, cb in self._crit_effect_cbs.items() if cb.isChecked()]
        dmg_types = [t for t, cb in self._damage_type_cbs.items() if cb.isChecked()]
        if self.type_combo.currentData() == "range":
            self._result = RangeWeapon(
                location=location,
                range=rng,
                power=power,
                name=wname,
                two_x=two_x,
                rof_dice=self.rof_dice_spin.value(),
                rof_flat=self.rof_flat_spin.value(),
                range_weapon_type=RangeWeaponType(self.rwtype_combo.currentData()),
                area_of_effect=self.aoe_spin.value(),
                blast_power=self.blast_spin.value(),
                weapon_qualities=qualities,
                continuous_effects=cont_effects,
                critical_effects=crit_effects,
                damage_types=dmg_types,
            )
        else:
            self._result = MeleeWeapon(
                location=location,
                range=rng,
                power=power,
                name=wname,
                two_x=two_x,
                weapon_qualities=qualities,
                continuous_effects=cont_effects,
                critical_effects=crit_effects,
                damage_types=dmg_types,
            )
        self.accept()


# ---------------------------------------------------------------------------
# HardpointGroupEditorDialog
# ---------------------------------------------------------------------------


class HardpointGroupEditorDialog(QtWidgets.QDialog):
    """Dialog to create or edit a single hardpoint group (list of Hardpoint)."""

    def __init__(
        self,
        group: Optional[list[Hardpoint]] = None,
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._hardpoints: list[Hardpoint] = list(group) if group else []
        self._setup_ui()
        self._refresh_list()

    @property
    def result_group(self) -> list[Hardpoint]:
        """The edited hardpoint group."""
        return list(self._hardpoints)

    def _setup_ui(self) -> None:
        self.setWindowTitle("Hardpoint Group Editor")
        self.setMinimumWidth(320)
        layout = QtWidgets.QVBoxLayout(self)

        self.hp_list = QtWidgets.QListWidget()
        self.hp_list.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        layout.addWidget(self.hp_list)

        form_group = QtWidgets.QGroupBox("New Hardpoint")
        form = QtWidgets.QFormLayout(form_group)
        self.hp_name_edit = QtWidgets.QLineEdit()
        form.addRow("Name:", self.hp_name_edit)
        self.hp_loc_combo = QtWidgets.QComboBox()
        for loc in WeaponLocation:
            self.hp_loc_combo.addItem(loc.value, loc)
        form.addRow("Location:", self.hp_loc_combo)
        add_btn = QtWidgets.QPushButton("Add to Group")
        add_btn.clicked.connect(self._on_add)
        form.addRow(add_btn)
        layout.addWidget(form_group)

        remove_btn = QtWidgets.QPushButton("Remove Selected")
        remove_btn.clicked.connect(self._on_remove)
        layout.addWidget(remove_btn)

        btn_box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def _refresh_list(self) -> None:
        self.hp_list.clear()
        for hp in self._hardpoints:
            self.hp_list.addItem(f"{hp.name}  [{hp.location.value}]")

    @QtCore.Slot()
    def _on_add(self) -> None:
        name = self.hp_name_edit.text().strip()
        if not name:
            return
        self._hardpoints.append(
            Hardpoint(name=name, location=self.hp_loc_combo.currentData())
        )
        self.hp_name_edit.clear()
        self._refresh_list()

    @QtCore.Slot()
    def _on_remove(self) -> None:
        rows = sorted(
            {self.hp_list.row(i) for i in self.hp_list.selectedItems()}, reverse=True
        )
        for row in rows:
            del self._hardpoints[row]
        self._refresh_list()


# ---------------------------------------------------------------------------
# DamageGridEditorDialog
# ---------------------------------------------------------------------------


class DamageGridEditorDialog(QtWidgets.QDialog):
    """Dialog showing one or two 6\u00d76 grids of QComboBoxes for DamageKey values."""

    def __init__(
        self,
        left_grid: Optional[list[list[DamageKey]]] = None,
        right_grid: Optional[list[list[DamageKey]]] = None,
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Damage Grid Editor")
        self._left_combos: list[list[QtWidgets.QComboBox]] = []
        self._right_combos: list[list[QtWidgets.QComboBox]] = []
        self._setup_ui()
        self._load(left_grid, right_grid)

    @property
    def left_grid(self) -> list[list[DamageKey]]:
        """Current state of the left grid."""
        return self._read_combos(self._left_combos)

    @property
    def right_grid(self) -> Optional[list[list[DamageKey]]]:
        """Current state of the right grid, or ``None`` if not enabled."""
        if self.has_right_cb.isChecked():
            return self._read_combos(self._right_combos)
        return None

    def _setup_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)

        self.has_right_cb = QtWidgets.QCheckBox("Has left and right damage grids")
        self.has_right_cb.toggled.connect(self._on_has_right_toggled)
        layout.addWidget(self.has_right_cb)

        grids_layout = QtWidgets.QHBoxLayout()

        self._left_grp = QtWidgets.QGroupBox("Grid")
        left_inner = QtWidgets.QGridLayout(self._left_grp)
        left_inner.setSpacing(2)
        self._left_combos = self._fill_grid(left_inner)
        grids_layout.addWidget(self._left_grp)

        self._right_grp = QtWidgets.QGroupBox("Right Grid")
        right_inner = QtWidgets.QGridLayout(self._right_grp)
        right_inner.setSpacing(2)
        self._right_combos = self._fill_grid(right_inner)
        self._right_grp.setVisible(False)
        grids_layout.addWidget(self._right_grp)

        layout.addLayout(grids_layout)

        btn_box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

        layout.setSizeConstraint(QtWidgets.QLayout.SetFixedSize)
        self.setWindowFlags(self.windowFlags() & ~QtCore.Qt.WindowMaximizeButtonHint)

    def _fill_grid(
        self, grid_layout: QtWidgets.QGridLayout
    ) -> list[list[QtWidgets.QComboBox]]:
        """Populate *grid_layout* with GRID_SIZE\u00d7GRID_SIZE QComboBoxes."""
        combos: list[list[QtWidgets.QComboBox]] = []
        for r in range(GRID_SIZE):
            row_combos: list[QtWidgets.QComboBox] = []
            for c in range(GRID_SIZE):
                combo = QtWidgets.QComboBox()
                combo.setFixedWidth(52)
                for dk in DamageKey:
                    label = "\u25a1" if dk == DamageKey.BLANK else dk.value
                    combo.addItem(label, dk)
                grid_layout.addWidget(combo, r, c)
                row_combos.append(combo)
            combos.append(row_combos)
        return combos

    @QtCore.Slot(bool)
    def _on_has_right_toggled(self, checked: bool) -> None:
        self._left_grp.setTitle("Left Grid" if checked else "Grid")
        self._right_grp.setVisible(checked)
        self.adjustSize()

    def _load(
        self,
        left_grid: Optional[list[list[DamageKey]]],
        right_grid: Optional[list[list[DamageKey]]],
    ) -> None:
        if left_grid is not None:
            self._load_combos(self._left_combos, left_grid)
        if right_grid is not None:
            self.has_right_cb.setChecked(True)
            self._load_combos(self._right_combos, right_grid)

    @staticmethod
    def _load_combos(
        combos: list[list[QtWidgets.QComboBox]],
        grid: list[list[DamageKey]],
    ) -> None:
        for r in range(min(GRID_SIZE, len(grid))):
            for c in range(min(GRID_SIZE, len(grid[r]))):
                idx = combos[r][c].findData(grid[r][c])
                if idx >= 0:
                    combos[r][c].setCurrentIndex(idx)

    @staticmethod
    def _read_combos(
        combos: list[list[QtWidgets.QComboBox]],
    ) -> list[list[DamageKey]]:
        return [
            [combos[r][c].currentData() for c in range(GRID_SIZE)]
            for r in range(GRID_SIZE)
        ]


# ---------------------------------------------------------------------------
# ModelEditorDialog
# ---------------------------------------------------------------------------


class ModelEditorDialog(QtWidgets.QDialog):
    """Full model editor dialog for creating or editing a ModelStatCard.

    When *card* is ``None`` the dialog opens in create mode with default
    values.  When *card* is provided the dialog opens in edit mode and
    pre-populates all fields from the card.

    The result is exposed via :attr:`result_card` after :meth:`exec` returns
    :attr:`~QDialog.Accepted`.
    """

    def __init__(
        self,
        card: Optional[ModelStatCard] = None,
        event_manager: Optional[GameEventManager] = None,
        db: Optional[ModelDatabase] = None,
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._original_card = card
        self._result_card: Optional[ModelStatCard] = None
        self._event_manager = event_manager
        self._db = db
        self._recording_vocal = False
        self._weapons: list[Union[MeleeWeapon, RangeWeapon]] = []
        self._hardpoint_groups: list[list[Hardpoint]] = []
        self._left_grid_data: list[list[DamageKey]] = [
            [DamageKey.BLANK] * GRID_SIZE for _ in range(GRID_SIZE)
        ]
        self._right_grid_data: Optional[list[list[DamageKey]]] = None
        self._dirty = False
        self._setup_ui()
        if card is not None:
            self._load_card(card)
        else:
            self._reset_to_defaults()
        self._connect_dirty_signals()

    @property
    def result_card(self) -> Optional[ModelStatCard]:
        """The :class:`ModelStatCard` produced by the dialog, or ``None``."""
        return self._result_card

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        self.setWindowTitle("Model Editor")
        self.setMinimumSize(820, 750)
        root = QtWidgets.QVBoxLayout(self)

        root.addWidget(self._create_top_section())
        root.addWidget(self._create_assoc_section())
        root.addWidget(self._create_stats_section())
        root.addWidget(self._create_tabs())
        self.basic_type_combo.currentIndexChanged.connect(self._update_stat_visibility)

        btn_bar = QtWidgets.QHBoxLayout()
        save_btn = QtWidgets.QPushButton("Save")
        save_btn.clicked.connect(self._on_save)
        revert_btn = QtWidgets.QPushButton("Revert")
        revert_btn.clicked.connect(self._on_revert)
        close_btn = QtWidgets.QPushButton("Close")
        close_btn.clicked.connect(self._on_close)
        btn_bar.addWidget(save_btn)
        btn_bar.addWidget(revert_btn)
        btn_bar.addWidget(close_btn)
        root.addLayout(btn_bar)
        self._update_stat_visibility()

    def _update_stat_visibility(self) -> None:
        bt_data = self.basic_type_combo.currentData()
        bt = BasicType(bt_data) if bt_data is not None else None
        caster_types = {BasicType.WARCASTER, BasicType.WARLOCK, BasicType.INFERNAL_MASTER}
        for stat in ("ARC", "CTRL"):
            self._stat_containers[stat].setVisible(bt in caster_types)
        for stat in ("FURY", "THR"):
            self._stat_containers[stat].setVisible(bt == BasicType.WARBEAST)

    def _create_top_section(self) -> QtWidgets.QWidget:
        widget = QtWidgets.QWidget()
        grid = QtWidgets.QGridLayout(widget)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 2)

        # --- Left column: basic fields ---
        self.name_edit = QtWidgets.QLineEdit()
        self.short_name_edit = QtWidgets.QLineEdit()

        self.faction_combo = QtWidgets.QComboBox()
        for f in sorted(Faction, key=lambda f: f.value):
            self.faction_combo.addItem(f.value, f)

        self.basic_type_combo = QtWidgets.QComboBox()
        for bt in BasicType:
            self.basic_type_combo.addItem(bt.value, bt)

        self.base_size_combo = QtWidgets.QComboBox()
        for bs in BASE_SIZES:
            self.base_size_combo.addItem(str(bs), bs)

        self.cost_spin = QtWidgets.QSpinBox()
        self.cost_spin.setRange(0, 999)

        self.is_char_cb = QtWidgets.QCheckBox()

        self.fa_spin = QtWidgets.QSpinBox()
        self.fa_spin.setRange(-1, 99)
        self.fa_spin.setValue(-1)
        self.fa_spin.setSpecialValueText("∞")

        rows = [
            ("Name:", self.name_edit),
            ("Short Name:", self.short_name_edit),
            ("Faction:", self.faction_combo),
            ("Basic Type:", self.basic_type_combo),
            ("Base Size:", self.base_size_combo),
            ("Cost:", self.cost_spin),
            ("Is Character:", self.is_char_cb),
            ("FA:", self.fa_spin),
        ]
        for row_idx, (label, ctrl) in enumerate(rows):
            grid.addWidget(QtWidgets.QLabel(label), row_idx, 0)
            grid.addWidget(ctrl, row_idx, 1)

        # --- Right column: vocal names ---
        grid.addWidget(QtWidgets.QLabel("Vocal Names:"), 0, 2)
        self.vocal_list = QtWidgets.QListWidget()
        self.vocal_list.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        grid.addWidget(self.vocal_list, 0, 3, 6, 1)

        self._vocal_dup_label = QtWidgets.QLabel()
        self._vocal_dup_label.setStyleSheet("color: crimson; font-style: italic;")
        grid.addWidget(self._vocal_dup_label, 6, 3)

        vn_btns = QtWidgets.QVBoxLayout()
        self._record_vn_btn = QtWidgets.QPushButton("Record")
        self._record_vn_btn.clicked.connect(self._on_record_vocal_name)
        if self._event_manager is None:
            self._record_vn_btn.setToolTip("Speech recognition unavailable")
            self._record_vn_btn.setEnabled(False)
        remove_vn = QtWidgets.QPushButton("Remove")
        remove_vn.clicked.connect(self._on_remove_vocal_name)
        vn_btns.addWidget(self._record_vn_btn)
        vn_btns.addWidget(remove_vn)
        vn_btns.addStretch()
        grid.addLayout(vn_btns, 0, 4, 6, 1)

        return widget

    def _create_assoc_section(self) -> QtWidgets.QWidget:
        """Armies, Keywords, Advantages and Resistances tag-input selectors."""
        widget = QtWidgets.QWidget()
        h = QtWidgets.QHBoxLayout(widget)

        def make_tag(label: str, **kwargs) -> TagInputWidget:
            grp = QtWidgets.QGroupBox(label)
            v = QtWidgets.QVBoxLayout(grp)
            tag = TagInputWidget(**kwargs)
            v.addWidget(tag)
            h.addWidget(grp)
            return tag

        if self._db is not None:
            self.armies_tag = make_tag(
                "Armies", str_values=self._db.armies, on_add=self._db.add_army
            )
            self.keywords_tag = make_tag(
                "Keywords", str_values=self._db.keywords, on_add=self._db.add_keyword
            )
        else:
            self.armies_tag = make_tag("Armies", str_values=[])
            self.keywords_tag = make_tag("Keywords", str_values=[])
        self.advantages_tag = make_tag("Advantages", enum_cls=ModelAdvantage)
        self.resistances_tag = make_tag("Resistances", enum_cls=ModelResistance)
        return widget

    def _create_stats_section(self) -> QtWidgets.QWidget:
        widget = QtWidgets.QWidget()
        h = QtWidgets.QHBoxLayout(widget)
        stat_names = ["SPD", "AAT", "MAT", "RAT", "DEF", "ARM", "ARC", "CTRL", "FURY", "THR"]
        self._stat_spins: dict[str, QtWidgets.QSpinBox] = {}
        self._stat_containers: dict[str, QtWidgets.QWidget] = {}
        for name in stat_names:
            container = QtWidgets.QWidget()
            v = QtWidgets.QVBoxLayout(container)
            v.setContentsMargins(0, 0, 0, 0)
            lbl = QtWidgets.QLabel(name)
            lbl.setAlignment(Qt.AlignCenter)
            spin = QtWidgets.QSpinBox()
            spin.setRange(-1, 99)
            spin.setValue(-1)
            spin.setSpecialValueText("-")
            spin.setFixedWidth(52)
            v.addWidget(lbl)
            v.addWidget(spin)
            h.addWidget(container)
            self._stat_spins[name] = spin
            self._stat_containers[name] = container
        h.addStretch()
        return widget

    def _create_tabs(self) -> QtWidgets.QTabWidget:
        tabs = QtWidgets.QTabWidget()
        tabs.addTab(self._create_special_rules_tab(), "Special Rules")
        tabs.addTab(self._create_health_tab(), "Health")
        tabs.addTab(self._create_spells_tab(), "Spells / Animus")
        tabs.addTab(self._create_weapons_tab(), "Weapons")
        tabs.addTab(self._create_hardpoints_tab(), "Hardpoints")
        return tabs

    # -- Tab: Special Rules --

    def _create_special_rules_tab(self) -> QtWidgets.QWidget:
        widget = QtWidgets.QWidget()
        h = QtWidgets.QHBoxLayout(widget)
        self.special_rules_list, pnl1 = self._make_string_list_editor("Special Rules")
        self.special_actions_list, pnl2 = self._make_string_list_editor("Special Actions")
        self.special_attacks_list, pnl3 = self._make_string_list_editor("Special Attacks")
        h.addWidget(pnl1)
        h.addWidget(pnl2)
        h.addWidget(pnl3)
        return widget

    # -- Tab: Health --

    def _create_health_tab(self) -> QtWidgets.QWidget:
        widget = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(widget)

        top = QtWidgets.QHBoxLayout()
        top.addWidget(QtWidgets.QLabel("Damage System:"))
        self.dmg_type_combo = QtWidgets.QComboBox()
        for dt in DamageSystemType:
            self.dmg_type_combo.addItem(dt.value.capitalize(), dt)
        self.dmg_type_combo.currentIndexChanged.connect(self._on_damage_type_changed)
        top.addWidget(self.dmg_type_combo)
        top.addStretch()
        v.addLayout(top)

        self.dmg_stack = QtWidgets.QStackedWidget()
        v.addWidget(self.dmg_stack)

        # Page 0: Box
        box_page = QtWidgets.QWidget()
        box_form = QtWidgets.QFormLayout(box_page)
        self.box_spin = QtWidgets.QSpinBox()
        self.box_spin.setRange(1, 999)
        self.box_spin.setValue(1)
        box_form.addRow("Boxes:", self.box_spin)
        self.dmg_stack.addWidget(box_page)

        # Page 1: Grid
        grid_page = QtWidgets.QWidget()
        gv = QtWidgets.QVBoxLayout(grid_page)
        self.grid_summary_label = QtWidgets.QLabel()
        gv.addWidget(self.grid_summary_label)
        edit_grid_btn = QtWidgets.QPushButton("Edit Grid\u2026")
        edit_grid_btn.clicked.connect(self._on_edit_grid)
        gv.addWidget(edit_grid_btn)
        gv.addStretch()
        self.dmg_stack.addWidget(grid_page)

        # Page 2: Spiral
        spiral_page = QtWidgets.QWidget()
        sv = QtWidgets.QHBoxLayout(spiral_page)
        self._spiral_spins: dict[str, dict[str, QtWidgets.QSpinBox]] = {}
        for aspect_name in ("Mind", "Body", "Spirit"):
            grp = QtWidgets.QGroupBox(aspect_name)
            form = QtWidgets.QFormLayout(grp)
            spins = {}
            for field_name in ("Branch 1", "Branch 2", "Common"):
                sp = QtWidgets.QSpinBox()
                sp.setRange(0, 99)
                form.addRow(f"{field_name}:", sp)
                spins[field_name] = sp
            sv.addWidget(grp)
            self._spiral_spins[aspect_name] = spins
        self.dmg_stack.addWidget(spiral_page)

        # Page 3: Web
        web_page = QtWidgets.QWidget()
        web_form = QtWidgets.QFormLayout(web_page)
        self.web_outer_spin = QtWidgets.QSpinBox()
        self.web_outer_spin.setRange(0, 99)
        self.web_middle_spin = QtWidgets.QSpinBox()
        self.web_middle_spin.setRange(0, 99)
        self.web_center_spin = QtWidgets.QSpinBox()
        self.web_center_spin.setRange(0, 99)
        web_form.addRow("Outer:", self.web_outer_spin)
        web_form.addRow("Middle:", self.web_middle_spin)
        web_form.addRow("Center:", self.web_center_spin)
        self.dmg_stack.addWidget(web_page)

        v.addStretch()
        return widget

    # -- Tab: Spells / Animus --

    def _create_spells_tab(self) -> QtWidgets.QWidget:
        widget = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(widget)
        feat_form = QtWidgets.QFormLayout()
        self.feat_edit = QtWidgets.QLineEdit()
        feat_form.addRow("Feat:", self.feat_edit)
        v.addLayout(feat_form)
        self.spells_list, panel = self._make_string_list_editor("Spells / Animus")
        v.addWidget(panel)
        return widget

    # -- Tab: Weapons --

    def _create_weapons_tab(self) -> QtWidgets.QWidget:
        widget = QtWidgets.QWidget()
        h = QtWidgets.QHBoxLayout(widget)

        self.weapons_list = QtWidgets.QListWidget()
        self.weapons_list.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.weapons_list.itemSelectionChanged.connect(self._on_weapons_selection_changed)
        h.addWidget(self.weapons_list, stretch=1)

        btn_col = QtWidgets.QVBoxLayout()
        add_w = QtWidgets.QPushButton("Add")
        add_w.clicked.connect(self._on_add_weapon)
        edit_w = QtWidgets.QPushButton("Edit")
        edit_w.clicked.connect(self._on_edit_weapon)
        self.edit_weapon_btn = edit_w
        remove_w = QtWidgets.QPushButton("Remove")
        remove_w.clicked.connect(self._on_remove_weapons)
        btn_col.addWidget(add_w)
        btn_col.addWidget(edit_w)
        btn_col.addWidget(remove_w)
        btn_col.addStretch()
        h.addLayout(btn_col)
        return widget

    # -- Tab: Hardpoints --

    def _create_hardpoints_tab(self) -> QtWidgets.QWidget:
        widget = QtWidgets.QWidget()
        h = QtWidgets.QHBoxLayout(widget)

        self.hardpoints_list = QtWidgets.QListWidget()
        self.hardpoints_list.setSelectionMode(
            QtWidgets.QAbstractItemView.ExtendedSelection
        )
        self.hardpoints_list.itemSelectionChanged.connect(
            self._on_hardpoints_selection_changed
        )
        h.addWidget(self.hardpoints_list, stretch=1)

        btn_col = QtWidgets.QVBoxLayout()
        add_h = QtWidgets.QPushButton("Add Group")
        add_h.clicked.connect(self._on_add_hardpoint_group)
        edit_h = QtWidgets.QPushButton("Edit Group")
        edit_h.clicked.connect(self._on_edit_hardpoint_group)
        self.edit_hp_btn = edit_h
        remove_h = QtWidgets.QPushButton("Remove")
        remove_h.clicked.connect(self._on_remove_hardpoint_groups)
        btn_col.addWidget(add_h)
        btn_col.addWidget(edit_h)
        btn_col.addWidget(remove_h)
        btn_col.addStretch()
        h.addLayout(btn_col)
        return widget

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _make_string_list_editor(
        self, title: str
    ) -> tuple[QtWidgets.QListWidget, QtWidgets.QWidget]:
        """Return a (QListWidget, panel) for editing a list of strings."""
        grp = QtWidgets.QGroupBox(title)
        v = QtWidgets.QVBoxLayout(grp)
        lst = QtWidgets.QListWidget()
        lst.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        v.addWidget(lst)
        btns = QtWidgets.QHBoxLayout()
        add_b = QtWidgets.QPushButton("Add")
        edit_b = QtWidgets.QPushButton("Edit")
        remove_b = QtWidgets.QPushButton("Remove")
        btns.addWidget(add_b)
        btns.addWidget(edit_b)
        btns.addWidget(remove_b)
        v.addLayout(btns)

        def on_add() -> None:
            text, ok = QtWidgets.QInputDialog.getText(self, title, "Enter text:")
            if ok and text.strip():
                lst.addItem(text.strip())

        def on_edit() -> None:
            item = lst.currentItem()
            if item:
                text, ok = QtWidgets.QInputDialog.getText(
                    self, title, "Edit text:", text=item.text()
                )
                if ok and text.strip():
                    item.setText(text.strip())

        def on_remove() -> None:
            for it in lst.selectedItems():
                lst.takeItem(lst.row(it))

        add_b.clicked.connect(on_add)
        edit_b.clicked.connect(on_edit)
        remove_b.clicked.connect(on_remove)
        return lst, grp

    def _load_card(self, card: ModelStatCard) -> None:
        self.name_edit.setText(card.name)
        self.short_name_edit.setText(card.short_name)

        idx = self.faction_combo.findData(card.faction)
        if idx >= 0:
            self.faction_combo.setCurrentIndex(idx)
        idx = self.basic_type_combo.findData(card.basic_type)
        if idx >= 0:
            self.basic_type_combo.setCurrentIndex(idx)
        idx = self.base_size_combo.findData(card.base_size)
        if idx >= 0:
            self.base_size_combo.setCurrentIndex(idx)

        self.cost_spin.setValue(card.cost)
        self.is_char_cb.setChecked(card.is_character)
        self.fa_spin.setValue(card.fa)

        self.vocal_list.clear()
        for vn in card.vocal_names:
            self.vocal_list.addItem(vn)

        self.armies_tag.set_values(card.armies)
        self.keywords_tag.set_values(card.keywords)
        self.advantages_tag.set_values(card.advantages)
        self.resistances_tag.set_values(card.model_resistances)

        s = card.model_statistics
        self._stat_spins["SPD"].setValue(s.spd)
        self._stat_spins["AAT"].setValue(s.aat)
        self._stat_spins["MAT"].setValue(s.mat)
        self._stat_spins["RAT"].setValue(s.rat)
        self._stat_spins["DEF"].setValue(s.def_)
        self._stat_spins["ARM"].setValue(s.arm)
        self._stat_spins["ARC"].setValue(s.arc)
        self._stat_spins["CTRL"].setValue(s.ctrl)
        self._stat_spins["FURY"].setValue(s.fury)
        self._stat_spins["THR"].setValue(s.thr)

        self._set_damage_system(card.damage_system_type, card.damage_system)

        self._load_string_list(self.special_rules_list, card.special_rules)
        self._load_string_list(self.special_actions_list, card.special_actions)
        self._load_string_list(self.special_attacks_list, card.special_attacks)

        self.feat_edit.setText(card.feat)
        self._load_string_list(self.spells_list, card.spells)

        self._weapons = list(card.melee_weapons) + list(card.range_weapons)
        self._refresh_weapons_list()

        self._hardpoint_groups = [list(g) for g in card.available_hardpoints]
        self._refresh_hardpoints_list()
        self._update_stat_visibility()

    def _reset_to_defaults(self) -> None:
        self.name_edit.clear()
        self.short_name_edit.clear()
        self.faction_combo.setCurrentIndex(0)
        self.basic_type_combo.setCurrentIndex(0)
        self.base_size_combo.setCurrentIndex(0)
        self.cost_spin.setValue(0)
        self.is_char_cb.setChecked(False)
        self.fa_spin.setValue(-1)
        self.vocal_list.clear()
        for tag in (
            self.armies_tag,
            self.keywords_tag,
            self.advantages_tag,
            self.resistances_tag,
        ):
            tag.clear()
        for spin in self._stat_spins.values():
            spin.setValue(-1)
        self.dmg_type_combo.setCurrentIndex(0)
        self.box_spin.setValue(1)
        self._left_grid_data = [[DamageKey.BLANK] * GRID_SIZE for _ in range(GRID_SIZE)]
        self._right_grid_data = None
        self._update_grid_summary()
        self._update_stat_visibility()
        self.special_rules_list.clear()
        self.special_actions_list.clear()
        self.special_attacks_list.clear()
        self.feat_edit.clear()
        self.spells_list.clear()
        self._weapons = []
        self._refresh_weapons_list()
        self._hardpoint_groups = []
        self._refresh_hardpoints_list()

    def _build_card(self) -> Optional[ModelStatCard]:
        name = self.name_edit.text().strip()
        if not name:
            QtWidgets.QMessageBox.warning(self, "Validation", "Name cannot be empty.")
            return None
        short_name = self.short_name_edit.text().strip()
        if not short_name:
            QtWidgets.QMessageBox.warning(
                self, "Validation", "Short Name cannot be empty."
            )
            return None
        try:
            stats = ModelStatistics(
                spd=self._stat_spins["SPD"].value(),
                aat=self._stat_spins["AAT"].value(),
                mat=self._stat_spins["MAT"].value(),
                rat=self._stat_spins["RAT"].value(),
                def_=self._stat_spins["DEF"].value(),
                arm=self._stat_spins["ARM"].value(),
                arc=self._stat_spins["ARC"].value(),
                ctrl=self._stat_spins["CTRL"].value(),
                fury=self._stat_spins["FURY"].value(),
                thr=self._stat_spins["THR"].value(),
            )
        except ValueError as exc:
            QtWidgets.QMessageBox.warning(self, "Validation", str(exc))
            return None

        try:
            return ModelStatCard(
                name=name,
                short_name=short_name,
                vocal_names=[
                    self.vocal_list.item(i).text()
                    for i in range(self.vocal_list.count())
                ],
                faction=Faction(self.faction_combo.currentData()),
                basic_type=BasicType(self.basic_type_combo.currentData()),
                base_size=self.base_size_combo.currentData(),
                cost=self.cost_spin.value(),
                model_statistics=stats,
                damage_system_type=DamageSystemType(self.dmg_type_combo.currentData()),
                damage_system=self._get_current_damage_system(),
                is_character=self.is_char_cb.isChecked(),
                fa=self.fa_spin.value(),
                armies=self.armies_tag.selected_values(),
                keywords=self.keywords_tag.selected_values(),
                advantages=[
                    ModelAdvantage(v) for v in self.advantages_tag.selected_values()
                ],
                model_resistances=[
                    ModelResistance(v) for v in self.resistances_tag.selected_values()
                ],
                special_rules=self._list_widget_strings(self.special_rules_list),
                special_actions=self._list_widget_strings(self.special_actions_list),
                special_attacks=self._list_widget_strings(self.special_attacks_list),
                feat=self.feat_edit.text(),
                spells=self._list_widget_strings(self.spells_list),
                melee_weapons=[w for w in self._weapons if isinstance(w, MeleeWeapon)],
                range_weapons=[w for w in self._weapons if isinstance(w, RangeWeapon)],
                available_hardpoints=self._hardpoint_groups,
            )
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "Validation Error", str(exc))
            return None

    # ------------------------------------------------------------------
    # Slots – bottom buttons
    # ------------------------------------------------------------------

    def _connect_dirty_signals(self) -> None:
        self.name_edit.textChanged.connect(self._mark_dirty)
        self.short_name_edit.textChanged.connect(self._mark_dirty)
        self.faction_combo.currentIndexChanged.connect(self._mark_dirty)
        self.basic_type_combo.currentIndexChanged.connect(self._mark_dirty)
        self.base_size_combo.currentIndexChanged.connect(self._mark_dirty)
        self.cost_spin.valueChanged.connect(self._mark_dirty)
        self.is_char_cb.stateChanged.connect(self._mark_dirty)
        self.fa_spin.valueChanged.connect(self._mark_dirty)
        self.dmg_type_combo.currentIndexChanged.connect(self._mark_dirty)
        self.box_spin.valueChanged.connect(self._mark_dirty)
        self.feat_edit.textChanged.connect(self._mark_dirty)
        for spin in self._stat_spins.values():
            spin.valueChanged.connect(self._mark_dirty)
        for tag in (self.armies_tag, self.keywords_tag,
                    self.advantages_tag, self.resistances_tag):
            tag.changed.connect(self._mark_dirty)
        for lst in (self.vocal_list, self.special_rules_list,
                    self.special_actions_list, self.special_attacks_list,
                    self.spells_list):
            lst.model().rowsInserted.connect(self._mark_dirty)
            lst.model().rowsRemoved.connect(self._mark_dirty)

    @QtCore.Slot()
    def _mark_dirty(self, *_) -> None:
        self._dirty = True

    def closeEvent(self, event) -> None:
        if self._recording_vocal:
            self._stop_vocal_recording()
        if self._dirty:
            reply = QtWidgets.QMessageBox.question(
                self,
                "Unsaved Changes",
                "You have unsaved changes. Close without saving?",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                QtWidgets.QMessageBox.No,
            )
            if reply != QtWidgets.QMessageBox.Yes:
                event.ignore()
                return
        super().closeEvent(event)

    @QtCore.Slot()
    def _on_save(self) -> None:
        card = self._build_card()
        if card is not None:
            self._result_card = card
            self._original_card = card
            self._dirty = False

    @QtCore.Slot()
    def _on_revert(self) -> None:
        if self._original_card is not None:
            self._load_card(self._original_card)
        else:
            self._reset_to_defaults()
        self._dirty = False

    @QtCore.Slot()
    def _on_close(self) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Slots – vocal names
    # ------------------------------------------------------------------

    @QtCore.Slot()
    def _on_record_vocal_name(self) -> None:
        if self._recording_vocal:
            self._stop_vocal_recording()
        else:
            self._vocal_dup_label.clear()
            self._recording_vocal = True
            self._record_vn_btn.setText("Abort")
            self._record_vn_btn.setStyleSheet(
                "QPushButton { background-color: crimson; color: white; font-weight: bold; }"
            )
            self._event_manager.push_speech_handler(self._on_vocal_speech)

    def _on_vocal_speech(self, text: str) -> None:
        self._stop_vocal_recording()
        text = text.strip()
        if not text:
            return
        text_lower = text.lower()
        existing_lower = [
            self.vocal_list.item(i).text().lower()
            for i in range(self.vocal_list.count())
        ]
        model_name_lower = self.name_edit.text().strip().lower()
        if text_lower in existing_lower or text_lower == model_name_lower:
            self._vocal_dup_label.setText(f'"{text}" already exists.')
        else:
            self._vocal_dup_label.clear()
            self.vocal_list.addItem(text)

    def _stop_vocal_recording(self) -> None:
        self._recording_vocal = False
        self._record_vn_btn.setText("Record")
        self._record_vn_btn.setStyleSheet("")
        if self._event_manager is not None:
            self._event_manager.pop_speech_handler(self._on_vocal_speech)

    @QtCore.Slot()
    def _on_remove_vocal_name(self) -> None:
        for it in self.vocal_list.selectedItems():
            self.vocal_list.takeItem(self.vocal_list.row(it))

    # ------------------------------------------------------------------
    # Slots – weapons
    # ------------------------------------------------------------------

    @QtCore.Slot()
    def _on_weapons_selection_changed(self) -> None:
        single = len(self.weapons_list.selectedItems()) == 1
        self.edit_weapon_btn.setEnabled(single)

    @QtCore.Slot()
    def _on_add_weapon(self) -> None:
        dlg = WeaponEditorDialog(parent=self)
        if dlg.exec() == QtWidgets.QDialog.Accepted and dlg.result_weapon:
            self._weapons.append(dlg.result_weapon)
            self._refresh_weapons_list()

    @QtCore.Slot()
    def _on_edit_weapon(self) -> None:
        items = self.weapons_list.selectedItems()
        if len(items) != 1:
            return
        idx = self.weapons_list.row(items[0])
        dlg = WeaponEditorDialog(weapon=self._weapons[idx], parent=self)
        if dlg.exec() == QtWidgets.QDialog.Accepted and dlg.result_weapon:
            self._weapons[idx] = dlg.result_weapon
            self._refresh_weapons_list()

    @QtCore.Slot()
    def _on_remove_weapons(self) -> None:
        rows = sorted(
            {self.weapons_list.row(it) for it in self.weapons_list.selectedItems()},
            reverse=True,
        )
        for row in rows:
            del self._weapons[row]
        self._refresh_weapons_list()

    def _refresh_weapons_list(self) -> None:
        self.weapons_list.clear()
        for w in self._weapons:
            self.weapons_list.addItem(self._format_weapon(w))

    @staticmethod
    def _format_weapon(w: Union[MeleeWeapon, RangeWeapon]) -> str:
        loc = w.location.value if isinstance(w.location, WeaponLocation) else w.location
        prefix = f"{'2x ' if w.two_x else ''}{w.name or '(unnamed)'}"
        if isinstance(w, RangeWeapon):
            aoe = f", AOE={w.area_of_effect}" if w.area_of_effect else ""
            rof_parts = []
            if w.rof_dice:
                rof_parts.append(f"{w.rof_dice}D3")
            if w.rof_flat or not rof_parts:
                rof_parts.append(str(w.rof_flat))
            rof = "+".join(rof_parts)
            return f"[Ranged | {loc}]  {prefix}  RNG={w.range}, ROF={rof}, POW={w.power}{aoe}"
        return f"[Melee | {loc}]  {prefix}  RNG={w.range}, POW={w.power}"

    # ------------------------------------------------------------------
    # Slots – hardpoints
    # ------------------------------------------------------------------

    @QtCore.Slot()
    def _on_hardpoints_selection_changed(self) -> None:
        single = len(self.hardpoints_list.selectedItems()) == 1
        self.edit_hp_btn.setEnabled(single)

    @QtCore.Slot()
    def _on_add_hardpoint_group(self) -> None:
        dlg = HardpointGroupEditorDialog(parent=self)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            self._hardpoint_groups.append(dlg.result_group)
            self._refresh_hardpoints_list()

    @QtCore.Slot()
    def _on_edit_hardpoint_group(self) -> None:
        items = self.hardpoints_list.selectedItems()
        if len(items) != 1:
            return
        idx = self.hardpoints_list.row(items[0])
        dlg = HardpointGroupEditorDialog(group=self._hardpoint_groups[idx], parent=self)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            self._hardpoint_groups[idx] = dlg.result_group
            self._refresh_hardpoints_list()

    @QtCore.Slot()
    def _on_remove_hardpoint_groups(self) -> None:
        rows = sorted(
            {
                self.hardpoints_list.row(it)
                for it in self.hardpoints_list.selectedItems()
            },
            reverse=True,
        )
        for row in rows:
            del self._hardpoint_groups[row]
        self._refresh_hardpoints_list()

    def _refresh_hardpoints_list(self) -> None:
        self.hardpoints_list.clear()
        for i, group in enumerate(self._hardpoint_groups):
            names = ", ".join(f"{hp.name} [{hp.location.value}]" for hp in group)
            self.hardpoints_list.addItem(f"Group {i + 1}: {names}" if names else f"Group {i + 1}: (empty)")

    # ------------------------------------------------------------------
    # Slots – health / damage system
    # ------------------------------------------------------------------

    @QtCore.Slot(int)
    def _on_damage_type_changed(self, index: int) -> None:
        self.dmg_stack.setCurrentIndex(index)

    @QtCore.Slot()
    def _on_edit_grid(self) -> None:
        dlg = DamageGridEditorDialog(
            left_grid=self._left_grid_data,
            right_grid=self._right_grid_data,
            parent=self,
        )
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            self._left_grid_data = dlg.left_grid
            self._right_grid_data = dlg.right_grid
            self._update_grid_summary()

    def _update_grid_summary(self) -> None:
        grids = 2 if self._right_grid_data is not None else 1
        non_blank = sum(
            1 for row in self._left_grid_data for dk in row if dk != DamageKey.NA
        )
        if self._right_grid_data is not None:
            non_blank += sum(
                1 for row in self._right_grid_data for dk in row if dk != DamageKey.NA
            )
        total = GRID_SIZE * GRID_SIZE * grids
        self.grid_summary_label.setText(
            f"{grids} grid{'s' if grids > 1 else ''}  —  "
            f"{non_blank} / {total} cells configured"
        )

    def _get_current_damage_system(self):
        dt = DamageSystemType(self.dmg_type_combo.currentData())
        if dt == DamageSystemType.BOX:
            return BoxDamageSystem(boxes=self.box_spin.value())
        if dt == DamageSystemType.GRID:
            return GridDamageSystem(
                left_grid=self._left_grid_data,
                right_grid=self._right_grid_data,
            )
        if dt == DamageSystemType.SPIRAL:
            aspects = {}
            for aspect_name in ("Mind", "Body", "Spirit"):
                spins = self._spiral_spins[aspect_name]
                aspects[aspect_name] = SpiralAspect(
                    branch1=spins["Branch 1"].value(),
                    branch2=spins["Branch 2"].value(),
                    common=spins["Common"].value(),
                )
            return SpiralDamageSystem(
                mind=aspects["Mind"], body=aspects["Body"], spirit=aspects["Spirit"]
            )
        return WebDamageSystem(
            outer=self.web_outer_spin.value(),
            middle=self.web_middle_spin.value(),
            center=self.web_center_spin.value(),
        )

    def _set_damage_system(self, dt: DamageSystemType, ds) -> None:
        idx = self.dmg_type_combo.findData(dt)
        if idx >= 0:
            self.dmg_type_combo.setCurrentIndex(idx)
        if isinstance(ds, BoxDamageSystem):
            self.box_spin.setValue(ds.boxes)
        elif isinstance(ds, GridDamageSystem):
            self._left_grid_data = [row[:] for row in ds.left_grid]
            self._right_grid_data = (
                [row[:] for row in ds.right_grid]
                if ds.right_grid is not None
                else None
            )
            self._update_grid_summary()
        elif isinstance(ds, SpiralDamageSystem):
            for aspect_name, aspect in (
                ("Mind", ds.mind),
                ("Body", ds.body),
                ("Spirit", ds.spirit),
            ):
                spins = self._spiral_spins[aspect_name]
                spins["Branch 1"].setValue(aspect.branch1)
                spins["Branch 2"].setValue(aspect.branch2)
                spins["Common"].setValue(aspect.common)
        elif isinstance(ds, WebDamageSystem):
            self.web_outer_spin.setValue(ds.outer)
            self.web_middle_spin.setValue(ds.middle)
            self.web_center_spin.setValue(ds.center)

    # ------------------------------------------------------------------
    # Utility helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _select_list_items(
        lst: QtWidgets.QListWidget, values: set[str]
    ) -> None:
        lst.clearSelection()
        for i in range(lst.count()):
            if lst.item(i).text() in values:
                lst.item(i).setSelected(True)

    @staticmethod
    def _selected_enum_items(lst: QtWidgets.QListWidget, enum_cls):
        return [enum_cls(lst.item(i).text()) for i in range(lst.count()) if lst.item(i).isSelected()]

    @staticmethod
    def _list_widget_strings(lst: QtWidgets.QListWidget) -> list[str]:
        return [lst.item(i).text() for i in range(lst.count())]

    @staticmethod
    def _load_string_list(lst: QtWidgets.QListWidget, strings: list[str]) -> None:
        lst.clear()
        for s in strings:
            lst.addItem(s)
