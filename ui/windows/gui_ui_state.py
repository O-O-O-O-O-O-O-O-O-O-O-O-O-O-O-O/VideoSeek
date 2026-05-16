"""AppUiState wiring — push helpers and signal handlers for MainWindow."""

from __future__ import annotations

from ui.state.app_ui_state import AppUiState


class AppUiStateMixin:
    """Owns `ui_state` and routes resource / inference / indexing updates to existing GUI helpers."""

    def _init_ui_state(self) -> None:
        self.ui_state = AppUiState(self)
        self.ui_state.indexing_changed.connect(self._on_ui_state_indexing_changed)
        self.ui_state.resources_changed.connect(self._on_ui_state_resources_changed)
        self.ui_state.inference_changed.connect(self._on_ui_state_inference_changed)

    def push_resources_status(self, status: dict | None = None) -> None:
        if status is None:
            from src.services.runtime_resource_service import get_runtime_resource_status

            status = get_runtime_resource_status()
        self.ui_state.set_resources_status(status)

    def push_inference_status(self, status: dict | None = None) -> None:
        if status is None:
            from src.core.clip_embedding import get_engine_runtime_status

            status = get_engine_runtime_status()
        self.ui_state.set_inference_status(status)

    def _on_ui_state_indexing_changed(self, _running: bool) -> None:
        self._refresh_search_session_hint()

    def _on_ui_state_resources_changed(self, status: dict) -> None:
        self._apply_runtime_resource_status(status)

    def _on_ui_state_inference_changed(self, status: dict) -> None:
        self._update_inference_backend_hint(status)

    @property
    def models_ready(self) -> bool:
        """Model runtime resources ready (alias for ui_state.model_ready)."""
        return self.ui_state.model_ready

    @property
    def resources_ready(self) -> bool:
        """Model + FFmpeg runtime resources ready."""
        return self.ui_state.resources_ready
