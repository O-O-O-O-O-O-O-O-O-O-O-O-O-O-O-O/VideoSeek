from PySide6.QtCore import QObject, Signal

from src.app.i18n import get_texts
from src.services.runtime_resource_service import (
    ensure_runtime_resource_dirs,
    get_runtime_resource_location_text,
    get_runtime_resource_status,
)
from ui.dialogs import ModelDownloadDialog
from ui.threading_utils import shutdown_thread
from ui.workers import ResourceDownloadWorker


class RuntimeResourceController(QObject):
    startup_cancelled = Signal()
    resources_ready = Signal(dict)
    status_changed = Signal(dict)

    def __init__(self, parent_window):
        super().__init__(parent_window)
        self.parent_window = parent_window
        self.dialog = None
        self.worker = None
        self._dialog_theme = None
        self._dialog_language = None

    def check_resources(self, show_dialog=True):
        status = get_runtime_resource_status()
        self.status_changed.emit(status)
        if status["resources_ready"]:
            return True
        if show_dialog:
            self.show_missing_dialog(status)
        return False

    def get_status_snapshot(self):
        return get_runtime_resource_status()

    def show_missing_dialog(self, status=None):
        status = status or get_runtime_resource_status()
        ensure_runtime_resource_dirs(status)
        dialog = self._ensure_dialog()
        dialog.set_missing_state(
            status["display_files"],
            get_runtime_resource_location_text(
                status=status,
                include_ffmpeg=not status["ffmpeg_ready"] or not status["model_ready"],
            ),
            download_enabled=status["download_enabled"],
        )
        dialog.exec()

    def show_manage_dialog(self):
        status = get_runtime_resource_status()
        ensure_runtime_resource_dirs(status)
        dialog = self._ensure_dialog()
        if status.get("resources_ready"):
            dialog.set_manage_state()
        else:
            dialog.set_missing_state(
                status["display_files"],
                get_runtime_resource_location_text(
                    status=status,
                    include_ffmpeg=not status["ffmpeg_ready"] or not status["model_ready"],
                ),
                download_enabled=status["download_enabled"],
            )
        dialog.exec()

    def start_download(self):
        if self.worker and self.worker.isRunning():
            return

        status = get_runtime_resource_status()
        if not status["download_enabled"]:
            texts = get_texts(self.parent_window.language)
            self.parent_window.show_info_dialog(
                texts["warning_title"],
                texts["download_models_unavailable"],
                kind="warning",
            )
            return

        dialog = self._ensure_dialog()
        dialog.set_progress_state(0, get_texts(self.parent_window.language)["model_download_starting"])

        self.worker = ResourceDownloadWorker(
            need_models=bool(status["missing_model_files"]),
            need_ffmpeg=not status["ffmpeg_ready"],
        )
        self.worker.progress_signal.connect(self._update_progress)
        self.worker.finished_signal.connect(self._finish_download)
        self.worker.error_signal.connect(self._fail_download)
        self.worker.start()

    def shutdown(self):
        shutdown_thread(self.worker)

    def _ensure_dialog(self):
        current_theme = bool(self.parent_window.is_dark_mode)
        current_language = str(self.parent_window.language)
        if (
            self.dialog is not None
            and (self._dialog_theme != current_theme or self._dialog_language != current_language)
        ):
            self.dialog.close()
            self.dialog.deleteLater()
            self.dialog = None
        if self.dialog is None:
            self.dialog = ModelDownloadDialog(
                self.parent_window,
                current_theme,
                current_language,
            )
            self.dialog.import_requested.connect(self.parent_window.parse_model_packages)
            self.dialog.go_download_requested.connect(self.parent_window.open_model_package_download_page)
            self._dialog_theme = current_theme
            self._dialog_language = current_language
        return self.dialog

    def _update_progress(self, value, text):
        if self.dialog:
            self.dialog.set_progress_state(value, text)

    def _finish_download(self, result):
        status = get_runtime_resource_status()
        self.status_changed.emit(status)
        if self.dialog:
            self.dialog.set_success_state(
                get_runtime_resource_location_text(status=status, include_ffmpeg=True)
            )
        self.resources_ready.emit(result)

    def _fail_download(self, error_text):
        status = get_runtime_resource_status()
        self.status_changed.emit(status)
        if self.dialog:
            self.dialog.set_error_state(
                error_text,
                status["display_files"],
                get_runtime_resource_location_text(
                    status=status,
                    include_ffmpeg=not status["ffmpeg_ready"],
                ),
                download_enabled=status["download_enabled"],
            )
