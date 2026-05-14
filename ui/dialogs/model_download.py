from PySide6.QtCore import QEvent, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QAbstractItemView, QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QProgressBar, QPushButton, QVBoxLayout

from src.app.i18n import get_texts
from ui.widgets.layout import WINDOW_SIZES, apply_dialog_size
from ui.widgets.styles import THEME_COLORS_DARK, THEME_COLORS_LIGHT


class ModelDownloadDialog(QDialog):
    upload_requested = Signal()
    import_requested = Signal(list)
    go_download_requested = Signal()

    def __init__(self, parent=None, is_dark=True, language="zh"):
        super().__init__(parent)
        self.texts = get_texts(language)
        self._is_dark = bool(is_dark)
        self._downloading = False
        self._selected_files = []

        self.setWindowTitle(self.texts["models_missing_title"])
        self.setModal(True)
        self.setAcceptDrops(True)
        self.setWindowFlag(Qt.WindowCloseButtonHint, True)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        apply_dialog_size(
            self,
            QSize(860, 520),
            QSize(760, 460),
            WINDOW_SIZES["notice_dialog"]["screen_margin"],
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 18, 18, 18)

        card = QFrame()
        card.setObjectName("Card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(24, 24, 24, 20)
        layout.setSpacing(12)

        self.title_label = QLabel(self.texts["models_missing_title"])
        self.title_label.setObjectName("DialogHeadline")
        self.body_label = QLabel()
        self.body_label.setObjectName("DialogBodyLabel")
        self.body_label.setWordWrap(True)
        self.body_label.setTextFormat(Qt.RichText)

        self.upload_area = QPushButton(self.texts.get("model_upload_area_hint", "Drop .zip/.sha256"))
        self.upload_area.setObjectName("ModelUploadArea")
        self.upload_area.setMinimumHeight(72)
        self.upload_area.setCursor(Qt.PointingHandCursor)
        self.upload_file_list = QListWidget()
        self.upload_file_list.setObjectName("ModelFileList")
        self.upload_file_list.setMinimumHeight(148)
        self.upload_file_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.upload_file_list.setAlternatingRowColors(False)
        self.upload_file_list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)

        self.progress_title = QLabel(self.texts["model_download_waiting"])
        self.progress_title.setObjectName("Hint")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_label = QLabel()
        self.progress_label.setObjectName("DialogBodyLabel")
        self.progress_label.setWordWrap(True)

        utility_row = QHBoxLayout()
        utility_row.setSpacing(8)
        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        self.go_download_button = QPushButton(self.texts.get("model_go_download_page", "Go to Download"))
        self.go_download_button.setObjectName("SearchButton")
        self.go_download_button.setMinimumWidth(196)
        self.go_download_button.setMinimumHeight(38)
        self.add_files_button = QPushButton(self.texts.get("model_upload_add_files", "Add Files"))
        self.add_files_button.setObjectName("PrimaryButton")
        self.add_files_button.setMinimumWidth(124)
        self.add_files_button.setMinimumHeight(36)
        self.remove_files_button = QPushButton(self.texts.get("model_upload_remove_selected", "Remove Selected"))
        self.remove_files_button.setObjectName("DangerGhostButton")
        self.remove_files_button.setMinimumWidth(132)
        self.remove_files_button.setMinimumHeight(36)
        self.clear_files_button = QPushButton(self.texts.get("model_upload_clear_files", "Clear"))
        self.clear_files_button.setObjectName("SolidDangerButton")
        self.clear_files_button.setMinimumWidth(100)
        self.clear_files_button.setMinimumHeight(36)
        self.import_button = QPushButton(self.texts.get("model_upload_package", "Import and Parse Package"))
        self.import_button.setObjectName("PrimaryButton")
        self.import_button.setMinimumWidth(232)
        self.import_button.setMinimumHeight(38)
        self.done_button = QPushButton(self.texts["model_ready_action"])
        self.done_button.setObjectName("PrimaryButton")
        self.done_button.hide()
        utility_row.addWidget(self.add_files_button)
        utility_row.addWidget(self.remove_files_button)
        utility_row.addWidget(self.clear_files_button)
        utility_row.addStretch()
        action_row.addStretch()
        action_row.addWidget(self.go_download_button)
        action_row.addWidget(self.import_button)
        action_row.addStretch()
        action_row.addWidget(self.done_button)

        layout.addWidget(self.title_label)
        layout.addWidget(self.body_label)
        layout.addWidget(self.upload_area)
        layout.addWidget(self.upload_file_list)
        layout.addWidget(self.progress_title)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.progress_label)
        layout.addLayout(utility_row)
        layout.addLayout(action_row)
        outer.addWidget(card)

        self.add_files_button.clicked.connect(self._select_files)
        self.remove_files_button.clicked.connect(self._remove_selected_files)
        self.clear_files_button.clicked.connect(self._clear_files)
        self.upload_area.clicked.connect(self._select_files)
        self.import_button.clicked.connect(self._emit_import_requested)
        self.go_download_button.clicked.connect(self.go_download_requested.emit)
        self.done_button.clicked.connect(self.accept)
        self._refresh_file_list()

    def showEvent(self, event):
        super().showEvent(event)
        # On first startup the top-level window frame may still be moving (WM placement / DPI),
        # and Qt can reposition a modal dialog once the native window exists. Re-apply a few times.
        for delay_ms in (0, 16, 50, 120, 200):
            QTimer.singleShot(delay_ms, self._center_over_parent_or_screen)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.ActivationChange and self.isActiveWindow():
            QTimer.singleShot(0, self._center_over_parent_or_screen)

    def _center_over_parent_or_screen(self):
        if not self.isVisible():
            return
        center_point = None
        parent = self.parentWidget()
        if parent is not None:
            top = parent.window()
            if top is not None and top.isVisible():
                frame_top = top.frameGeometry()
                if frame_top.width() >= 200 and frame_top.height() >= 200:
                    center_point = frame_top.center()
        if center_point is None:
            screen = None
            if parent is not None:
                ref = parent.mapToGlobal(parent.rect().center())
                screen = QGuiApplication.screenAt(ref)
            if screen is None:
                screen = QGuiApplication.primaryScreen()
            if screen is None:
                return
            center_point = screen.availableGeometry().center()
        frame = self.frameGeometry()
        frame.moveCenter(center_point)
        self.move(frame.topLeft())

    def set_missing_state(self, missing_files, folder, download_enabled=True):
        self._downloading = False
        self.title_label.setText(self.texts["models_missing_title"])
        has_model_missing = any(str(item).lower() != "ffmpeg.exe" for item in (missing_files or []))
        has_ffmpeg_missing = any(str(item).lower() == "ffmpeg.exe" for item in (missing_files or []))
        if has_model_missing and has_ffmpeg_missing:
            missing_text = self.texts.get("models_missing_generic_both", "Model and FFmpeg are not ready.")
        elif has_model_missing:
            missing_text = self.texts.get("models_missing_generic_model", "Model resources are missing.")
        elif has_ffmpeg_missing:
            missing_text = self.texts.get("models_missing_generic_ffmpeg", "FFmpeg is missing.")
        else:
            missing_text = self.texts.get("models_missing_generic_unknown", "Runtime resources are incomplete.")
        status_html = self._build_resource_status_html(has_model_missing=has_model_missing, has_ffmpeg_missing=has_ffmpeg_missing)
        model_guide = self.texts.get("model_package_guide", "").strip()
        if model_guide:
            self.body_label.setText(f"{status_html}<br><br>{missing_text}<br><br>{model_guide}")
        else:
            self.body_label.setText(f"{status_html}<br><br>{missing_text}")
        self.body_label.show()
        self.upload_area.show()
        self.progress_title.hide()
        self.progress_bar.hide()
        self.progress_label.hide()
        self.go_download_button.show()
        self.go_download_button.setEnabled(download_enabled)
        self.add_files_button.show()
        self.add_files_button.setEnabled(True)
        self.remove_files_button.show()
        self.remove_files_button.setEnabled(bool(self._selected_files))
        self.clear_files_button.show()
        self.clear_files_button.setEnabled(bool(self._selected_files))
        self.import_button.show()
        self.import_button.setEnabled(bool(self._selected_files))
        self.upload_area.setEnabled(True)
        self.upload_file_list.setEnabled(True)
        self.upload_file_list.show()
        self.done_button.hide()

    def set_progress_state(self, value, text):
        self._downloading = True
        self.title_label.setText(self.texts["download_models"])
        self.body_label.hide()
        self.upload_area.hide()
        self.progress_title.show()
        self.progress_bar.show()
        self.progress_label.show()
        self.progress_title.setText(self.texts["model_download_in_progress"])
        self.progress_bar.setValue(value)
        self.progress_label.setText(text)
        self.go_download_button.setEnabled(False)
        self.add_files_button.setEnabled(False)
        self.remove_files_button.setEnabled(False)
        self.clear_files_button.setEnabled(False)
        self.import_button.setEnabled(False)
        self.upload_area.setEnabled(False)
        self.upload_file_list.setEnabled(False)
        self.done_button.hide()

    def set_import_progress_state(self, value, text):
        self._downloading = True
        self.title_label.setText(self.texts.get("model_upload_package", "Import and Parse Package"))
        self.body_label.hide()
        self.upload_area.hide()
        self.progress_title.show()
        self.progress_bar.show()
        self.progress_label.show()
        self.progress_title.setText(self.texts.get("model_import_in_progress", "Importing model package"))
        self.progress_bar.setValue(value)
        self.progress_label.setText(text)
        self.go_download_button.setEnabled(False)
        self.add_files_button.setEnabled(False)
        self.remove_files_button.setEnabled(False)
        self.clear_files_button.setEnabled(False)
        self.import_button.setEnabled(False)
        self.upload_area.setEnabled(False)
        self.upload_file_list.setEnabled(False)
        self.done_button.hide()

    def set_error_state(self, error_text, missing_files, folder, download_enabled=True):
        self._downloading = False
        self.title_label.setText(self.texts["model_download_failed"])
        has_model_missing = any(str(item).lower() != "ffmpeg.exe" for item in (missing_files or []))
        has_ffmpeg_missing = any(str(item).lower() == "ffmpeg.exe" for item in (missing_files or []))
        if has_model_missing and has_ffmpeg_missing:
            missing_text = self.texts.get("models_missing_generic_both", "Model and FFmpeg are not ready.")
        elif has_model_missing:
            missing_text = self.texts.get("models_missing_generic_model", "Model resources are missing.")
        elif has_ffmpeg_missing:
            missing_text = self.texts.get("models_missing_generic_ffmpeg", "FFmpeg is missing.")
        else:
            missing_text = self.texts.get("models_missing_generic_unknown", "Runtime resources are incomplete.")
        status_html = self._build_resource_status_html(has_model_missing=has_model_missing, has_ffmpeg_missing=has_ffmpeg_missing)
        model_guide = self.texts.get("model_package_guide", "").strip()
        if model_guide:
            self.body_label.setText(f"{status_html}<br><br>{missing_text}<br><br>{model_guide}")
        else:
            self.body_label.setText(f"{status_html}<br><br>{missing_text}")
        self.body_label.show()
        self.upload_area.show()
        self.progress_title.show()
        self.progress_bar.show()
        self.progress_label.show()
        self.progress_title.setText(self.texts["warning_title"])
        self.progress_bar.setValue(0)
        self.progress_label.setText(error_text)
        self.go_download_button.show()
        self.go_download_button.setEnabled(download_enabled)
        self.add_files_button.show()
        self.add_files_button.setEnabled(True)
        self.remove_files_button.show()
        self.remove_files_button.setEnabled(bool(self._selected_files))
        self.clear_files_button.show()
        self.clear_files_button.setEnabled(bool(self._selected_files))
        self.import_button.show()
        self.import_button.setEnabled(bool(self._selected_files))
        self.upload_area.setEnabled(True)
        self.upload_file_list.setEnabled(True)
        self.upload_file_list.show()
        self.done_button.hide()

    def set_success_state(self, folder):
        self._downloading = False
        self.title_label.setText(self.texts["success_title"])
        self.body_label.setText(self.texts["model_download_done"])
        self.body_label.show()
        self.upload_area.hide()
        self.progress_title.show()
        self.progress_bar.show()
        self.progress_label.show()
        self.progress_title.setText(self.texts["model_download_in_progress"])
        self.progress_bar.setValue(100)
        self.progress_label.setText(self.texts["model_ready_hint"])
        self.go_download_button.hide()
        self.add_files_button.hide()
        self.remove_files_button.hide()
        self.clear_files_button.hide()
        self.import_button.hide()
        self.upload_file_list.hide()
        self.done_button.show()

    def set_import_success_state(self, message=""):
        self._downloading = False
        self.title_label.setText(self.texts["success_title"])
        self.body_label.setText(self.texts.get("model_import_success", "Model package imported successfully."))
        self.body_label.show()
        self.upload_area.hide()
        self.progress_title.show()
        self.progress_bar.show()
        self.progress_label.show()
        self.progress_title.setText(self.texts.get("model_upload_package", "Import and Parse Package"))
        self.progress_bar.setValue(100)
        self.progress_label.setText(message or self.texts.get("model_import_done_hint", "Import finished."))
        self.go_download_button.hide()
        self.add_files_button.hide()
        self.remove_files_button.hide()
        self.clear_files_button.hide()
        self.import_button.hide()
        self.upload_file_list.hide()
        self.done_button.show()

    def set_manage_state(self):
        self._downloading = False
        self.title_label.setText(self.texts["models_missing_title"])
        ready_text = self.texts.get(
            "model_manage_hint",
            "Runtime resources are ready. You can continue importing additional model packages.",
        )
        model_guide = self.texts.get("model_package_guide", "").strip()
        status_html = self._build_resource_status_html(has_model_missing=False, has_ffmpeg_missing=False)
        if model_guide:
            self.body_label.setText(f"{status_html}<br><br>{ready_text}<br><br>{model_guide}")
        else:
            self.body_label.setText(f"{status_html}<br><br>{ready_text}")
        self.body_label.show()
        self.upload_area.show()
        self.progress_title.hide()
        self.progress_bar.hide()
        self.progress_label.hide()
        self.go_download_button.show()
        self.go_download_button.setEnabled(True)
        self.add_files_button.show()
        self.add_files_button.setEnabled(True)
        self.remove_files_button.show()
        self.remove_files_button.setEnabled(bool(self._selected_files))
        self.clear_files_button.show()
        self.clear_files_button.setEnabled(bool(self._selected_files))
        self.import_button.show()
        self.import_button.setEnabled(bool(self._selected_files))
        self.upload_area.setEnabled(True)
        self.upload_file_list.setEnabled(True)
        self.upload_file_list.show()
        self.done_button.hide()

    def _select_files(self):
        selected_files, _ = QFileDialog.getOpenFileNames(
            self,
            self.texts.get("model_upload_package", "Import and Parse Package"),
            "",
            "Runtime Package (*.zip *.sha256 *.exe);;All Files (*.*)",
        )
        self._append_files(selected_files)

    def _append_files(self, paths):
        changed = False
        for raw_path in paths or []:
            path = str(raw_path or "").strip()
            if not path:
                continue
            lower = path.lower()
            if not (lower.endswith(".zip") or lower.endswith(".sha256") or lower.endswith(".exe")):
                continue
            if path in self._selected_files:
                continue
            self._selected_files.append(path)
            changed = True
        if changed:
            self._refresh_file_list()

    def _refresh_file_list(self):
        self.upload_file_list.clear()
        for path in self._selected_files:
            self.upload_file_list.addItem(QListWidgetItem(path))
        has_files = bool(self._selected_files)
        if hasattr(self, "import_button"):
            self.import_button.setEnabled(has_files)
        if hasattr(self, "remove_files_button"):
            self.remove_files_button.setEnabled(has_files)
        if hasattr(self, "clear_files_button"):
            self.clear_files_button.setEnabled(has_files)

    def _remove_selected_files(self):
        selected_rows = sorted({index.row() for index in self.upload_file_list.selectedIndexes()}, reverse=True)
        if not selected_rows:
            return
        for row in selected_rows:
            if 0 <= row < len(self._selected_files):
                self._selected_files.pop(row)
        self._refresh_file_list()

    def _clear_files(self):
        if not self._selected_files:
            return
        self._selected_files.clear()
        self._refresh_file_list()

    def _emit_import_requested(self):
        if not self._selected_files:
            return
        self.import_requested.emit(list(self._selected_files))
        self.upload_requested.emit()
        self._clear_files()

    def dragEnterEvent(self, event):
        mime_data = event.mimeData()
        if mime_data and mime_data.hasUrls():
            for url in mime_data.urls():
                local = str(url.toLocalFile() or "").strip().lower()
                if local.endswith(".zip") or local.endswith(".sha256") or local.endswith(".exe"):
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dropEvent(self, event):
        mime_data = event.mimeData()
        if not (mime_data and mime_data.hasUrls()):
            event.ignore()
            return
        dropped = [str(url.toLocalFile() or "").strip() for url in mime_data.urls()]
        self._append_files(dropped)
        event.acceptProposedAction()

    def _build_resource_status_html(self, has_model_missing, has_ffmpeg_missing):
        c = THEME_COLORS_DARK if self._is_dark else THEME_COLORS_LIGHT
        ok_color = c["SUCCESS"]
        bad_color = c["DANGER"]
        model_state = (
            self.texts.get("models_missing_generic_model", "Model resources are missing.")
            if has_model_missing
            else self.texts.get("resource_ready_state", "Ready")
        )
        ffmpeg_state = (
            self.texts.get("models_missing_generic_ffmpeg", "FFmpeg is missing.")
            if has_ffmpeg_missing
            else self.texts.get("resource_ready_state", "Ready")
        )
        model_color = bad_color if has_model_missing else ok_color
        ffmpeg_color = bad_color if has_ffmpeg_missing else ok_color
        model_label = self.texts.get("resource_model_label", "Model")
        ffmpeg_label = self.texts.get("resource_ffmpeg_label", "FFmpeg")
        return (
            f"<b>{model_label}:</b> <span style='color:{model_color};'><b>{model_state}</b></span><br>"
            f"<b>{ffmpeg_label}:</b> <span style='color:{ffmpeg_color};'><b>{ffmpeg_state}</b></span>"
        )
