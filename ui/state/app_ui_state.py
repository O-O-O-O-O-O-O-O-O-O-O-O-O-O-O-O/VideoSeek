"""Centralized read-only UI state with change signals for MainWindow bindings."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class AppUiState(QObject):
    """Tracks presentation-relevant flags; controllers push updates, GUI reacts via signals."""

    indexing_changed = Signal(bool)
    resources_changed = Signal(dict)
    inference_changed = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._indexing_running = False
        self._resources_status: dict = {}
        self._inference_status: dict = {}

    @property
    def indexing_running(self) -> bool:
        return self._indexing_running

    @property
    def resources_status(self) -> dict:
        return dict(self._resources_status)

    @property
    def inference_status(self) -> dict:
        return dict(self._inference_status)

    @property
    def resources_ready(self) -> bool:
        return bool(self._resources_status.get("resources_ready"))

    @property
    def model_ready(self) -> bool:
        return bool(self._resources_status.get("model_ready"))

    @property
    def ffmpeg_ready(self) -> bool:
        return bool(self._resources_status.get("ffmpeg_ready"))

    def set_indexing_running(self, running: bool) -> None:
        running = bool(running)
        if self._indexing_running == running:
            return
        self._indexing_running = running
        self.indexing_changed.emit(running)

    def set_resources_status(self, status: dict | None) -> None:
        self._resources_status = dict(status or {})
        self.resources_changed.emit(self._resources_status)

    def set_inference_status(self, status: dict | None) -> None:
        self._inference_status = dict(status or {})
        self.inference_changed.emit(self._inference_status)
