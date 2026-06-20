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

"""Append-only game log for the Warmachine game.

Writes every narrator utterance and player command to a timestamped file on
disk so the session can be reviewed later as a story.  Only the most recent
lines are kept in memory for the UI display widget, avoiding unbounded growth.
"""

from __future__ import annotations

import datetime
from collections import deque
from pathlib import Path
from typing import Optional

from PySide6 import QtCore

_LOG_DIR = Path(__file__).parent.parent / "logs"
_MAX_DISPLAY_LINES = 100


class GameLog(QtCore.QObject):
    """Append-only game log backed by a file on disk.

    Attributes:
        line_added: Emitted with the display-friendly text whenever a new
            line is appended.
    """

    line_added = QtCore.Signal(str)

    def __init__(
        self,
        log_dir: Path = _LOG_DIR,
        parent: Optional[QtCore.QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._log_dir = log_dir
        self._log_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self._path = self._log_dir / f"match_{ts}.log"
        self._file = open(self._path, "a", encoding="utf-8")
        self._recent: deque[str] = deque(maxlen=_MAX_DISPLAY_LINES)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def path(self) -> Path:
        """Path to the log file on disk."""
        return self._path

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def narrate(self, text: str) -> None:
        """Log a narrator line."""
        self._write("Narrator", text)

    def player_said(self, player_label: str, text: str) -> None:
        """Log a player command."""
        self._write(player_label, text)

    def system(self, text: str) -> None:
        """Log a system / meta message."""
        self._write("System", text)

    def recent_lines(self) -> list[str]:
        """Return the most recent display lines (up to 100)."""
        return list(self._recent)

    def close(self) -> None:
        """Flush and close the backing file."""
        if self._file and not self._file.closed:
            self._file.close()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _write(self, speaker: str, text: str) -> None:
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # Full line on disk (with timestamp)
        disk_line = f"[{ts}] {speaker}: {text}"
        self._file.write(disk_line + "\n")
        self._file.flush()
        # Story-friendly display line (no timestamp)
        display_line = f"{speaker}: {text}"
        self._recent.append(display_line)
        self.line_added.emit(display_line)
