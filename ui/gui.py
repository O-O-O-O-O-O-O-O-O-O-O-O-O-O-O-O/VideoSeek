import json
import os
import re
import shutil
import time
import webbrowser
from collections import deque

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import QApplication, QFileDialog, QFrame, QGraphicsOpacityEffect, QLabel, QMainWindow, QMessageBox, QScrollArea, QStackedWidget, \
    QVBoxLayout, QWidget, QHBoxLayout, QAbstractItemView, QTableWidgetItem

from src.app.config import (
    DEFAULT_CONFIG,
    get_app_version,
    get_configured_data_root,
    get_data_storage_paths,
    load_config,
    pop_migration_notice,
    save_config,
)
from src.app.app_meta import get_app_meta
from src.app.i18n import get_texts
from src.core.clip_embedding import get_engine_runtime_status, reset_engine
from src.services.about_service import get_local_about_payload
from src.services.library_service import (
    GLOBAL_INDEX_STATE_STALE,
    add_library,
    get_global_index_state,
    list_libraries,
    list_local_vector_details,
    list_partial_libraries,
    remove_library as remove_library_entry,
)
from src.services.notice_service import get_local_notice_payload
from src.services.indexing_service import list_missing_library_files
from src.services.storage_service import (
    cleanup_old_data_root as cleanup_old_data_root_service,
    cleanup_old_model_dir as cleanup_old_model_dir_service,
    migrate_app_data_root,
    migrate_model_root,
)
from src.services.model_package_service import remove_model_profile
from src.storage.config_store import get_active_model_profile, get_effective_model_dir
from src.services.query_text_service import prepare_text_query
from src.services.remix_embedding_cache import get_remix_embed_cache_dir
from src.services.remote_library_service import list_remote_link_details
from src.services.remote_link_precheck_service import precheck_remote_links
from src.storage.asset_store import load_model_metadata
from src.web.display_qr import build_qr_pixmap
from src.workflows.update_video import delete_physical_video_data
from src.utils import (
    ensure_sampling_fps_rules_open_tail,
    get_ffmpeg_status_text,
    get_configured_ffmpeg_target_path,
    get_configured_model_dir,
    normalize_sampling_fps_mode,
    normalize_sampling_fps_rules_text,
    open_folder_in_explorer,
    open_in_explorer,
    parse_sampling_fps_rules,
    resolve_sampling_fps,
    validate_sampling_fps_rules_full_coverage,
    sync_ffmpeg_path_to_config,
    sync_model_dir_to_config,
)
from src.services.version_service import get_local_version_status
from ui.app_meta_controller import AppMetaController
from ui.components import LibraryPage, LinkSearchPage, NavigationSidebar, RemixMatchPage, SearchPage, SettingsPage
from ui.dialogs import AboutDialog, AppMessageDialog, MobileBridgeDialog, NoticeDialog, ResourceTableDialog, SamplingRulesDialog
from ui.indexing_controller import IndexingController
from ui.layout import WINDOW_SIZES, apply_window_size
from ui.mobile_bridge_controller import MobileBridgeController
from ui.network_search_controller import NetworkSearchController
from ui.preview_dialog import ExportCancelledError, ExportClipWorker, PreviewDialog
from ui.preview_controller import PreviewController
from ui.runtime_resource_controller import RuntimeResourceController
from ui.search_controller import SearchController
from ui.styles import DARK_STYLE, LIGHT_STYLE
from ui.remix_compare_dialog import RemixCompareDialog
from ui.table_views import (
    build_remix_scope_checkbox_widget,
    populate_library_table,
    populate_remix_result_table,
    populate_result_table,
    remix_scope_row_checkbox,
)
from ui.workers import LocalVectorDetailsWorker, ModelPackageImportWorker, RemixMatchWorker, ThumbLoader


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.startup_cancelled = False
        self._close_when_indexing_stops = False
        self.current_img_path = None
        self.network_query_img_path = None
        self.version_info = None
        self.notice_payload = None
        self.about_payload = None
        self.models_ready = True
        self._startup_complete = False
        self._preview_dialog_cooldown_until = 0.0
        self._preview_dialog_opening = False
        self._preview_export_queue = deque()
        self._preview_export_active = {}
        self._preview_export_seq = 0
        self._preview_export_tasks = []
        self._local_vector_detail_worker = None
        self._model_package_import_worker = None
        self.remix_worker = None
        self._remix_thumb_thread = None
        self._ffmpeg_imported_with_package = False
        self._settings_dirty = False
        self._settings_loading = False
        self._settings_dirty_tracking_bound = False
        self._last_index_issues = []
        self._last_index_issue_target = None
        self._search_indexing_notice_effect = None
        self._search_indexing_notice_animation = None
        cfg = load_config()
        self._debug_tools_enabled = bool(cfg.get("show_debug_test_buttons", False))
        self.is_dark_mode = cfg.get("theme", "dark") == "dark"
        self.language = cfg.get("language", "zh")
        self.texts = get_texts(self.language)
        self.version_info = get_local_version_status(self.language)
        self.notice_payload = get_local_notice_payload(self.language)
        self.about_payload = get_local_about_payload(self.language)

        self.init_ui()
        self.app_meta_controller = AppMetaController(self)
        self.app_meta_controller.version_ready.connect(self._update_version_info)
        self.app_meta_controller.notice_ready.connect(self._update_notice_payload)
        self.app_meta_controller.about_ready.connect(self._update_about_payload)
        self.indexing_controller = IndexingController(self)
        self.indexing_controller.status_changed.connect(self._update_indexing_progress)
        self.indexing_controller.runtime_status_changed.connect(self._apply_runtime_status)
        self.indexing_controller.error_occurred.connect(self._handle_indexing_error)
        self.indexing_controller.finished.connect(self._finish_indexing)
        self.preview_controller = PreviewController(self)
        self.search_controller = SearchController(self)
        self.network_search_controller = NetworkSearchController(self)
        self.mobile_bridge_controller = MobileBridgeController(self)
        self.mobile_bridge_controller.upload_received.connect(self._handle_mobile_upload_received)
        self.mobile_bridge_controller.status_changed.connect(self._handle_mobile_bridge_status_changed)
        self.runtime_resource_controller = RuntimeResourceController(self)
        self.runtime_resource_controller.startup_cancelled.connect(self._handle_runtime_resource_exit)
        self.runtime_resource_controller.resources_ready.connect(self._finish_runtime_resource_download)
        self.runtime_resource_controller.status_changed.connect(self._apply_runtime_resource_status)
        self.media_player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.audio_output.setVolume(1.0)
        self.media_player.setAudioOutput(self.audio_output)
        self.media_player.setVideoOutput(self.video_widget)
        self._update_expand_preview_button()
        self.apply_texts()
        self._bind_settings_dirty_tracking()
        self.load_settings_values()
        self._set_settings_dirty(False)
        self._show_startup_migration_notice()
        self.check_runtime_resources(show_dialog=False)
        if self.startup_cancelled:
            return
        self.apply_theme()
        QTimer.singleShot(0, self._finish_startup_sequence)

    def init_ui(self):
        self.setWindowTitle(f"VideoSeek v{get_app_version()}")
        apply_window_size(
            self,
            WINDOW_SIZES["main"]["preferred"],
            WINDOW_SIZES["main"]["minimum"],
            WINDOW_SIZES["main"]["screen_margin"],
        )

        central = QWidget()
        central.setObjectName("AppRoot")
        self.setCentralWidget(central)

        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(12)

        self.sidebar = NavigationSidebar()
        main_layout.addWidget(self.sidebar)

        self.content = QWidget()
        self.content.setObjectName("ContentArea")
        content_layout = QVBoxLayout(self.content)
        content_layout.setContentsMargins(0, 0, 0, 0)

        self.pages = QStackedWidget()
        self.search_page = SearchPage()
        self.link_page = LinkSearchPage()
        self.remix_page = RemixMatchPage()
        self.library_page = LibraryPage()
        self.settings_page = SettingsPage()
        self.pages.addWidget(self._build_scroll_page(self.search_page))
        self.pages.addWidget(self._build_scroll_page(self.link_page))
        self.pages.addWidget(self._build_scroll_page(self.remix_page))
        self.pages.addWidget(self._build_scroll_page(self.library_page))
        self.pages.addWidget(self.settings_page)
        content_layout.addWidget(self.pages)
        main_layout.addWidget(self.content, 1)

        self.search_page.preview_placeholder.hide()
        self.video_widget = QVideoWidget()
        self.video_widget.setAttribute(Qt.WA_NativeWindow, True)
        self.video_widget.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.search_page.preview_host.mouseDoubleClickEvent = self.open_current_preview_dialog
        self.search_page.preview_host_layout.addWidget(self.video_widget)

        self.result_table = self.search_page.result_table

        self.sidebar.btn_page_search.clicked.connect(lambda: self.switch_page("search"))
        self.sidebar.btn_page_link.clicked.connect(lambda: self.switch_page("link"))
        self.sidebar.btn_page_remix.clicked.connect(lambda: self.switch_page("remix"))
        self.sidebar.btn_page_library.clicked.connect(lambda: self.switch_page("library"))
        self.sidebar.btn_page_settings.clicked.connect(lambda: self.switch_page("settings"))
        self.sidebar.btn_theme.clicked.connect(self.toggle_theme)
        self.sidebar.btn_language.clicked.connect(self.toggle_language)
        self.sidebar.btn_about.clicked.connect(self.show_about)
        self.sidebar.btn_notice.clicked.connect(self.show_notice)

        self.search_page.btn_search.clicked.connect(self.start_search)
        self.search_page.btn_clear.clicked.connect(self.clear_all_content)
        self.search_page.btn_mobile_toggle.clicked.connect(self.toggle_mobile_bridge)
        self.search_page.btn_mobile_qr.clicked.connect(self.show_mobile_bridge_qr)
        self.search_page.btn_expand_preview.clicked.connect(self.open_current_preview_dialog)
        self.search_page.btn_export_tasks.clicked.connect(self.show_preview_export_tasks)
        self.search_page.search_mode.currentIndexChanged.connect(self._save_search_mode)
        self.search_page.img_label.mousePressEvent = lambda e: self.upload_file()
        self.link_page.query_image_label.mousePressEvent = lambda e: self.upload_network_query_image()
        self.link_page.btn_build.clicked.connect(self.start_network_build)
        self.link_page.btn_import.clicked.connect(self.import_network_library)
        self.link_page.btn_export.clicked.connect(self.export_network_library)
        self.link_page.btn_run.clicked.connect(self.start_network_search)
        self.link_page.btn_clear.clicked.connect(self.clear_link_search_content)
        self.link_page.btn_link_details.clicked.connect(self.show_network_link_details)
        self.link_page.btn_open_cache.clicked.connect(self.open_network_download_cache_folder)

        self.remix_page.btn_browse_mix.clicked.connect(self._browse_remix_mix_video)
        self.remix_page.btn_run.clicked.connect(self.start_remix_match)
        self.remix_page.btn_stop.clicked.connect(self.stop_remix_match)
        self.remix_page.btn_clear.clicked.connect(self.clear_remix_match_ui)
        self.remix_page.btn_scope_all.clicked.connect(self._remix_scope_select_all)
        self.remix_page.btn_scope_none.clicked.connect(self._remix_scope_select_none)
        self.remix_page.btn_open_remix_cache.clicked.connect(self.open_remix_embed_cache_folder)
        self.remix_page.scope_table.cellClicked.connect(self._on_remix_scope_table_cell_clicked)

        self.library_page.btn_add_lib.clicked.connect(self.select_video_folder)
        self.library_page.btn_sync_db.clicked.connect(self.start_update_index)
        self.library_page.btn_stop_index.clicked.connect(self.stop_update_index)
        self.library_page.btn_index_issues.clicked.connect(self.show_last_index_issue_details)
        self.library_page.btn_cleanup_missing.clicked.connect(self.cleanup_missing_library_vectors)
        self.library_page.btn_vector_details.clicked.connect(self.show_local_vector_details)
        self.library_page.btn_debug_gpu_oom.clicked.connect(self.start_debug_gpu_oom)
        self.library_page.btn_debug_system_oom.clicked.connect(self.start_debug_system_oom)

        self.settings_page.btn_save.clicked.connect(self.save_settings)
        self.settings_page.btn_reset.clicked.connect(self.reset_settings)
        self.settings_page.btn_edit_sampling_rules.clicked.connect(self._open_sampling_rules_dialog)
        self.settings_page.btn_browse_data_root.clicked.connect(self._browse_data_root)
        self.settings_page.btn_browse_ffmpeg_path.clicked.connect(self._browse_ffmpeg_path)
        self.settings_page.btn_browse_model_dir.clicked.connect(self._browse_model_dir)
        self.settings_page.btn_migrate_model_dir.clicked.connect(self._migrate_model_root)
        self.settings_page.btn_download_runtime_resources.clicked.connect(self.open_runtime_resource_dialog)
        self.settings_page.btn_remove_model_profile.clicked.connect(self.remove_current_model_profile)
        self.settings_page.input_active_model_profile.currentIndexChanged.connect(self._on_active_model_profile_changed)
        self.settings_page.btn_show_runtime_diagnostics.clicked.connect(self.show_runtime_diagnostics)
        self.settings_page.btn_cleanup_old_data_root.clicked.connect(self.cleanup_old_data_root)
        self.settings_page.btn_cleanup_old_model_dir.clicked.connect(self.cleanup_old_model_dir)

        self.setAcceptDrops(True)
        for page in (self.search_page, self.link_page, self.remix_page, self.library_page, self.settings_page):
            page.header.runtime_banner_action.clicked.connect(self.open_runtime_resource_dialog)

    def _build_scroll_page(self, page_widget):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(page_widget)
        return scroll

    def switch_page(self, page_name):
        mapping = {"search": 0, "link": 1, "remix": 2, "library": 3, "settings": 4}
        prev_idx = self.pages.currentIndex()
        next_idx = mapping[page_name]
        self.pages.setCurrentIndex(next_idx)
        self.sidebar.set_current_page(page_name)
        if prev_idx == mapping["search"] and next_idx != mapping["search"]:
            self.preview_controller.stop_preview()
            dlg = getattr(self, "_preview_dialog", None)
            if dlg is not None:
                dlg.dismiss_for_page_switch()
        if page_name == "remix":
            self._refresh_remix_scope_table()

    def _update_version_info(self, version_info):
        self.version_info = version_info
        self.apply_texts()

    def _update_notice_payload(self, notice_payload):
        self.notice_payload = notice_payload

    def _update_about_payload(self, about_payload):
        self.about_payload = about_payload

    def apply_texts(self):
        self.texts = get_texts(self.language)
        t = self.texts
        try:
            config = load_config()
        except Exception as exc:
            self.show_error_dialog(t["settings_load_failed"], exc)
            return

        self.setWindowTitle(f"{t['app_name']} v{get_app_version()}")
        self.sidebar.title.setText(t["app_name"])
        self.sidebar.subtitle.setText(t["app_subtitle"])
        self.sidebar.hero_tag.setText(t["hero_tag"])
        self.sidebar.hero_title.setText(t["hero_title"])
        self.sidebar.hero_body.setText(t["hero_body"])
        self.sidebar.btn_page_search.setText(t["nav_search"])
        self.sidebar.btn_page_link.setText(t["nav_link"])
        self.sidebar.btn_page_remix.setText(t["nav_remix"])
        self.sidebar.btn_page_library.setText(t["nav_library"])
        self.sidebar.btn_page_settings.setText(t["nav_settings"])
        self.sidebar.btn_notice.setText(t["notice_short"])
        if self.version_info and self.version_info.get("has_update"):
            self.sidebar.btn_about.setText(t["about_short_update"])
            self.sidebar.btn_about.setObjectName("UpdateButton")
        else:
            self.sidebar.btn_about.setText(t["about_short"])
            self.sidebar.btn_about.setObjectName("SecondaryButton")
        self.sidebar.btn_about.style().unpolish(self.sidebar.btn_about)
        self.sidebar.btn_about.style().polish(self.sidebar.btn_about)
        self.sidebar.btn_about.update()
        self.sidebar.btn_language.setText(t["language_toggle"])
        self.sidebar.btn_theme.setText(t["theme_light"] if self.is_dark_mode else t["theme_dark"])
        self.sidebar.runtime_hint.hide()
        self.sidebar.runtime_hint.setToolTip("")

        self.search_page.header.title.setText(t["search_page_title"])
        self.search_page.header.subtitle.setText(t["search_page_desc"])
        self.search_page.controls_title.setText(t["controls_label"])
        self.search_page.controls_hint.setText(t["controls_hint"])
        current_mode = self.search_page.search_mode.currentData()
        self.search_page.search_mode_label.setText(t["setting_search_mode"])
        self.search_page.search_mode.blockSignals(True)
        self.search_page.search_mode.clear()
        self.search_page.search_mode.addItem(t["setting_search_mode_frame"], "frame")
        self.search_page.search_mode.addItem(t["setting_search_mode_chunk"], "chunk")
        self.search_page.search_mode.setCurrentIndex(1 if current_mode == "chunk" else 0)
        self.search_page.search_mode.blockSignals(False)
        self.search_page.session_title.setText(t["workspace_label"])
        self.search_page.indexing_notice_text.setText(t.get("search_during_indexing_hint", ""))
        self._refresh_search_session_hint()
        self.search_page.preview_title.setText(t["preview_panel"])
        self.search_page.btn_expand_preview.setText(t.get("preview_expand", "放大预览"))
        self.search_page.results_title.setText(t["results_panel"])
        self.search_page.btn_export_tasks.setText(t.get("preview_export_tasks", "Export Tasks"))
        self._update_expand_preview_button()
        self.search_page.text_search.setPlaceholderText(t["search_placeholder"])
        self.search_page.mobile_toggle_label.setText(t.get("mobile_bridge_toggle_label", t["mobile_bridge_start"]))
        self.search_page.btn_mobile_toggle.setText(self._mobile_bridge_toggle_text(self.mobile_bridge_controller.is_running(), texts=t))
        self.search_page.btn_mobile_toggle.setToolTip(
            t["mobile_bridge_stop"] if self.mobile_bridge_controller.is_running() else t["mobile_bridge_start"]
        )
        self.search_page.btn_mobile_toggle.setChecked(self.mobile_bridge_controller.is_running())
        self.search_page.btn_mobile_qr.setText(t["mobile_bridge_qr"])
        self.search_page.btn_mobile_qr.setEnabled(self.mobile_bridge_controller.is_running())
        self.search_page.btn_search.setText(t["search"])
        self.search_page.btn_clear.setText(t["clear"])
        self.search_page.preview_placeholder.setText(t["preview_placeholder"])
        self.result_table.setHorizontalHeaderLabels(t["result_headers"])

        self.link_page.header.title.setText(t["link_page_title"])
        self.link_page.header.subtitle.setText(t["link_page_desc"])
        self.link_page.notice_body.setText(t["network_notice_body"])
        self.link_page.build_title.setText(t.get("network_build_section_title", t["controls_label"]))
        self.link_page.build_hint.setText(t.get("network_build_section_hint", t["controls_hint"]))
        self.link_page.search_title.setText(t.get("network_search_section_title", t["link_controls_label"]))
        self.link_page.search_hint.setText(t.get("network_search_section_hint", t["link_controls_hint"]))
        self.link_page.mode_label.show()
        self.link_page.mode_combo.show()
        self.link_page.mode_label.setText(t["network_build_mode"])
        self.link_page.mode_combo.blockSignals(True)
        self.link_page.mode_combo.clear()
        self.link_page.mode_combo.addItem(t["link_mode_download"], "download")
        self.link_page.mode_combo.addItem(t["link_mode_stream"], "stream")
        self.link_page.mode_combo.blockSignals(False)
        self.link_page.build_links_input.setPlaceholderText(t["network_link_editor_placeholder"])
        self.link_page.input_link.setPlaceholderText(t["link_input_placeholder"])
        self.link_page.query_image_label.setText(t["network_image_preview_hint"])
        self.link_page.btn_build.setText(t["network_build"])
        self.link_page.btn_import.setText(t["network_import"])
        self.link_page.btn_export.setText(t["network_export"])
        self.link_page.btn_link_details.setText(t["network_links_detail"])
        self.link_page.btn_open_cache.setText(t["network_open_cache"])
        self.link_page.btn_run.setText(t["link_run"])
        self.link_page.btn_clear.setText(t["clear"])
        self.link_page.results_title.setText(t["link_results_panel"])
        self.link_page.result_table.setHorizontalHeaderLabels(t["network_result_headers"])

        self.remix_page.header.title.setText(t["remix_page_title"])
        self.remix_page.header.subtitle.setText(t["remix_page_desc"])
        self.remix_page.mix_label.setText(t["remix_mix_video"])
        self.remix_page.section_params_title.setText(t.get("remix_section_params", ""))
        self.remix_page.mix_hint.setText(t["remix_mix_hint"])
        self.remix_page.btn_browse_mix.setText(t["remix_browse"])
        self.remix_page.lbl_sample_fps.setText(t["remix_sample_fps"])
        self.remix_page.lbl_sample_fps.setToolTip(t.get("remix_sample_fps_tip", ""))
        self.remix_page.input_sample_fps.setToolTip(t.get("remix_sample_fps_tip", ""))
        self.remix_page.lbl_score.setText(t["remix_score_threshold"])
        self.remix_page.lbl_score.setToolTip(t.get("remix_score_threshold_tip", ""))
        self.remix_page.input_score_threshold.setToolTip(t.get("remix_score_threshold_tip", ""))
        self.remix_page.lbl_gap.setText(t["remix_merge_gap"])
        self.remix_page.lbl_gap.setToolTip(t.get("remix_merge_gap_tip", ""))
        self.remix_page.input_merge_gap.setToolTip(t.get("remix_merge_gap_tip", ""))
        self.remix_page.lbl_min_seg.setText(t["remix_min_segment"])
        self.remix_page.lbl_min_seg.setToolTip(t.get("remix_min_segment_tip", ""))
        self.remix_page.input_min_segment.setToolTip(t.get("remix_min_segment_tip", ""))
        self.remix_page.lbl_remix_cluster.setText(t["remix_cluster_gap"])
        self.remix_page.lbl_remix_cluster.setToolTip(t.get("remix_cluster_gap_tip", ""))
        self.remix_page.input_remix_cluster_gap.setToolTip(t.get("remix_cluster_gap_tip", ""))
        self.remix_page.lbl_faiss_top_k.setText(t["remix_faiss_top_k"])
        self.remix_page.lbl_faiss_top_k.setToolTip(t.get("remix_faiss_top_k_tip", ""))
        self.remix_page.input_faiss_top_k.setToolTip(t.get("remix_faiss_top_k_tip", ""))
        self.remix_page.lbl_speed_min.setText(t["remix_speed_min"])
        self.remix_page.lbl_speed_min.setToolTip(t.get("remix_speed_min_tip", ""))
        self.remix_page.input_speed_min.setToolTip(t.get("remix_speed_min_tip", ""))
        self.remix_page.lbl_speed_max.setText(t["remix_speed_max"])
        self.remix_page.lbl_speed_max.setToolTip(t.get("remix_speed_max_tip", ""))
        self.remix_page.input_speed_max.setToolTip(t.get("remix_speed_max_tip", ""))
        self.remix_page.lbl_ransac_iters.setText(t["remix_ransac_iters"])
        self.remix_page.lbl_ransac_iters.setToolTip(t.get("remix_ransac_iters_tip", ""))
        self.remix_page.input_ransac_iters.setToolTip(t.get("remix_ransac_iters_tip", ""))
        self.remix_page.lbl_min_line_pts.setText(t["remix_min_line_points"])
        self.remix_page.lbl_min_line_pts.setToolTip(t.get("remix_min_line_points_tip", ""))
        self.remix_page.input_min_line_points.setToolTip(t.get("remix_min_line_points_tip", ""))
        self.remix_page.remix_params_guide.setText(t.get("remix_params_guide", ""))
        self.remix_page.btn_open_remix_cache.setText(t.get("remix_open_cache_dir", t.get("network_open_cache", "")))
        self.remix_page.btn_open_remix_cache.setToolTip(t.get("remix_open_cache_dir_tip", ""))
        self.remix_page.scope_title.setText(t["remix_scope_title"])
        self.remix_page.radio_scope_all.setText(t["remix_scope_all"])
        self.remix_page.radio_scope_restricted.setText(t["remix_scope_restricted"])
        self.remix_page.scope_table_hint.setText(t["remix_scope_table_hint"])
        self.remix_page.btn_scope_all.setText(t["remix_select_all"])
        self.remix_page.btn_scope_none.setText(t["remix_select_none"])
        self.remix_page.btn_run.setText(t["remix_run"])
        self.remix_page.btn_stop.setText(t["remix_stop"])
        self.remix_page.btn_clear.setText(t["remix_clear"])
        self.remix_page.results_title.setText(t["remix_results_title"])
        rh = t["remix_result_headers"]
        self.remix_page.result_table.setColumnCount(len(rh))
        self.remix_page.result_table.setHorizontalHeaderLabels(rh)

        self.library_page.header.title.setText(t["library_page_title"])
        self.library_page.header.subtitle.setText(t["library_page_desc"])
        self.library_page.table_title.setText(t["library_table_title"])
        self.library_page.btn_add_lib.setText(t["add_folder"])
        self.library_page.btn_sync_db.setText(t["update_index"])
        self.library_page.btn_stop_index.setText(t["stop"])
        self.library_page.btn_index_issues.setText(t["index_issues_button"])
        self.library_page.btn_cleanup_missing.setText(t["cleanup_missing_vectors"])
        self.library_page.btn_vector_details.setText(t["library_vectors_detail"])
        self.library_page.btn_debug_gpu_oom.setText(t["debug_gpu_oom"])
        self.library_page.btn_debug_system_oom.setText(t["debug_system_oom"])
        self.library_page.btn_debug_gpu_oom.setVisible(getattr(self, "_debug_tools_enabled", False))
        self.library_page.btn_debug_system_oom.setVisible(getattr(self, "_debug_tools_enabled", False))
        self._apply_index_issue_button_state(bool(self._last_index_issues))

        self.settings_page.header.title.setText(t["settings_page_title"])
        self.settings_page.header.subtitle.setText(t["settings_page_desc"])
        self.settings_page.general_title.setText(t["settings_group_title"])
        self.settings_page.btn_save.setText(t["save_settings"])
        self.settings_page.btn_reset.setText(t["reset_settings"])
        self.settings_page.configure_form_labels(t)
        self._update_inference_backend_hint()
        self._refresh_pending_cleanup_actions(config)

        if not self.current_img_path and not self.search_page.img_label.pixmap():
            self.search_page.img_label.setText(t["image_drop_hint"])

        self.search_page.lbl_status.setText(t["ready"])
        self.link_page.lbl_build_status.setText(t["ready"])
        self.link_page.lbl_search_status.setText(t["ready"])
        self.remix_page.lbl_status.setText(t["ready"])
        self.library_page.lbl_status.setText(t["ready"])
        self.settings_page.lbl_status.setText(t["settings_hint"])
        self._bind_sampling_preview_signals()
        self._update_sampling_preview()
        if self._startup_complete:
            self.refresh_library_table()

    def _finish_startup_sequence(self):
        synced_model_dir = sync_model_dir_to_config()
        synced_path = sync_ffmpeg_path_to_config()
        if synced_model_dir:
            self.settings_page.input_model_dir.setText(synced_model_dir)
        if synced_path:
            self.settings_page.input_ffmpeg_path.setText(synced_path)
        self._startup_complete = True
        self.refresh_library_table()
        self._prompt_resume_partial_indexing()
        self.app_meta_controller.refresh(self.language)

    def load_settings_values(self):
        self._settings_loading = True
        try:
            config = load_config()
        except Exception as exc:
            self._settings_loading = False
            self.show_error_dialog(self.texts["settings_load_failed"], exc)
            return
        self._populate_model_profile_options(config)
        sampling_fps_mode = normalize_sampling_fps_mode(
            config.get("sampling_fps_mode", DEFAULT_CONFIG["sampling_fps_mode"])
        )
        self.settings_page.set_sampling_fps_mode(sampling_fps_mode)
        self.settings_page.input_fps.setValue(config.get("fps", DEFAULT_CONFIG["fps"]))
        sampling_rules = normalize_sampling_fps_rules_text(
            config.get("sampling_fps_rules", DEFAULT_CONFIG["sampling_fps_rules"])
        )
        if sampling_fps_mode == "dynamic" and not sampling_rules:
            sampling_rules = DEFAULT_CONFIG["sampling_fps_rules"]
        self.settings_page.set_sampling_fps_rules_text(sampling_rules)
        self.settings_page.input_top_k.setValue(config.get("search_top_k", DEFAULT_CONFIG["search_top_k"]))
        frame_neighbor_rerank_enabled = bool(
            config.get(
                "frame_neighbor_rerank_enabled",
                DEFAULT_CONFIG["frame_neighbor_rerank_enabled"],
            )
        )
        self.settings_page.input_frame_neighbor_rerank_enabled.setCurrentIndex(1 if frame_neighbor_rerank_enabled else 0)
        self.settings_page.input_frame_neighbor_rerank_top_n.setValue(
            int(
                config.get(
                    "frame_neighbor_rerank_top_n",
                    DEFAULT_CONFIG["frame_neighbor_rerank_top_n"],
                )
            )
        )
        self.settings_page.input_frame_neighbor_rerank_window.setValue(
            int(
                config.get(
                    "frame_neighbor_rerank_window",
                    DEFAULT_CONFIG["frame_neighbor_rerank_window"],
                )
            )
        )
        self.settings_page.input_preview_seconds.setValue(
            config.get("preview_seconds", DEFAULT_CONFIG["preview_seconds"])
        )
        self.settings_page.input_preview_width.setValue(
            config.get("preview_width", DEFAULT_CONFIG["preview_width"])
        )
        self.settings_page.input_preview_height.setValue(
            config.get("preview_height", DEFAULT_CONFIG["preview_height"])
        )
        self.settings_page.input_thumb_width.setValue(
            config.get("thumb_width", DEFAULT_CONFIG["thumb_width"])
        )
        self.settings_page.input_thumb_height.setValue(
            config.get("thumb_height", DEFAULT_CONFIG["thumb_height"])
        )
        self.settings_page.input_remote_max_frames.setValue(
            int(config.get("remote_max_frames", DEFAULT_CONFIG["remote_max_frames"]))
        )
        self.settings_page.input_embedding_batch_size.setValue(
            int(config.get("embedding_batch_size", DEFAULT_CONFIG["embedding_batch_size"]))
        )
        search_mode = config.get("search_mode", DEFAULT_CONFIG["search_mode"])
        self.search_page.search_mode.setCurrentIndex(0 if search_mode == "frame" else 1)
        self.settings_page.input_similarity_threshold.setValue(
            config.get("similarity_threshold", DEFAULT_CONFIG["similarity_threshold"])
        )
        self.settings_page.input_max_chunk_duration.setValue(
            config.get("max_chunk_duration", DEFAULT_CONFIG["max_chunk_duration"])
        )
        self.settings_page.input_min_chunk_size.setValue(
            config.get("min_chunk_size", DEFAULT_CONFIG["min_chunk_size"])
        )
        chunk_similarity_mode = config.get("chunk_similarity_mode", DEFAULT_CONFIG["chunk_similarity_mode"])
        self.settings_page.input_chunk_similarity_mode.setCurrentIndex(
            0 if chunk_similarity_mode == "chunk" else 1
        )
        prefer_gpu = config.get("prefer_gpu", DEFAULT_CONFIG["prefer_gpu"])
        self.settings_page.input_prefer_gpu.setCurrentIndex(0 if prefer_gpu else 1)
        gpu_probe_unknown_keep_gpu = bool(
            config.get("gpu_probe_unknown_keep_gpu", DEFAULT_CONFIG["gpu_probe_unknown_keep_gpu"])
        )
        self.settings_page.input_gpu_probe_unknown_keep_gpu.setCurrentIndex(1 if gpu_probe_unknown_keep_gpu else 0)
        auto_cleanup_missing_files = bool(
            config.get("auto_cleanup_missing_files", DEFAULT_CONFIG["auto_cleanup_missing_files"])
        )
        self.settings_page.input_auto_cleanup_missing_files.setCurrentIndex(1 if auto_cleanup_missing_files else 0)
        self.settings_page.input_data_root.setText(get_configured_data_root(config))
        self.settings_page.input_ffmpeg_path.setText(config.get("ffmpeg_path", DEFAULT_CONFIG["ffmpeg_path"]))
        self.settings_page.input_model_dir.setText(config.get("model_dir", DEFAULT_CONFIG["model_dir"]))
        self._update_inference_backend_hint()
        self._update_sampling_rules_feedback()
        self._update_sampling_preview()
        self._refresh_pending_cleanup_actions(config)
        self._settings_loading = False
        self._set_settings_dirty(False)

    def _bind_settings_dirty_tracking(self):
        if self._settings_dirty_tracking_bound:
            return
        self._settings_dirty_tracking_bound = True
        editors = [
            self.settings_page.input_fps,
            self.settings_page.input_top_k,
            self.settings_page.input_frame_neighbor_rerank_enabled,
            self.settings_page.input_frame_neighbor_rerank_top_n,
            self.settings_page.input_frame_neighbor_rerank_window,
            self.settings_page.input_preview_seconds,
            self.settings_page.input_preview_width,
            self.settings_page.input_preview_height,
            self.settings_page.input_thumb_width,
            self.settings_page.input_thumb_height,
            self.settings_page.input_remote_max_frames,
            self.settings_page.input_embedding_batch_size,
            self.settings_page.input_similarity_threshold,
            self.settings_page.input_max_chunk_duration,
            self.settings_page.input_min_chunk_size,
            self.settings_page.input_chunk_similarity_mode,
            self.settings_page.input_prefer_gpu,
            self.settings_page.input_gpu_probe_unknown_keep_gpu,
            self.settings_page.input_auto_cleanup_missing_files,
            self.settings_page.input_active_model_profile,
            self.settings_page.input_data_root,
            self.settings_page.input_ffmpeg_path,
            self.settings_page.input_model_dir,
            self.settings_page.input_sampling_fps_mode,
            self.settings_page.input_sampling_fps_rules,
        ]
        for widget in editors:
            if hasattr(widget, "valueChanged"):
                widget.valueChanged.connect(self._mark_settings_dirty)
            elif hasattr(widget, "currentIndexChanged"):
                widget.currentIndexChanged.connect(self._mark_settings_dirty)
            elif hasattr(widget, "textChanged"):
                widget.textChanged.connect(self._mark_settings_dirty)

    def _mark_settings_dirty(self, *_args):
        if self._settings_loading:
            return
        self._set_settings_dirty(True)

    def _set_settings_dirty(self, dirty):
        dirty = bool(dirty)
        self._settings_dirty = dirty
        btn = self.settings_page.btn_save
        btn.setEnabled(dirty)
        target_object = "PrimaryButton" if dirty else "GhostButton"
        if btn.objectName() != target_object:
            btn.setObjectName(target_object)
            style = btn.style()
            style.unpolish(btn)
            style.polish(btn)
            btn.update()

    def _populate_model_profile_options(self, config):
        models = dict(config.get("models") or {})
        profiles = [item for item in models.get("profiles", []) if isinstance(item, dict)]
        active_profile_id = str(models.get("active_profile", "") or "").strip()
        combo = self.settings_page.input_active_model_profile
        combo.blockSignals(True)
        combo.clear()
        for profile in profiles:
            profile_id = str(profile.get("id", "") or "").strip()
            if not profile_id:
                continue
            runtime = dict(profile.get("runtime") or {})
            provider = str(profile.get("provider", "") or "").strip()
            provider_dir = "openai-clip" if provider == "clip_onnx" else provider.replace("_", "-")
            model_variant = str(runtime.get("model_variant", "") or profile.get("model_variant", "") or "").strip()
            if not model_variant:
                model_variant = "vit-base-patch32"
            display_name = f"{provider_dir} / {model_variant}"
            combo.addItem(display_name, profile_id)
        if combo.count() == 0:
            combo.addItem(
                self.texts.get("model_profile_none", "No model imported"),
                "",
            )
            active_profile_id = ""
        index = combo.findData(active_profile_id)
        combo.setCurrentIndex(0 if index < 0 else index)
        combo.blockSignals(False)

    def _on_active_model_profile_changed(self, _index):
        config = load_config()
        selected_profile_id = str(self.settings_page.input_active_model_profile.currentData() or "").strip()
        models = dict(config.get("models") or {})
        profiles = [item for item in models.get("profiles", []) if isinstance(item, dict)]
        for profile in profiles:
            if str(profile.get("id", "") or "").strip() != selected_profile_id:
                continue
            runtime = dict(profile.get("runtime") or {})
            prefer_gpu = bool(runtime.get("prefer_gpu", DEFAULT_CONFIG["prefer_gpu"]))
            model_dir = str(runtime.get("model_dir", "") or "").strip() or config.get("model_dir", DEFAULT_CONFIG["model_dir"])
            self.settings_page.input_prefer_gpu.setCurrentIndex(0 if prefer_gpu else 1)
            self.settings_page.input_model_dir.setText(model_dir)
            break

    def save_settings(self):
        try:
            config = load_config()
            current_data_root = get_configured_data_root(config)
            previous_fps = config.get("fps", DEFAULT_CONFIG["fps"] )
            previous_sampling_fps_mode = normalize_sampling_fps_mode(
                config.get("sampling_fps_mode", DEFAULT_CONFIG["sampling_fps_mode"])
            )
            previous_sampling_fps_rules = normalize_sampling_fps_rules_text(
                config.get("sampling_fps_rules", DEFAULT_CONFIG["sampling_fps_rules"])
            )
            previous_similarity_threshold = float(
                config.get("similarity_threshold", DEFAULT_CONFIG["similarity_threshold"])
            )
            previous_embedding_batch_size = int(
                config.get("embedding_batch_size", DEFAULT_CONFIG["embedding_batch_size"])
            )
            previous_max_chunk_duration = float(
                config.get("max_chunk_duration", DEFAULT_CONFIG["max_chunk_duration"])
            )
            previous_min_chunk_size = int(config.get("min_chunk_size", DEFAULT_CONFIG["min_chunk_size"]))
            previous_chunk_similarity_mode = str(
                config.get("chunk_similarity_mode", DEFAULT_CONFIG["chunk_similarity_mode"])
            )
            previous_prefer_gpu = config.get("prefer_gpu", DEFAULT_CONFIG["prefer_gpu"])
            previous_gpu_probe_unknown_keep_gpu = bool(
                config.get("gpu_probe_unknown_keep_gpu", DEFAULT_CONFIG["gpu_probe_unknown_keep_gpu"])
            )
            previous_models = dict(config.get("models") or {})
            previous_active_profile_id = str(previous_models.get("active_profile", "") or "").strip()
            try:
                previous_effective_model_dir = str(get_effective_model_dir(config=config) or "").strip()
            except Exception:
                previous_effective_model_dir = ""
            new_fps = self.settings_page.input_fps.value()
            new_sampling_fps_mode = normalize_sampling_fps_mode(
                self.settings_page.get_sampling_fps_mode()
            )
            user_sampling_fps_rules = normalize_sampling_fps_rules_text(
                self.settings_page.get_sampling_fps_rules_text()
            )
            new_sampling_fps_rules = user_sampling_fps_rules
            if new_sampling_fps_mode == "dynamic":
                new_sampling_fps_rules = ensure_sampling_fps_rules_open_tail(new_sampling_fps_rules, default_tail_fps=0.5)
            auto_tail_rule = ""
            if (
                new_sampling_fps_mode == "dynamic"
                and user_sampling_fps_rules
                and new_sampling_fps_rules != user_sampling_fps_rules
            ):
                auto_tail_rule = new_sampling_fps_rules[len(user_sampling_fps_rules):].lstrip(" ;")
            rules_valid, _ = validate_sampling_fps_rules_full_coverage(new_sampling_fps_rules)
            if new_sampling_fps_mode == "dynamic" and new_sampling_fps_rules and not rules_valid:
                self.settings_page.lbl_status.setText(self.texts["setting_sampling_fps_rules_invalid"] )
                self.show_info_dialog(
                    self.texts["error_title"],
                    self.texts["setting_sampling_fps_rules_invalid"],
                    kind="warning",
                )
                return
            new_similarity_threshold = float(self.settings_page.input_similarity_threshold.value())
            new_embedding_batch_size = int(self.settings_page.input_embedding_batch_size.value())
            new_max_chunk_duration = float(self.settings_page.input_max_chunk_duration.value())
            new_min_chunk_size = int(self.settings_page.input_min_chunk_size.value())
            new_chunk_similarity_mode = str(self.settings_page.input_chunk_similarity_mode.currentData())
            config["fps"] = new_fps
            config["sampling_fps_mode"] = new_sampling_fps_mode
            # Preserve the user's rule set even while fixed mode is active so
            # switching back to dynamic mode does not silently drop it.
            config["sampling_fps_rules"] = new_sampling_fps_rules
            config["search_top_k"] = self.settings_page.input_top_k.value()
            config["frame_neighbor_rerank_enabled"] = bool(
                self.settings_page.input_frame_neighbor_rerank_enabled.currentData()
            )
            config["frame_neighbor_rerank_top_n"] = int(
                self.settings_page.input_frame_neighbor_rerank_top_n.value()
            )
            config["frame_neighbor_rerank_window"] = int(
                self.settings_page.input_frame_neighbor_rerank_window.value()
            )
            config["preview_seconds"] = self.settings_page.input_preview_seconds.value()
            config["preview_width"] = self.settings_page.input_preview_width.value()
            config["preview_height"] = self.settings_page.input_preview_height.value()
            config["thumb_width"] = self.settings_page.input_thumb_width.value()
            config["thumb_height"] = self.settings_page.input_thumb_height.value()
            config["remote_max_frames"] = int(self.settings_page.input_remote_max_frames.value())
            config["embedding_batch_size"] = new_embedding_batch_size
            config["similarity_threshold"] = new_similarity_threshold
            config["max_chunk_duration"] = new_max_chunk_duration
            config["min_chunk_size"] = new_min_chunk_size
            config["chunk_similarity_mode"] = new_chunk_similarity_mode
            config["prefer_gpu"] = bool(self.settings_page.input_prefer_gpu.currentData())
            config["gpu_probe_unknown_keep_gpu"] = bool(
                self.settings_page.input_gpu_probe_unknown_keep_gpu.currentData()
            )
            config["auto_cleanup_missing_files"] = bool(
                self.settings_page.input_auto_cleanup_missing_files.currentData()
            )
            selected_profile_id = str(self.settings_page.input_active_model_profile.currentData() or "").strip()
            models = config.get("models")
            if not isinstance(models, dict):
                models = {}
                config["models"] = models
            profiles = models.get("profiles")
            if not isinstance(profiles, list):
                profiles = []
                models["profiles"] = profiles
            if selected_profile_id:
                models["active_profile"] = selected_profile_id
            requested_data_root = self._normalize_requested_data_root(self.settings_page.input_data_root.text())
            config["ffmpeg_path"] = self.settings_page.input_ffmpeg_path.text().strip()
            config["model_dir"] = self.settings_page.input_model_dir.text().strip() or DEFAULT_CONFIG["model_dir"]
            if selected_profile_id:
                for idx, item in enumerate(profiles):
                    if not isinstance(item, dict):
                        continue
                    if str(item.get("id", "") or "").strip() != selected_profile_id:
                        continue
                    updated_item = dict(item)
                    runtime = dict(updated_item.get("runtime") or {})
                    runtime["prefer_gpu"] = config["prefer_gpu"]
                    runtime["model_dir"] = config["model_dir"]
                    updated_item["runtime"] = runtime
                    profiles[idx] = updated_item
                    break
            try:
                new_effective_model_dir = str(get_effective_model_dir(config=config) or "").strip()
            except Exception:
                new_effective_model_dir = ""
            profile_switched = bool(selected_profile_id) and selected_profile_id != previous_active_profile_id
            effective_model_dir_changed = (
                os.path.normcase(os.path.normpath(previous_effective_model_dir or ""))
                != os.path.normcase(os.path.normpath(new_effective_model_dir or ""))
            )
            migration_result = self._migrate_data_root_if_needed(current_data_root, requested_data_root)
            if migration_result is False:
                return
            config["data_root"] = requested_data_root
            if isinstance(migration_result, dict) and migration_result.get("migrated"):
                config["pending_cleanup_data_root"] = migration_result.get("old_data_root", "")
            save_config(config)
            self._refresh_pending_cleanup_actions(config)
            self.settings_page.input_data_root.setText(get_configured_data_root(config))
            effective_rules = new_sampling_fps_rules if new_sampling_fps_mode == "dynamic" else ""
            fps_changed = (
                previous_fps != new_fps
                or previous_sampling_fps_mode != new_sampling_fps_mode
                or previous_sampling_fps_rules != effective_rules
            )
            chunk_changed = (
                previous_similarity_threshold != new_similarity_threshold
                or previous_max_chunk_duration != new_max_chunk_duration
                or previous_min_chunk_size != new_min_chunk_size
                or previous_chunk_similarity_mode != new_chunk_similarity_mode
            )
            if (
                previous_prefer_gpu != config["prefer_gpu"]
                or previous_gpu_probe_unknown_keep_gpu != config["gpu_probe_unknown_keep_gpu"]
                or previous_embedding_batch_size != config["embedding_batch_size"]
                or profile_switched
                or effective_model_dir_changed
            ):
                reset_engine()
            if not config["model_dir"]:
                synced_model_dir = sync_model_dir_to_config()
                if synced_model_dir:
                    self.settings_page.input_model_dir.setText(synced_model_dir)
            if not config["ffmpeg_path"]:
                synced_path = sync_ffmpeg_path_to_config()
                if synced_path:
                    self.settings_page.input_ffmpeg_path.setText(synced_path)
            self.check_runtime_resources(show_dialog=False)
            self._update_inference_backend_hint()
            self._update_sampling_preview()
            if profile_switched:
                self.refresh_library_table()
            save_message = self._build_settings_save_message(fps_changed, chunk_changed)
            if auto_tail_rule:
                save_message = f"{save_message}\n\n{self.texts['sampling_rules_auto_tail_added'].format(rule=auto_tail_rule)}"
            if profile_switched:
                save_message = f"{save_message}\n\n{self.texts['model_profile_switched_rebuild_hint']}"
            if isinstance(migration_result, dict) and migration_result.get("migrated"):
                save_message = f"{save_message}\n\n{self._build_data_root_migration_message(migration_result, requested_data_root)}"
            self.settings_page.lbl_status.setText(save_message)
            self.show_info_dialog(self.texts["success_title"], save_message, kind="success")
            self._set_settings_dirty(False)
        except Exception as exc:
            self.show_error_dialog(self.texts["settings_save_failed"], exc)

    def reset_settings(self):
        try:
            if not self.show_confirm_dialog(
                self.texts["confirm_title"],
                self.texts.get("reset_settings_confirm", "Restore parameter defaults now?"),
            ):
                self.settings_page.lbl_status.setText(self.texts["settings_hint"])
                return
            config = load_config()
            current_data_root = get_configured_data_root(config)
            previous_prefer_gpu = config.get("prefer_gpu", DEFAULT_CONFIG["prefer_gpu"])
            preserved_values = {
                "theme": config.get("theme"),
                "language": config.get("language"),
                "data_root": config.get("data_root"),
                "model_dir": config.get("model_dir"),
                "ffmpeg_path": config.get("ffmpeg_path"),
                "models": config.get("models"),
                "pending_cleanup_data_root": config.get("pending_cleanup_data_root"),
                "pending_cleanup_model_dir": config.get("pending_cleanup_model_dir"),
            }
            for key, value in DEFAULT_CONFIG.items():
                if key in {
                    "theme",
                    "language",
                    "data_root",
                    "model_dir",
                    "ffmpeg_path",
                    "models",
                    "pending_cleanup_data_root",
                    "pending_cleanup_model_dir",
                }:
                    continue
                config[key] = value
            config.update({k: v for k, v in preserved_values.items() if v is not None})
            requested_data_root = self._normalize_requested_data_root(str(config.get("data_root", current_data_root) or current_data_root))
            migration_result = None
            save_config(config)
            self._refresh_pending_cleanup_actions(config)
            if previous_prefer_gpu != config.get("prefer_gpu", DEFAULT_CONFIG["prefer_gpu"]):
                reset_engine()
            synced_model_dir = sync_model_dir_to_config()
            synced_path = sync_ffmpeg_path_to_config()
            self.load_settings_values()
            if synced_model_dir:
                self.settings_page.input_model_dir.setText(synced_model_dir)
            if synced_path:
                self.settings_page.input_ffmpeg_path.setText(synced_path)
            self.check_runtime_resources(show_dialog=False)
            self._update_inference_backend_hint()
            self._update_sampling_preview()
            reset_message = self.texts["reset_settings_done"]
            if isinstance(migration_result, dict) and migration_result.get("migrated"):
                reset_message = f"{reset_message}\n\n{self._build_data_root_migration_message(migration_result, requested_data_root)}"
            self.settings_page.lbl_status.setText(reset_message)
            self.show_info_dialog(self.texts["success_title"], reset_message, kind="success")
        except Exception as exc:
            self.show_error_dialog(self.texts["settings_save_failed"], exc)

    def _normalize_requested_data_root(self, raw_value):
        value = str(raw_value or "").strip()
        if not value:
            value = DEFAULT_CONFIG["data_root"]
        return os.path.normpath(os.path.abspath(os.path.expanduser(value)))

    def _migrate_data_root_if_needed(self, current_data_root, requested_data_root):
        if os.path.normcase(requested_data_root) == os.path.normcase(current_data_root):
            return None
        confirmed = self.show_confirm_dialog(
            self.texts["confirm_title"],
            self.texts["data_root_move_confirm"].format(path=requested_data_root),
        )
        if not confirmed:
            self.settings_page.lbl_status.setText(self.texts["settings_hint"])
            return False
        return migrate_app_data_root(requested_data_root)

    def _build_data_root_migration_message(self, migration_result, fallback_new_path):
        result = dict(migration_result or {})
        old_path = str(result.get("old_data_root", "") or "").strip()
        new_path = str(result.get("new_data_root", "") or "").strip() or str(fallback_new_path or "").strip()
        if old_path and new_path:
            template = self.texts.get("data_root_move_success_detail", "")
            if template:
                return template.format(old_path=old_path, new_path=new_path)
        return self.texts["data_root_move_success"].format(path=new_path or fallback_new_path)

    def _browse_data_root(self):
        current_path = self._normalize_requested_data_root(self.settings_page.input_data_root.text())
        selected_path = QFileDialog.getExistingDirectory(
            self,
            self.texts["browse_folder"],
            current_path,
        )
        if not selected_path:
            return
        self.settings_page.input_data_root.setText(os.path.normpath(selected_path))

    def _get_pending_cleanup_data_root(self, config=None):
        current_config = dict(config or load_config())
        pending_root = str(current_config.get("pending_cleanup_data_root", "") or "").strip()
        if not pending_root:
            return ""
        pending_root = self._normalize_requested_data_root(pending_root)
        active_root = get_configured_data_root(current_config)
        if os.path.normcase(pending_root) == os.path.normcase(active_root):
            return ""
        return pending_root

    def _refresh_pending_cleanup_action(self, config=None):
        pending_root = self._get_pending_cleanup_data_root(config)
        self.settings_page.btn_cleanup_old_data_root.setVisible(bool(pending_root))
        if pending_root:
            self.settings_page.btn_cleanup_old_data_root.setToolTip(
                self.texts["cleanup_old_data_root_pending"].format(path=pending_root)
            )
        else:
            self.settings_page.btn_cleanup_old_data_root.setToolTip("")
        return pending_root

    def _get_pending_cleanup_model_dir(self, config=None):
        current_config = dict(config or load_config())
        pending = str(current_config.get("pending_cleanup_model_dir", "") or "").strip()
        if not pending:
            return ""
        pending = os.path.normpath(os.path.abspath(os.path.expanduser(pending)))
        try:
            active = get_effective_model_dir(config=current_config)
        except Exception:
            return pending
        active_norm = os.path.normpath(os.path.abspath(os.path.expanduser(str(active or "").strip())))
        if pending and active_norm and os.path.normcase(pending) == os.path.normcase(active_norm):
            return ""
        return pending

    def _refresh_pending_cleanup_model_action(self, config=None):
        pending_path = self._get_pending_cleanup_model_dir(config)
        self.settings_page.btn_cleanup_old_model_dir.setVisible(bool(pending_path))
        if pending_path:
            self.settings_page.btn_cleanup_old_model_dir.setToolTip(
                self.texts["cleanup_old_model_dir_pending"].format(path=pending_path)
            )
        else:
            self.settings_page.btn_cleanup_old_model_dir.setToolTip("")
        return pending_path

    def _refresh_pending_cleanup_actions(self, config=None):
        self._refresh_pending_cleanup_action(config)
        self._refresh_pending_cleanup_model_action(config)

    def cleanup_old_data_root(self):
        config = load_config()
        current_data_root = get_configured_data_root(config)
        target_root = self._get_pending_cleanup_data_root(config)
        try:
            if not target_root:
                message = self.texts["cleanup_old_data_root_unavailable"]
                self.settings_page.lbl_status.setText(message)
                self.show_info_dialog(self.texts["warning_title"], message, kind="warning")
                self._refresh_pending_cleanup_actions(config)
                return

            if os.path.normcase(target_root) == os.path.normcase(current_data_root):
                message = self.texts["cleanup_old_data_root_active_error"].format(path=target_root)
                self.settings_page.lbl_status.setText(message)
                self.show_info_dialog(self.texts["warning_title"], message, kind="warning")
                return

            if not self.show_confirm_dialog(
                self.texts["confirm_title"],
                self.texts["cleanup_old_data_root_confirm"].format(path=target_root),
                kind="warning",
            ):
                self.settings_page.lbl_status.setText(self.texts["settings_hint"])
                return

            if not self.show_confirm_dialog(
                self.texts["confirm_title"],
                self.texts["cleanup_old_data_root_confirm_again"].format(
                    path=target_root,
                    active_path=current_data_root,
                ),
                kind="warning",
            ):
                self.settings_page.lbl_status.setText(self.texts["settings_hint"])
                return

            result = cleanup_old_data_root_service(target_root, active_data_root=current_data_root)
            config.pop("pending_cleanup_data_root", None)
            save_config(config)
            self._refresh_pending_cleanup_actions(config)
            if result.get("cleaned"):
                message = self.texts["cleanup_old_data_root_done"].format(path=result.get("old_data_dir", target_root))
                self.settings_page.lbl_status.setText(message)
                self.show_info_dialog(self.texts["success_title"], message, kind="success")
                return

            message = self.texts["cleanup_old_data_root_missing"].format(path=result.get("old_data_dir", target_root))
            self.settings_page.lbl_status.setText(message)
            self.show_info_dialog(self.texts["warning_title"], message, kind="warning")
        except Exception as exc:
            self.show_error_dialog(self.texts["cleanup_old_data_root_failed"], exc)

    def cleanup_old_model_dir(self):
        config = load_config()
        target_dir = self._get_pending_cleanup_model_dir(config)
        try:
            active_dir = get_effective_model_dir(config=config)
        except Exception as exc:
            self.show_error_dialog(self.texts["cleanup_old_model_dir_failed"], exc)
            return
        try:
            if not target_dir:
                message = self.texts["cleanup_old_model_dir_unavailable"]
                self.settings_page.lbl_status.setText(message)
                self.show_info_dialog(self.texts["warning_title"], message, kind="warning")
                self._refresh_pending_cleanup_actions(config)
                return

            if os.path.normcase(target_dir) == os.path.normcase(os.path.normpath(active_dir)):
                message = self.texts["cleanup_old_model_dir_active_error"].format(path=target_dir)
                self.settings_page.lbl_status.setText(message)
                self.show_info_dialog(self.texts["warning_title"], message, kind="warning")
                return

            if not self.show_confirm_dialog(
                self.texts["confirm_title"],
                self.texts["cleanup_old_model_dir_confirm"].format(path=target_dir),
                kind="warning",
            ):
                self.settings_page.lbl_status.setText(self.texts["settings_hint"])
                return

            if not self.show_confirm_dialog(
                self.texts["confirm_title"],
                self.texts["cleanup_old_model_dir_confirm_again"].format(
                    path=target_dir,
                    active_path=active_dir,
                ),
                kind="warning",
            ):
                self.settings_page.lbl_status.setText(self.texts["settings_hint"])
                return

            result = cleanup_old_model_dir_service(target_dir, active_model_dir=active_dir)
            config.pop("pending_cleanup_model_dir", None)
            save_config(config)
            self._refresh_pending_cleanup_actions(config)
            if result.get("cleaned"):
                message = self.texts["cleanup_old_model_dir_done"].format(
                    path=result.get("old_model_dir", target_dir)
                )
                self.settings_page.lbl_status.setText(message)
                self.show_info_dialog(self.texts["success_title"], message, kind="success")
                return

            message = self.texts["cleanup_old_model_dir_missing"].format(
                path=result.get("old_model_dir", target_dir)
            )
            self.settings_page.lbl_status.setText(message)
            self.show_info_dialog(self.texts["warning_title"], message, kind="warning")
        except Exception as exc:
            self.show_error_dialog(self.texts["cleanup_old_model_dir_failed"], exc)

    def _browse_ffmpeg_path(self):
        current_path = self.settings_page.input_ffmpeg_path.text().strip()
        initial_dir = os.path.dirname(current_path) if current_path else ""
        selected_path, _ = QFileDialog.getOpenFileName(
            self,
            self.texts["browse_file"],
            initial_dir,
            "Executable Files (*.exe);;All Files (*.*)",
        )
        if not selected_path:
            return
        self.settings_page.input_ffmpeg_path.setText(os.path.normpath(selected_path))

    def _browse_model_dir(self):
        current_path = self.settings_page.input_model_dir.text().strip()
        initial_dir = current_path if current_path and os.path.isdir(current_path) else ""
        selected_path = QFileDialog.getExistingDirectory(
            self,
            self.texts["browse_folder"],
            initial_dir,
        )
        if not selected_path:
            return
        self.settings_page.input_model_dir.setText(os.path.normpath(selected_path))

    def _migrate_model_root(self):
        t = self.texts
        try:
            config = load_config()
            source = get_effective_model_dir(config=config)
        except Exception as exc:
            self.show_error_dialog(t["model_root_move_failed"], exc)
            return
        if not source or not os.path.isdir(source):
            self.show_info_dialog(t["warning_title"], t["model_root_move_source_missing"], kind="warning")
            return
        initial = source
        dest = QFileDialog.getExistingDirectory(self, t["model_root_move_pick_target"], initial)
        if not dest:
            return
        dest = os.path.normpath(os.path.abspath(os.path.expanduser(dest)))
        if os.path.normcase(dest) == os.path.normcase(source):
            self.show_info_dialog(t["warning_title"], t["model_root_move_same_path"], kind="warning")
            return
        if not self.show_confirm_dialog(t["confirm_title"], t["model_root_move_confirm"].format(source=source, dest=dest)):
            self.settings_page.lbl_status.setText(t["settings_hint"])
            return
        try:
            result = migrate_model_root(dest)
        except Exception as exc:
            self.show_error_dialog(t["model_root_move_failed"], exc)
            return
        if not result.get("migrated") and result.get("reason") == "same_path":
            return
        self.load_settings_values()
        synced = sync_model_dir_to_config()
        if synced:
            self.settings_page.input_model_dir.setText(synced)
        self.check_runtime_resources(show_dialog=False)
        self._update_inference_backend_hint()
        old_path = str(result.get("old_model_dir", "") or "")
        new_path = str(result.get("new_model_dir", "") or "")
        detail = str(t.get("model_root_move_success_detail") or "").strip()
        if detail and old_path and new_path:
            msg = detail.format(old_path=old_path, new_path=new_path)
        else:
            msg = t["model_root_move_success"].format(path=new_path or dest)
        self.settings_page.lbl_status.setText(msg)
        self.show_info_dialog(t["success_title"], msg, kind="success")

    def _bind_sampling_preview_signals(self):
        if getattr(self, "_sampling_preview_bound", False):
            return
        self._sampling_preview_bound = True
        self.settings_page.input_fps.valueChanged.connect(self._update_sampling_preview)
        self.settings_page.input_sampling_fps_mode.currentIndexChanged.connect(self._handle_sampling_mode_preview_changed)
        self.settings_page.input_sampling_fps_mode.currentIndexChanged.connect(self._handle_sampling_mode_feedback_changed)
        self.settings_page.input_sampling_fps_rules.textChanged.connect(self._update_sampling_preview)
        self.settings_page.input_sampling_fps_rules.textChanged.connect(self._update_sampling_rules_feedback)

    def _handle_sampling_mode_preview_changed(self, *_args):
        self._ensure_dynamic_sampling_defaults()
        self._update_sampling_preview()

    def _handle_sampling_mode_feedback_changed(self, *_args):
        self._ensure_dynamic_sampling_defaults()
        self._update_sampling_rules_feedback()

    def _open_sampling_rules_dialog(self):
        dialog = SamplingRulesDialog(
            parent=self,
            is_dark=self.is_dark_mode,
            language=self.language,
            rules_text=self.settings_page.get_sampling_fps_rules_text() or DEFAULT_CONFIG["sampling_fps_rules"],
        )
        if dialog.exec():
            self.settings_page.set_sampling_fps_rules_text(dialog.rules_text())
            self._update_sampling_rules_feedback()
            self._update_sampling_preview()

    def _ensure_dynamic_sampling_defaults(self):
        if normalize_sampling_fps_mode(self.settings_page.get_sampling_fps_mode()) != "dynamic":
            return
        current_rules_text = normalize_sampling_fps_rules_text(self.settings_page.get_sampling_fps_rules_text())
        if current_rules_text:
            return
        self.settings_page.set_sampling_fps_rules_text(DEFAULT_CONFIG["sampling_fps_rules"])

    def _update_sampling_rules_feedback(self):
        current_rules_text = self.settings_page.get_sampling_fps_rules_text()
        rules_text = normalize_sampling_fps_rules_text(current_rules_text)
        sampling_fps_mode = normalize_sampling_fps_mode(self.settings_page.get_sampling_fps_mode())
        if sampling_fps_mode == "dynamic":
            rules_text = ensure_sampling_fps_rules_open_tail(rules_text, default_tail_fps=0.5)
        default_hint = self.texts["setting_sampling_fps_rules_hint"]
        if current_rules_text != rules_text:
            self.settings_page.set_sampling_fps_rules_text(rules_text)
            return
        if sampling_fps_mode != "dynamic":
            self.settings_page.set_sampling_rules_error_state(False)
            return

        is_valid, _ = validate_sampling_fps_rules_full_coverage(rules_text)
        if rules_text and not is_valid:
            self.settings_page.set_sampling_rules_error_state(True)
            return

        self.settings_page.set_sampling_rules_error_state(False)

    def _update_sampling_preview(self):
        base_fps = float(self.settings_page.input_fps.value())
        sampling_fps_mode = normalize_sampling_fps_mode(self.settings_page.get_sampling_fps_mode())
        rules_text = normalize_sampling_fps_rules_text(self.settings_page.get_sampling_fps_rules_text())
        if sampling_fps_mode == "dynamic":
            rules_text = ensure_sampling_fps_rules_open_tail(rules_text, default_tail_fps=0.5)
        rules_valid, _ = validate_sampling_fps_rules_full_coverage(rules_text)
        if sampling_fps_mode == "dynamic" and rules_text and not rules_valid:
            return
        samples = [
            ("2m", 120.0),
            ("10m", 600.0),
            ("30m", 1800.0),
            ("2h", 7200.0),
        ]
        preview_parts = []
        for label, duration_sec in samples:
            fps_value = resolve_sampling_fps(
                duration_sec=duration_sec,
                config={
                    "fps": base_fps,
                    "sampling_fps_mode": sampling_fps_mode,
                    "sampling_fps_rules": rules_text,
                },
            )
            frame_count = max(1, int(round(duration_sec * fps_value)))
            if self.language == "zh":
                preview_parts.append(f"{label} -> {fps_value:.2f} FPS / ~{frame_count}\u5e27")
            else:
                preview_parts.append(f"{label} -> {fps_value:.2f} FPS / ~{frame_count} frames")

        if self.language != "zh":
            prefix = "Fixed sampling" if sampling_fps_mode == "fixed" else "Duration-range sampling"
        else:
            prefix = "\u56fa\u5b9a\u91c7\u6837" if sampling_fps_mode == "fixed" else "\u603b\u957f\u5ea6\u533a\u95f4\u91c7\u6837"
        self.settings_page.hint_sampling_fps_preview.setText(f"{prefix}: " + " | ".join(preview_parts))

    def show_notice(self):
        NoticeDialog(self, self.is_dark_mode, self.language, notice=self.notice_payload).exec()

    def show_about(self):
        AboutDialog(
            self,
            self.is_dark_mode,
            self.language,
            version_info=self.version_info,
            about=self.about_payload,
        ).exec()

    def refresh_library_table(self):
        try:
            is_indexing = self.indexing_controller.is_running()
            populate_library_table(
                self.library_page.lib_table,
                list_libraries(),
                is_indexing,
                self.sync_library,
                self.remove_library_entry,
                self.open_library_folder,
                self.texts,
            )
            self._refresh_global_index_ui()
        except Exception as exc:
            self.show_error_dialog(self.texts["library_load_failed"], exc)
            return
        try:
            self._refresh_remix_scope_table()
        except Exception:
            pass

    def sync_library(self, path):
        self.start_update_index(target_lib=path, rebuild_global_assets=False)

    def open_library_folder(self, path):
        open_folder_in_explorer(path)

    def start_search(self):
        if not self.check_runtime_resources():
            self.search_page.lbl_status.setText(self.texts["model_features_disabled"])
            return

        text_query = self.search_page.text_search.text().strip()
        if text_query:
            query_info = prepare_text_query(text_query)
            if query_info["too_short"]:
                self.search_page.lbl_status.setText(self.texts["query_too_short"])
                return
            if query_info["changed"]:
                self.search_page.text_search.setText(query_info["normalized"])
            if query_info["generic"]:
                self.show_info_dialog(
                    self.texts["query_generic_title"],
                    self.texts["query_generic_hint"],
                    kind="info",
                )
            query = query_info["normalized"]
        else:
            query = self.current_img_path
        if not query:
            self.search_page.lbl_status.setText(self.texts["empty_query"])
            return

        self.switch_page("search")
        self.search_controller.start_search(query, bool(text_query))

    def _browse_remix_mix_video(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            self.texts["remix_file_dialog_title"],
            "",
            self.texts["remix_file_filter"],
        )
        if path:
            self.remix_page.input_mix_path.setText(path)

    def _stop_remix_thumbnail_loading(self):
        from ui.threading_utils import shutdown_thread

        shutdown_thread(getattr(self, "_remix_thumb_thread", None), stop_first=True)
        self._remix_thumb_thread = None

    def _refresh_remix_scope_table(self):
        t = self.texts
        table = self.remix_page.scope_table
        table.setHorizontalHeaderLabels([t["remix_scope_col_use"], t["remix_scope_col_name"], t["remix_scope_col_path"]])
        table.setRowCount(0)
        try:
            detail = list_local_vector_details(validate_contents=False)
        except Exception:
            return
        for ent in detail.get("entries", []):
            if not ent.get("source_exists"):
                continue
            if str(ent.get("asset_state", "")).strip().lower() != "ready":
                continue
            lib = ent.get("library_path", "")
            rel = ent.get("video_rel_path", "")
            full = os.path.normpath(os.path.join(str(lib), str(rel)))
            row = table.rowCount()
            table.insertRow(row)
            wrap, cb = build_remix_scope_checkbox_widget(full, checked=True)
            cb.setToolTip(t.get("remix_scope_check_tip", ""))
            table.setCellWidget(row, 0, wrap)
            name_item = QTableWidgetItem(os.path.basename(full))
            name_item.setFlags(name_item.flags() & ~Qt.ItemIsEditable)
            name_item.setTextAlignment(Qt.AlignCenter)
            name_item.setToolTip(full)
            table.setItem(row, 1, name_item)
            path_item = QTableWidgetItem(full)
            path_item.setFlags(path_item.flags() & ~Qt.ItemIsEditable)
            path_item.setToolTip(full)
            table.setItem(row, 2, path_item)

    def _on_remix_scope_table_cell_clicked(self, row, column):
        if column == 0:
            return
        cb = remix_scope_row_checkbox(self.remix_page.scope_table, row)
        if cb is not None:
            cb.setChecked(not cb.isChecked())

    def _remix_scope_select_all(self):
        table = self.remix_page.scope_table
        for r in range(table.rowCount()):
            cb = remix_scope_row_checkbox(table, r)
            if cb is not None:
                cb.setChecked(True)

    def _remix_scope_select_none(self):
        table = self.remix_page.scope_table
        for r in range(table.rowCount()):
            cb = remix_scope_row_checkbox(table, r)
            if cb is not None:
                cb.setChecked(False)

    def clear_remix_match_ui(self):
        from ui.threading_utils import shutdown_thread

        if self.remix_worker is not None:
            self.remix_worker.stop()
            shutdown_thread(self.remix_worker)
            self.remix_worker = None
        self.remix_page.btn_run.setEnabled(True)
        self.remix_page.btn_stop.setEnabled(False)
        self._stop_remix_thumbnail_loading()
        self.remix_page.result_table.setRowCount(0)
        self.remix_page.lbl_status.setText(self.texts.get("ready", ""))

    def stop_remix_match(self):
        if self.remix_worker is not None:
            self.remix_worker.stop()

    def start_remix_match(self):
        if not self.check_runtime_resources():
            self.remix_page.lbl_status.setText(self.texts["model_features_disabled"])
            return
        mix = self.remix_page.input_mix_path.text().strip()
        if not mix or not os.path.isfile(mix):
            self.remix_page.lbl_status.setText(self.texts["remix_mix_hint"])
            return
        scope_paths = None
        if self.remix_page.radio_scope_restricted.isChecked():
            paths = []
            table = self.remix_page.scope_table
            for r in range(table.rowCount()):
                cb = remix_scope_row_checkbox(table, r)
                if cb is not None and cb.isChecked():
                    p = cb.property("video_path")
                    if p:
                        paths.append(str(p))
            if not paths:
                self.remix_page.lbl_status.setText(self.texts["remix_scope_table_hint"])
                return
            scope_paths = paths

        self._stop_remix_thumbnail_loading()
        self.remix_page.btn_run.setEnabled(False)
        self.remix_page.btn_stop.setEnabled(True)
        self.remix_page.lbl_status.setText(self.texts["remix_progress"])
        self._remix_match_started_at = time.time()

        self.remix_worker = RemixMatchWorker(
            mix,
            scope_paths,
            self.remix_page.input_sample_fps.value(),
            self.remix_page.input_score_threshold.value(),
            self.remix_page.input_merge_gap.value(),
            self.remix_page.input_min_segment.value(),
            self.remix_page.input_remix_cluster_gap.value(),
            self.remix_page.input_faiss_top_k.value(),
            self.remix_page.input_speed_min.value(),
            self.remix_page.input_speed_max.value(),
            self.remix_page.input_ransac_iters.value(),
            self.remix_page.input_min_line_points.value(),
        )
        self.remix_worker.result_ready.connect(self._on_remix_match_results)
        self.remix_worker.error_signal.connect(self._on_remix_match_error)
        self.remix_worker.stopped_signal.connect(self._on_remix_match_stopped)
        self.remix_worker.progress_signal.connect(self._on_remix_match_progress)
        self.remix_worker.finished.connect(self._on_remix_match_finished)
        self.remix_worker.start()

    def _on_remix_match_progress(self, msg):
        s = str(msg)
        if s.startswith("remix_progress_frames:"):
            self.remix_page.lbl_status.setText(self.texts["remix_progress"])
        elif s == "remix_progress_cache_hit":
            self.remix_page.lbl_status.setText(self.texts.get("remix_progress_cache_hit", self.texts["remix_progress"]))
        elif s == "remix_progress_embed_done":
            self.remix_page.lbl_status.setText(self.texts.get("remix_progress_embed_done", self.texts["remix_progress"]))
        else:
            self.remix_page.lbl_status.setText(self.texts["remix_progress"])

    def _on_remix_match_results(self, results):
        self._update_inference_backend_hint()
        if not results:
            self.remix_page.result_table.setRowCount(0)
            self.remix_page.lbl_status.setText(self.texts["remix_no_results"])
            return
        mix_path = self.remix_page.input_mix_path.text().strip()
        populate_remix_result_table(
            self.remix_page.result_table,
            results,
            mix_path,
            self.handle_remix_compare,
            self.open_result_in_explorer,
            self.handle_export_clip,
            self.texts,
        )
        elapsed = max(0.0, time.time() - getattr(self, "_remix_match_started_at", time.time()))
        self.remix_page.lbl_status.setText(self.texts["remix_done"].format(count=len(results), duration=elapsed))
        thumb_payload = [h.as_search_hit() for h in results]
        self._remix_thumb_thread = ThumbLoader(thumb_payload)
        self._remix_thumb_thread.thumb_ready.connect(self._on_remix_thumb_ready)
        self._remix_thumb_thread.start()

    def _on_remix_thumb_ready(self, row, pixmap):
        label = QLabel()
        label.setAlignment(Qt.AlignCenter)
        label.setPixmap(pixmap)
        self.remix_page.result_table.setCellWidget(row, 1, label)

    def _on_remix_match_error(self, error_text):
        self._update_inference_backend_hint()
        self.remix_page.lbl_status.setText(self.texts["remix_failed"])
        if str(error_text).strip():
            self.show_error_dialog(self.texts["remix_failed"], Exception(str(error_text)))

    def _on_remix_match_stopped(self):
        self._update_inference_backend_hint()
        self.remix_page.lbl_status.setText(self.texts["remix_stopped"])

    def _on_remix_match_finished(self):
        self.remix_page.btn_run.setEnabled(True)
        self.remix_page.btn_stop.setEnabled(False)
        self.remix_worker = None

    def toggle_mobile_bridge(self):
        try:
            url = self.mobile_bridge_controller.toggle()
        except Exception as exc:
            self.show_error_dialog(self.texts["mobile_bridge_start_failed"], exc)
            return

        if url:
            self.search_page.lbl_status.setText(self.texts["mobile_bridge_running"].format(url=url))
            self.show_mobile_bridge_qr()
        else:
            self.search_page.lbl_status.setText(self.texts["mobile_bridge_stopped"])
        self._update_mobile_bridge_controls()

    def show_mobile_bridge_qr(self):
        if not self.mobile_bridge_controller.is_running():
            return
        url = self.mobile_bridge_controller.get_access_url()
        MobileBridgeDialog(
            url=url,
            parent=self,
            is_dark=self.is_dark_mode,
            language=self.language,
            qr_pixmap=build_qr_pixmap(url),
        ).exec()

    def _handle_mobile_upload_received(self, path, _source):
        self.switch_page("search")
        self._set_image_query(path, clear_text=True)
        self.search_page.lbl_status.setText(self.texts["mobile_bridge_received"])
        self.start_search()

    def _handle_mobile_bridge_status_changed(self, _state):
        self._update_mobile_bridge_controls()

    def _update_mobile_bridge_controls(self):
        is_running = hasattr(self, "mobile_bridge_controller") and self.mobile_bridge_controller.is_running()
        self.search_page.btn_mobile_toggle.blockSignals(True)
        self.search_page.btn_mobile_toggle.setChecked(is_running)
        self.search_page.btn_mobile_toggle.blockSignals(False)
        self.search_page.btn_mobile_toggle.setProperty("bridgeState", "on" if is_running else "off")
        self.search_page.btn_mobile_toggle.style().unpolish(self.search_page.btn_mobile_toggle)
        self.search_page.btn_mobile_toggle.style().polish(self.search_page.btn_mobile_toggle)
        self.search_page.btn_mobile_toggle.update()
        self.search_page.btn_mobile_qr.setObjectName("MobileBridgeQrButton")
        self.search_page.btn_mobile_qr.style().unpolish(self.search_page.btn_mobile_qr)
        self.search_page.btn_mobile_qr.style().polish(self.search_page.btn_mobile_qr)
        self.search_page.btn_mobile_qr.update()
        self.search_page.btn_mobile_toggle.setText(self._mobile_bridge_toggle_text(is_running))
        self.search_page.btn_mobile_toggle.setToolTip(
            self.texts["mobile_bridge_stop"] if is_running else self.texts["mobile_bridge_start"]
        )
        self.search_page.btn_mobile_qr.setEnabled(is_running)

    def _mobile_bridge_toggle_text(self, is_running, texts=None):
        t = texts or self.texts
        return t.get("mobile_bridge_toggle_on" if is_running else "mobile_bridge_toggle_off", "ON" if is_running else "OFF")

    def _save_search_mode(self):
        try:
            config = load_config()
            search_mode = str(self.search_page.search_mode.currentData() or DEFAULT_CONFIG["search_mode"])
            config["search_mode"] = search_mode
            save_config(config)
        except Exception as exc:
            self.show_error_dialog(self.texts["settings_save_failed"], exc)

    def _build_settings_save_message(self, fps_changed, chunk_changed):
        if fps_changed and chunk_changed:
            return self.texts["settings_saved_mixed_rebuild"]
        if fps_changed:
            return self.texts["settings_saved_full_rebuild"]
        if chunk_changed:
            return self.texts["settings_saved_chunk_rebuild"]
        return self.texts["settings_saved_no_rebuild"]

    def clear_all_content(self):
        self.current_img_path = None
        self.search_page.text_search.clear()
        self.search_page.img_label.clear()
        self.search_page.img_label.setText(self.texts["image_drop_hint"])
        self.search_controller.clear_results()
        self.preview_controller.stop_preview()
        self._update_expand_preview_button()
        self.search_page.lbl_status.setText(self.texts["ready"])

    def clear_link_search_content(self):
        if hasattr(self, "network_search_controller"):
            self.network_search_controller.clear()
            return
        self.link_page.input_link.clear()
        self.network_query_img_path = None
        self.link_page.query_image_label.clear()
        self.link_page.query_image_label.setText(self.texts["network_image_preview_hint"])
        self.link_page.progress_bar.setValue(0)
        self.link_page.result_table.setRowCount(0)
        self.link_page.lbl_build_status.setText(self.texts["ready"])
        self.link_page.lbl_search_status.setText(self.texts["ready"])

    def open_result_in_explorer(self, path):
        open_in_explorer(path)

    def select_video_folder(self):
        path = QFileDialog.getExistingDirectory(self, self.texts["select_folder"])
        if not path:
            return
        try:
            result = add_library(path)
            if result.get("added"):
                self.refresh_library_table()
                status_text = self._with_global_index_notice(self.texts["library_added"])
                self.library_page.lbl_status.setText(status_text)
                self.show_info_dialog(self.texts["success_title"], status_text, kind="success")
            elif result.get("reason") == "overlap":
                message = self.texts["library_overlap"].format(path=result.get("conflict_path", ""))
                self.library_page.lbl_status.setText(message)
                self.show_info_dialog(self.texts["warning_title"], message, kind="warning")
            else:
                self.library_page.lbl_status.setText(self.texts["library_exists"])
                self.show_info_dialog(self.texts["warning_title"], self.texts["library_exists"], kind="warning")
        except Exception as exc:
            self.show_error_dialog(self.texts["library_add_failed"], exc)

    def remove_library_entry(self, path):
        if not self.show_confirm_dialog(self.texts["confirm_title"], self.texts["remove_library_confirm"].format(path=path)):
            return
        try:
            if remove_library_entry(path, delete_physical_video_data):
                self.refresh_library_table()
                status_text = self._with_global_index_notice(self.texts["library_removed"])
                self.library_page.lbl_status.setText(status_text)
                self.show_info_dialog(self.texts["success_title"], status_text, kind="success")
            else:
                self.library_page.lbl_status.setText(self.texts["library_remove_failed"])
        except Exception as exc:
            self.show_error_dialog(self.texts["library_remove_failed"], exc)

    def start_update_index(self, target_lib=None, rebuild_global_assets=True):
        self._start_index_update(
            target_lib=target_lib,
            force_cleanup_missing_files=False,
            rebuild_global_assets=rebuild_global_assets,
        )

    def start_debug_gpu_oom(self):
        self._start_index_update(debug_failure="gpu_oom")

    def start_debug_system_oom(self):
        self._start_index_update(debug_failure="system_oom")

    def cleanup_missing_library_vectors(self):
        try:
            config = load_config()
            meta = load_model_metadata(config=config)
            missing_entries = list(list_missing_library_files(meta, config))
        except Exception as exc:
            self.show_error_dialog(self.texts["library_load_failed"], exc)
            return

        if not missing_entries:
            self.show_info_dialog(
                self.texts["cleanup_missing_vectors_preview_title"],
                self.texts["cleanup_missing_vectors_preview_empty"],
                kind="info",
            )
            return

        reviewed_entries = self._show_cleanup_preview_dialog(missing_entries)
        if reviewed_entries is None:
            return
        if not reviewed_entries:
            self.show_info_dialog(
                self.texts["cleanup_missing_vectors_preview_title"],
                self.texts["cleanup_missing_vectors_preview_empty"],
                kind="info",
            )
            return

        if not self.show_confirm_dialog(
            self.texts["confirm_title"],
            self.texts["cleanup_missing_vectors_confirm"].format(count=len(reviewed_entries)),
            kind="warning",
        ):
            return
        self._start_index_update(
            target_lib=None,
            force_cleanup_missing_files=True,
            cleanup_missing_entries=reviewed_entries,
        )

    def _show_cleanup_preview_dialog(self, missing_entries):
        rows = []
        for index, entry in enumerate(missing_entries, start=1):
            rows.append(
                [
                    index,
                    entry["library_path"],
                    entry["video_rel_path"],
                    entry.get("video_id", "") or "",
                    entry["abs_path"],
                ]
            )

        subtitle = "\n".join(
            [
                self.texts["cleanup_missing_vectors_preview_summary"].format(
                    count=len(missing_entries),
                    libraries=len({entry["library_path"] for entry in missing_entries}),
                ),
                self.texts["cleanup_missing_vectors_preview_continue"],
            ]
        )
        dialog = ResourceTableDialog(
            parent=self,
            is_dark=self.is_dark_mode,
            language=self.language,
            title=self.texts["cleanup_missing_vectors_preview_title"],
            subtitle=subtitle,
            headers=self.texts["cleanup_missing_vectors_headers"],
            rows=rows,
            export_default_name=self.texts["cleanup_missing_vectors_export_name"],
            stretch_column=4,
            fixed_column_widths={
                0: 52,
                2: 220,
                3: 140,
            },
            confirm_mode=True,
            confirm_text=self.texts["confirm_action"],
            issue_row_predicate=lambda row: True,
            summary_text=self.texts["cleanup_missing_vectors_preview_continue"],
            row_payloads=missing_entries,
            extra_actions=[
                {
                    "label": self.texts["details_exclude_selected"],
                    "object_name": "Ghost",
                    "handler": self._exclude_cleanup_preview_selection,
                }
            ],
            selection_mode=QAbstractItemView.ExtendedSelection,
        )
        if not dialog.exec():
            return None
        return dialog.row_payloads

    def _exclude_cleanup_preview_selection(self, dialog):
        removed = dialog.remove_selected_payloads()
        if not removed:
            dialog.status_hint.setText(self.texts["details_nothing_selected"])
            return
        dialog.status_hint.setText(self.texts["details_excluded_count"].format(count=removed))
        if not dialog.row_payloads:
            dialog.reject()

    def _start_index_update(
        self,
        target_lib=None,
        force_cleanup_missing_files=False,
        cleanup_missing_entries=None,
        rebuild_global_assets=True,
        debug_failure="",
    ):
        try:
            if not self.check_runtime_resources():
                self.library_page.lbl_status.setText(self.texts["model_features_disabled"])
                return
            self.switch_page("library")
            if self.indexing_controller.is_running():
                return
            self.library_page.btn_sync_db.setEnabled(False)
            self.library_page.btn_stop_index.setEnabled(True)
            self.library_page.btn_stop_index.setVisible(True)
            self.library_page.btn_add_lib.setEnabled(False)
            self._apply_index_issue_button_state(False)
            self.library_page.btn_cleanup_missing.setEnabled(False)
            if getattr(self, "_debug_tools_enabled", False):
                self.library_page.btn_debug_gpu_oom.setEnabled(False)
                self.library_page.btn_debug_system_oom.setEnabled(False)
            self.library_page.progress_bar.setVisible(True)
            self._last_index_issues = []
            self._last_index_issue_target = target_lib
            self.refresh_library_table()
            start_kwargs = {
                "target_lib": target_lib,
                "force_cleanup_missing_files": force_cleanup_missing_files,
                "cleanup_missing_entries": cleanup_missing_entries,
                "rebuild_global_assets": rebuild_global_assets,
            }
            if debug_failure:
                start_kwargs["debug_failure"] = debug_failure
            self.indexing_controller.start(
                **start_kwargs,
            )
            self._refresh_search_session_hint()
        except Exception as exc:
            self.show_error_dialog(self.texts["index_start_failed"], exc)

    def stop_update_index(self):
        if not self.indexing_controller.is_running():
            return
        if self.indexing_controller.request_stop():
            self.library_page.lbl_status.setText(self.texts["index_stop_requested"])
            self.library_page.btn_stop_index.setEnabled(False)

    def _update_indexing_progress(self, value, text):
        self.library_page.progress_bar.setValue(value)
        self.library_page.lbl_status.setText(text)

    def _apply_runtime_status(self, _status):
        self._update_inference_backend_hint()

    def _finish_indexing(self, success, target_lib, stopped=False, has_search_assets=False, issues=None, rebuild_global_assets=True):
        self.library_page.btn_sync_db.setEnabled(True)
        self.library_page.btn_stop_index.setEnabled(False)
        self.library_page.btn_stop_index.setVisible(False)
        self.library_page.btn_add_lib.setEnabled(True)
        self.library_page.btn_cleanup_missing.setEnabled(True)
        if getattr(self, "_debug_tools_enabled", False):
            self.library_page.btn_debug_gpu_oom.setEnabled(True)
            self.library_page.btn_debug_system_oom.setEnabled(True)
        self.library_page.progress_bar.setVisible(False)
        self._update_inference_backend_hint()
        self.refresh_library_table()
        issue_count = len(issues or [])
        self._last_index_issues = list(issues or [])
        self._last_index_issue_target = target_lib
        self._apply_index_issue_button_state(issue_count > 0)
        if stopped:
            status_text = self.texts["index_stopped"]
        elif success:
            if has_search_assets:
                status_text = self.texts["index_updated_single"] if target_lib else self.texts["index_updated"]
            else:
                status_text = self.texts["index_updated_empty_single"] if target_lib else self.texts["index_updated_empty"]
            if issue_count:
                status_text = f"{status_text} {self.texts['index_issue_summary'].format(count=issue_count)}"
        else:
            status_text = self.texts["index_failed"]
        if not rebuild_global_assets:
            status_text = self._with_global_index_notice(status_text)
        self.library_page.lbl_status.setText(status_text)
        self._refresh_search_session_hint()
        self._show_index_issue_guidance(issues or [])
        if self._close_when_indexing_stops:
            self._close_when_indexing_stops = False
            self.close()

    def _refresh_search_session_hint(self):
        self.search_page.session_hint.setText(self.texts.get("workspace_hint", ""))
        indexing_running = self.indexing_controller.is_running()
        self.search_page.indexing_notice.setVisible(indexing_running)
        if indexing_running:
            self._start_search_indexing_notice_animation()
        else:
            self._stop_search_indexing_notice_animation()

    def _start_search_indexing_notice_animation(self):
        if self._search_indexing_notice_effect is None:
            effect = QGraphicsOpacityEffect(self.search_page.indexing_notice)
            effect.setOpacity(1.0)
            self.search_page.indexing_notice.setGraphicsEffect(effect)
            self._search_indexing_notice_effect = effect
        if self._search_indexing_notice_animation is None:
            animation = QPropertyAnimation(self._search_indexing_notice_effect, b"opacity", self)
            animation.setStartValue(1.0)
            animation.setEndValue(0.55)
            animation.setDuration(900)
            animation.setEasingCurve(QEasingCurve.InOutSine)
            animation.setLoopCount(-1)
            self._search_indexing_notice_animation = animation
        if self._search_indexing_notice_animation.state() != QPropertyAnimation.Running:
            self._search_indexing_notice_animation.start()

    def _stop_search_indexing_notice_animation(self):
        animation = self._search_indexing_notice_animation
        if animation is not None and animation.state() == QPropertyAnimation.Running:
            animation.stop()
        if self._search_indexing_notice_effect is not None:
            self._search_indexing_notice_effect.setOpacity(1.0)

    def _handle_indexing_error(self, error_text):
        detail = str(error_text or "").strip()
        if not detail:
            return
        self.show_error_dialog(self.texts["index_failed"], detail)

    def _show_index_issue_guidance(self, issues):
        issue_list = list(issues or [])
        if not issue_list:
            return
        gpu_issue_count = sum(1 for item in issue_list if item.get("reason") == "gpu_out_of_memory")
        system_issue_count = sum(1 for item in issue_list if item.get("reason") == "system_out_of_memory")
        if gpu_issue_count <= 0 and system_issue_count <= 0:
            return
        if gpu_issue_count >= system_issue_count:
            resource_text = self.texts["index_issues_memory_resource_gpu"]
            issue_count = gpu_issue_count
        else:
            resource_text = self.texts["index_issues_memory_resource_system"]
            issue_count = system_issue_count
        message = self.texts["index_issues_memory_guidance"].format(
            count=issue_count,
            resource=resource_text,
            button=self.texts["index_issues_button"],
        )
        self.show_info_dialog(self.texts["warning_title"], message, kind="warning")

    def _get_global_index_state(self):
        try:
            return get_global_index_state()
        except Exception:
            return ""

    def _is_global_index_stale(self):
        return self._get_global_index_state() == GLOBAL_INDEX_STATE_STALE

    def _with_global_index_notice(self, status_text):
        base_text = str(status_text or "").strip()
        stale_text = self.texts.get("global_index_stale_status", "").strip()
        if not stale_text or not self._is_global_index_stale():
            return base_text
        if stale_text in base_text:
            return base_text
        if not base_text:
            return stale_text
        return f"{base_text} {stale_text}"

    def _refresh_global_index_ui(self):
        is_stale = self._is_global_index_stale()
        update_button = self.library_page.btn_sync_db
        update_button.setText(self.texts["update_index_pending"] if is_stale else self.texts["update_index"])
        update_button.setToolTip(self.texts["global_index_stale_status"] if is_stale else "")
        if not self.indexing_controller.is_running():
            update_button.setObjectName("WarningButton" if is_stale else "PrimaryButton")
            update_button.style().unpolish(update_button)
            update_button.style().polish(update_button)
            update_button.update()
            current_status = self.library_page.lbl_status.text().strip()
            stale_status = self.texts["global_index_stale_status"]
            if is_stale and current_status in {"", self.texts["ready"], stale_status}:
                self.library_page.lbl_status.setText(stale_status)
            elif not is_stale and current_status == stale_status:
                self.library_page.lbl_status.setText(self.texts["ready"])

    def _apply_index_issue_button_state(self, has_issues):
        button = self.library_page.btn_index_issues
        button.setEnabled(bool(has_issues))
        button.setObjectName("WarningButton" if has_issues else "GhostButton")
        button.style().unpolish(button)
        button.style().polish(button)
        button.update()

    def show_last_index_issue_details(self):
        if not self._last_index_issues:
            self.show_info_dialog(
                self.texts["index_issues_title"],
                self.texts["index_issues_empty"],
                kind="info",
            )
            return
        self.show_index_issue_details(self._last_index_issues, target_lib=self._last_index_issue_target)

    def show_index_issue_details(self, issues, target_lib=None):
        issue_list = list(issues or [])
        if not issue_list:
            return

        rows = []
        payloads = []
        for index, item in enumerate(issue_list, start=1):
            rows.append(
                [
                    index,
                    item.get("library_path", ""),
                    item.get("video_rel_path", ""),
                    self._format_index_issue_action(item.get("action")),
                    self._format_index_issue_reason(item.get("reason")),
                ]
            )
            payloads.append(item)

        subtitle = self.texts["index_issues_subtitle"].format(
            count=len(issue_list),
            scope=self.texts["index_issues_scope_single"] if target_lib else self.texts["index_issues_scope_all"],
        )
        ResourceTableDialog(
            parent=self,
            is_dark=self.is_dark_mode,
            language=self.language,
            title=self.texts["index_issues_title"],
            subtitle=subtitle,
            headers=self.texts["index_issues_headers"],
            rows=rows,
            row_payloads=payloads,
            export_default_name="index_issues.json",
            stretch_column=2,
            allow_sorting=False,
            fixed_column_widths={
                0: 52,
                3: 120,
                4: 180,
            },
            issue_row_predicate=lambda _row: True,
            extra_actions=[
                {
                    "label": self.texts["details_open_selected"],
                    "object_name": "Ghost",
                    "handler": self._open_selected_index_issue_path,
                },
                {
                    "label": self.texts["details_copy_selected"],
                    "object_name": "Ghost",
                    "handler": self._copy_selected_index_issue_path,
                },
            ],
            row_double_click_handler=self._open_index_issue_payload,
        ).exec()

    def _format_index_issue_action(self, action):
        action_key = str(action or "").strip().lower() or "skipped"
        return self.texts.get(f"index_issue_action_{action_key}", action_key)

    def _format_index_issue_reason(self, reason):
        reason_key = str(reason or "").strip().lower()
        if not reason_key:
            return ""
        return self.texts.get(
            f"index_issue_reason_{reason_key}",
            self.texts.get(f"library_sync_failure_reason_{reason_key}", reason_key),
        )

    def _open_index_issue_payload(self, dialog, payload, item=None):
        target_path = str(payload.get("abs_path", "")).strip()
        library_path = str(payload.get("library_path", "")).strip()
        detail = str(payload.get("detail", "")).strip()
        if not target_path and library_path:
            target_path = library_path
        if not target_path:
            dialog.status_hint.setText(detail or self.texts["details_nothing_selected"])
            return
        if os.path.exists(target_path):
            open_in_explorer(target_path)
        else:
            fallback_dir = os.path.dirname(target_path) or library_path
            if fallback_dir:
                open_folder_in_explorer(fallback_dir)
        dialog.status_hint.setText(f"{target_path} | {detail}" if detail else target_path)

    def _open_selected_index_issue_path(self, dialog):
        selected = dialog.get_selected_payloads()
        if not selected:
            dialog.status_hint.setText(self.texts["details_nothing_selected"])
            return
        self._open_index_issue_payload(dialog, selected[0], dialog.table.currentItem())

    def _copy_selected_index_issue_path(self, dialog):
        selected = dialog.get_selected_payloads()
        if not selected:
            dialog.status_hint.setText(self.texts["details_nothing_selected"])
            return
        payload = selected[0]
        target_path = str(payload.get("abs_path", "")).strip() or str(payload.get("library_path", "")).strip()
        if not target_path:
            dialog.status_hint.setText(self.texts["details_nothing_selected"])
            return
        QApplication.clipboard().setText(target_path)
        dialog.status_hint.setText(self.texts["details_copy_done"])

    def handle_play(self, path, sec, end_sec=None):
        if not self.check_runtime_resources():
            self.search_page.lbl_status.setText(self.texts["model_features_disabled"])
            self._update_expand_preview_button()
            return
        if not self.preview_controller.play(path, sec, end_sec=end_sec):
            self.search_page.lbl_status.setText(self.texts["preview_failed"])
        self._update_expand_preview_button()

    def handle_remix_compare(self, remix_path, remix_start_sec, remix_end_sec, source_path, source_start_sec, source_end_sec):
        if not self.check_runtime_resources():
            self.remix_page.lbl_status.setText(self.texts["model_features_disabled"])
            return
        rp = str(remix_path or "").strip()
        if not rp or not os.path.isfile(rp):
            self.remix_page.lbl_status.setText(
                self.texts.get("remix_compare_no_mix", "Remix video path is invalid. Pick the file again.")
            )
            return
        sp = str(source_path or "").strip()
        if not sp or not os.path.isfile(sp):
            self.remix_page.lbl_status.setText(
                self.texts.get("remix_compare_no_source", "Source video file not found.")
            )
            return
        dlg = RemixCompareDialog(
            self,
            rp,
            float(remix_start_sec),
            float(remix_end_sec),
            sp,
            float(source_start_sec),
            float(source_end_sec),
            self.texts,
        )
        dlg.exec()

    def open_current_preview_dialog(self, _event=None):
        if not self.check_runtime_resources():
            self.search_page.lbl_status.setText(self.texts["model_features_disabled"])
            return
        now = time.monotonic()
        if self._preview_dialog_opening or now < self._preview_dialog_cooldown_until:
            self.search_page.lbl_status.setText(
                self.texts.get("preview_dialog_busy", "Preview is still switching. Try again in a moment.")
            )
            return

        payload = self.preview_controller.get_current_preview_context()
        if not payload:
            return
        video_path = str(payload.get("video_path", "")).strip()
        if not video_path:
            return

        start_sec = float(payload.get("start_sec", 0.0))
        end_sec = float(payload.get("end_sec", start_sec))
        self.preview_controller.stop_preview()
        self._update_expand_preview_button()
        self._preview_dialog_opening = True
        self._preview_dialog_cooldown_until = now + 0.8

        try:
            if not hasattr(self, "_preview_dialog") or self._preview_dialog is None:
                self._preview_dialog = PreviewDialog(self, video_path, start_sec, end_sec, self.texts)
                self._preview_dialog.export_requested.connect(self._queue_preview_export)
                self._preview_dialog.export_status_changed.connect(self._handle_preview_export_status)
            else:
                self._preview_dialog.load_preview(video_path, start_sec, end_sec)
            self._preview_dialog.show()
            self._preview_dialog.raise_()
            self._preview_dialog.activateWindow()
        finally:
            QTimer.singleShot(800, self._release_preview_dialog_gate)

    def _release_preview_dialog_gate(self):
        self._preview_dialog_opening = False

    def _update_expand_preview_button(self):
        controller = getattr(self, "preview_controller", None)
        has_preview = controller is not None and controller.get_current_preview_context() is not None
        self.search_page.btn_expand_preview.setEnabled(has_preview)
        self._update_preview_action_button_styles()

    def _update_preview_action_button_styles(self):
        controller = getattr(self, "preview_controller", None)
        has_preview = controller is not None and controller.get_current_preview_context() is not None
        has_export_tasks = bool(self._preview_export_tasks)
        self._set_button_object_name(
            self.search_page.btn_expand_preview,
            "PrimaryButton" if has_preview else "GhostButton",
        )
        self._set_button_object_name(
            self.search_page.btn_export_tasks,
            "PrimaryButton" if has_export_tasks else "GhostButton",
        )

    @staticmethod
    def _set_button_object_name(button, object_name):
        if button.objectName() == object_name:
            return
        button.setObjectName(object_name)
        style = button.style()
        style.unpolish(button)
        style.polish(button)
        button.update()

    def _handle_preview_export_status(self, state, text):
        if state in {"queued", "running", "succeeded", "failed", "cancelled"}:
            self.search_page.lbl_status.setText(text)

    def _queue_preview_export(self, video_path, start_sec, end_sec, save_path):
        self._preview_export_seq += 1
        task = {
            "id": self._preview_export_seq,
            "video_path": str(video_path),
            "start_sec": float(start_sec),
            "end_sec": float(end_sec),
            "save_path": str(save_path),
            "status": "queued",
            "worker": None,
            "result": None,
        }
        self._preview_export_queue.append(task)
        self._preview_export_tasks.append(task)
        running_count = len(self._preview_export_active)
        queued_count = len(self._preview_export_queue)
        self.search_page.lbl_status.setText(
            self.texts.get(
                "preview_dialog_export_queue_status",
                "Export queued. Running: {running} | Waiting: {queued}",
            ).format(running=running_count, queued=queued_count)
        )
        self._update_preview_action_button_styles()
        self._start_next_preview_exports()

    def _start_next_preview_exports(self):
        while len(self._preview_export_active) < 2 and self._preview_export_queue:
            task = self._preview_export_queue.popleft()
            worker = ExportClipWorker(
                self.preview_controller,
                task["video_path"],
                task["start_sec"],
                task["end_sec"],
                task["save_path"],
            )
            task["worker"] = worker
            task["status"] = "running"
            self._preview_export_active[task["id"]] = task
            worker.finished_export.connect(
                lambda result, path, task_id=task["id"]: self._handle_preview_export_result(task_id, result, path)
            )
            worker.finished.connect(lambda task_id=task["id"]: self._handle_preview_export_finished(task_id))
            worker.start()
            running_count = len(self._preview_export_active)
            queued_count = len(self._preview_export_queue)
            self.search_page.lbl_status.setText(
                self.texts.get(
                    "preview_dialog_export_running_status",
                    "Export started. Running: {running} | Waiting: {queued}",
                ).format(running=running_count, queued=queued_count)
            )

    def _handle_preview_export_result(self, task_id, result, save_path):
        task = self._preview_export_active.get(task_id)
        if task is None:
            return
        task["result"] = result
        if isinstance(result, ExportCancelledError):
            task["status"] = "cancelled"
            text = self.texts.get("preview_dialog_export_cancelled", "Export cancelled.")
        elif isinstance(result, Exception) or getattr(result, "returncode", 1) != 0:
            task["status"] = "failed"
            text = self.texts.get("export_clip_failed", "Failed to export clip.")
        else:
            task["status"] = "succeeded"
            text = self.texts.get("export_clip_success", "Clip exported: {path}").format(path=save_path)
        self.search_page.lbl_status.setText(text)

    def _handle_preview_export_finished(self, task_id):
        task = self._preview_export_active.pop(task_id, None)
        if task is None:
            self._start_next_preview_exports()
            return
        worker = task.get("worker")
        if worker is not None:
            try:
                worker.deleteLater()
            except Exception:
                pass
        self._start_next_preview_exports()
        if self._preview_export_active or self._preview_export_queue:
            self.search_page.lbl_status.setText(
                self.texts.get(
                    "preview_dialog_export_queue_status",
                    "Export queued. Running: {running} | Waiting: {queued}",
                ).format(
                    running=len(self._preview_export_active),
                    queued=len(self._preview_export_queue),
                )
            )
        self._update_preview_action_button_styles()

    def _cancel_all_preview_exports(self, timeout_ms=3000):
        self._preview_export_queue.clear()
        for task in list(self._preview_export_active.values()):
            worker = task.get("worker")
            if worker is None:
                continue
            task["status"] = "cancelled"
            worker.cancel()
        for task in list(self._preview_export_active.values()):
            worker = task.get("worker")
            if worker is None:
                continue
            if not worker.wait(timeout_ms):
                return False
            try:
                worker.deleteLater()
            except Exception:
                pass
        self._preview_export_active.clear()
        self._update_preview_action_button_styles()
        return True

    def show_preview_export_tasks(self):
        total = len(self._preview_export_tasks)
        if total == 0:
            self.show_info_dialog(
                self.texts.get("preview_export_tasks_title", "Preview Export Tasks"),
                self.texts.get("preview_export_tasks_empty", "No export tasks yet."),
                kind="info",
            )
            return
        headers = self.texts.get(
            "preview_export_tasks_headers",
            ["#", "Status", "Source Video", "Start(s)", "End(s)", "Output File"],
        )
        rows = []
        for index, task in enumerate(self._preview_export_tasks, start=1):
            rows.append(
                [
                    index,
                    self._format_preview_export_status(task.get("status")),
                    os.path.basename(task.get("video_path", "")) or task.get("video_path", ""),
                    f"{float(task.get('start_sec', 0.0)):.2f}",
                    f"{float(task.get('end_sec', 0.0)):.2f}",
                    task.get("save_path", ""),
                ]
            )
        subtitle = self.texts.get(
            "preview_export_tasks_subtitle",
            "{total} tasks | running {running} | waiting {queued}",
        ).format(
            total=total,
            running=sum(1 for task in self._preview_export_tasks if task.get("status") == "running"),
            queued=sum(1 for task in self._preview_export_tasks if task.get("status") == "queued"),
        )
        ResourceTableDialog(
            parent=self,
            is_dark=self.is_dark_mode,
            language=self.language,
            title=self.texts.get("preview_export_tasks_title", "Preview Export Tasks"),
            subtitle=subtitle,
            headers=headers,
            rows=rows,
            row_payloads=self._preview_export_tasks,
            export_default_name="preview_export_tasks.json",
            stretch_column=5,
            allow_sorting=False,
            fixed_column_widths={
                0: 52,
                1: 100,
                3: 92,
                4: 92,
            },
            extra_actions=[
                {
                    "label": self.texts["details_open_selected"],
                    "object_name": "Ghost",
                    "handler": self._open_selected_preview_export_path,
                },
                {
                    "label": self.texts["details_copy_selected"],
                    "object_name": "Ghost",
                    "handler": self._copy_selected_preview_export_path,
                },
            ],
            row_double_click_handler=self._open_preview_export_payload,
        ).exec()

    def _format_preview_export_status(self, status):
        key = f"preview_export_status_{status or 'queued'}"
        return self.texts.get(key, str(status or "queued"))

    def _open_preview_export_payload(self, dialog, payload, item=None):
        output_path = str(payload.get("save_path", "")).strip()
        if not output_path:
            dialog.status_hint.setText(self.texts["details_nothing_selected"])
            return
        if os.path.exists(output_path):
            open_in_explorer(output_path)
        else:
            open_folder_in_explorer(os.path.dirname(output_path))
        dialog.status_hint.setText(output_path)

    def _open_selected_preview_export_path(self, dialog):
        selected = dialog.get_selected_payloads()
        if not selected:
            dialog.status_hint.setText(self.texts["details_nothing_selected"])
            return
        self._open_preview_export_payload(dialog, selected[0], dialog.table.currentItem())

    def _copy_selected_preview_export_path(self, dialog):
        selected = dialog.get_selected_payloads()
        if not selected:
            dialog.status_hint.setText(self.texts["details_nothing_selected"])
            return
        output_path = str(selected[0].get("save_path", "")).strip()
        if not output_path:
            dialog.status_hint.setText(self.texts["details_nothing_selected"])
            return
        QApplication.clipboard().setText(output_path)
        dialog.status_hint.setText(self.texts["details_copy_done"])

    def handle_export_clip(self, path, sec, end_sec=None):
        base_name = os.path.splitext(os.path.basename(path))[0]
        suggested_name = f"{base_name}_clip_{int(float(sec)):06d}.mp4"
        save_path, _ = QFileDialog.getSaveFileName(
            self,
            self.texts.get("export_clip_title", "\u5bfc\u51fa\u9884\u89c8\u7247\u6bb5"),
            suggested_name,
            self.texts.get("export_clip_filter", "\u89c6\u9891\u6587\u4ef6 (*.mp4 *.mkv *.mov)"),
        )
        if not save_path:
            return
        self._queue_preview_export(path, float(sec), float(end_sec if end_sec is not None else sec), save_path)

    def upload_file(self):
        path, _ = QFileDialog.getOpenFileName(self, self.texts["select_image"], "", self.texts["image_filter"])
        if path:
            self._set_image_query(path, clear_text=True)

    def apply_theme(self):
        style = DARK_STYLE if self.is_dark_mode else LIGHT_STYLE
        app = QApplication.instance()
        if app:
            app.setProperty("videoseek_is_dark", self.is_dark_mode)
            app.setStyleSheet(style)
        self.update()
        self.sidebar.btn_theme.setText(self.texts["theme_light"] if self.is_dark_mode else self.texts["theme_dark"])

    def toggle_theme(self):
        self.is_dark_mode = not self.is_dark_mode
        self.apply_theme()
        config = load_config()
        config["theme"] = "dark" if self.is_dark_mode else "light"
        save_config(config)

    def toggle_language(self):
        self.language = "en" if self.language == "zh" else "zh"
        config = load_config()
        config["language"] = self.language
        save_config(config)
        self.version_info = get_local_version_status(self.language)
        self.notice_payload = get_local_notice_payload(self.language)
        self.about_payload = get_local_about_payload(self.language)
        self.apply_texts()
        self.load_settings_values()
        self.apply_theme()
        self.app_meta_controller.refresh(self.language)

    def show_error_dialog(self, message, exc=None):
        detail = self.texts["generic_detail"].format(detail=str(exc)) if exc else ""
        text = f"{message}\n\n{detail}".strip()
        AppMessageDialog(
            self.texts["error_title"],
            text,
            kind="error",
            parent=self,
            is_dark=self.is_dark_mode,
            language=self.language,
        ).exec()

    def show_info_dialog(self, title, text, kind="info"):
        AppMessageDialog(
            title,
            text,
            kind=kind,
            parent=self,
            is_dark=self.is_dark_mode,
            language=self.language,
        ).exec()

    def show_confirm_dialog(self, title, text, kind="warning"):
        dialog = AppMessageDialog(
            title,
            text,
            kind=kind,
            parent=self,
            is_dark=self.is_dark_mode,
            language=self.language,
            confirm=True,
        )
        dialog.exec()
        return dialog.confirmed()

    def _show_startup_migration_notice(self):
        notice = pop_migration_notice()
        if not notice:
            return
        self.show_info_dialog(
            self.texts["migration_notice_title"],
            self.texts["migration_notice_body"].format(
                config_file=notice["config_file"],
                data_dir=notice["data_dir"],
            ),
            kind="info",
        )

    def _prompt_resume_partial_indexing(self):
        partial_libraries = list_partial_libraries(include_offline=False)
        if not partial_libraries or self.indexing_controller.is_running():
            return

        if len(partial_libraries) == 1:
            message = self.texts["partial_resume_body_single"].format(library=partial_libraries[0])
        else:
            message = self.texts["partial_resume_body_multi"].format(count=len(partial_libraries))

        if not self.show_confirm_dialog(
            self.texts["partial_resume_title"],
            message,
            kind="warning",
        ):
            return

        self.switch_page("library")
        self.library_page.lbl_status.setText(self.texts["partial_resume_status"])
        self.start_update_index()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if urls:
            dropped_path = urls[0].toLocalFile()
            if self.pages.currentIndex() == 1:
                self.upload_network_file_path(dropped_path)
                return
            self.upload_file_path(dropped_path)

    def upload_file_path(self, path):
        self._set_image_query(path, clear_text=False)
        self.switch_page("search")

    def upload_network_file_path(self, path):
        self._set_network_image_query(path)
        self.switch_page("link")

    def closeEvent(self, event):
        if self._preview_export_active or self._preview_export_queue:
            cancelled = self._cancel_all_preview_exports()
            if not cancelled:
                self.search_page.lbl_status.setText(
                    self.texts.get("preview_dialog_export_running", "Clip export is still running. Please wait.")
                )
                event.ignore()
                return
        if self.indexing_controller.is_running():
            self._close_when_indexing_stops = True
            self.indexing_controller.request_stop()
            self.library_page.lbl_status.setText(self.texts["index_stop_requested"])
            event.ignore()
            return
        if hasattr(self, "_preview_dialog") and self._preview_dialog is not None:
            self._preview_dialog.shutdown_player(fast=True)
        self.search_controller.shutdown()
        self.network_search_controller.shutdown()
        from ui.threading_utils import shutdown_thread

        shutdown_thread(getattr(self, "remix_worker", None))
        self.remix_worker = None
        self._stop_remix_thumbnail_loading()
        self.mobile_bridge_controller.shutdown()
        self.indexing_controller.shutdown()
        self.app_meta_controller.shutdown()
        self.runtime_resource_controller.shutdown()
        self.preview_controller.shutdown()
        event.accept()

    def _set_image_query(self, path, clear_text):
        self.current_img_path = path
        self.search_page.img_label.setPixmap(
            QPixmap(path).scaled(420, 280, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )
        if clear_text:
            self.search_page.text_search.clear()
        self.search_page.lbl_status.setText(self.texts["image_loaded"])

    def open_runtime_resource_folder(self):
        from src.services.runtime_resource_service import ensure_runtime_resource_dirs

        target_dirs = ensure_runtime_resource_dirs()
        for target_dir in target_dirs:
            open_folder_in_explorer(target_dir)

    def parse_model_packages(self, selected_files=None, scan_only=False):
        config = load_config()
        try:
            model_root = self._resolve_model_package_root(config)
            if not model_root:
                raise ValueError("Active profile model_dir is empty.")

            if selected_files is not None:
                selected_files = [str(path or "").strip() for path in (selected_files or []) if str(path or "").strip()]
            elif not scan_only:
                selected_files, _ = QFileDialog.getOpenFileNames(
                    self,
                    self.texts.get("model_upload_package", "Upload Model Package"),
                    "",
                    "Runtime Package (*.zip *.sha256 *.exe);;All Files (*.*)",
                )
                selected_files = [str(path or "").strip() for path in (selected_files or []) if str(path or "").strip()]
            else:
                selected_files = []
        except Exception as exc:
            self.show_error_dialog(self.texts.get("parse_model_package_failed", "Failed to parse model package."), exc)
            return
        ffmpeg_files = [
            path for path in selected_files
            if path.lower().endswith(".exe") and os.path.basename(path).strip().lower() == "ffmpeg.exe"
        ]
        model_files = [path for path in selected_files if not path.lower().endswith(".exe")]
        ffmpeg_updated = False
        ffmpeg_error = ""
        if ffmpeg_files:
            try:
                self._import_ffmpeg_executable(ffmpeg_files[0], config)
                ffmpeg_updated = True
            except Exception as exc:
                ffmpeg_error = str(exc)
        if ffmpeg_error:
            self.show_error_dialog(
                self.texts.get("parse_model_package_failed", "Failed to parse model package."),
                ffmpeg_error,
            )
            return
        self._ffmpeg_imported_with_package = bool(ffmpeg_updated)
        if not model_files and not scan_only:
            self.check_runtime_resources(show_dialog=False)
            dialog = self._active_model_import_dialog()
            if dialog is not None:
                status = self.runtime_resource_controller.get_status_snapshot()
                if status.get("resources_ready"):
                    dialog.set_manage_state()
                else:
                    dialog.set_missing_state(
                        status.get("display_files", []),
                        "",
                        download_enabled=bool(status.get("download_enabled", False)),
                    )
            self._update_inference_backend_hint()
            if ffmpeg_updated:
                self.show_info_dialog(
                    self.texts["success_title"],
                    self.texts.get("ffmpeg_import_done", "FFmpeg imported successfully."),
                    kind="success",
                )
            return
        self._start_model_package_import(model_root, model_files, scan_only)

    def _import_ffmpeg_executable(self, ffmpeg_file, config):
        source_path = os.path.normpath(os.path.abspath(os.fspath(ffmpeg_file)))
        if os.path.basename(source_path).strip().lower() != "ffmpeg.exe":
            raise RuntimeError("Selected executable is not ffmpeg.exe")
        if not os.path.exists(source_path):
            raise RuntimeError(f"FFmpeg file not found: {source_path}")
        target_path = os.path.normpath(get_configured_ffmpeg_target_path(config=config))
        target_dir = os.path.dirname(target_path)
        if target_dir:
            os.makedirs(target_dir, exist_ok=True)
        shutil.copy2(source_path, target_path)
        config["ffmpeg_path"] = target_path
        save_config(config)

    def _resolve_model_package_root(self, config):
        config_root = str(config.get("model_dir", "") or "").strip()
        active_root = str(get_effective_model_dir(config=config) or "").strip()
        model_root = config_root or active_root
        if not model_root:
            return ""
        model_root = os.path.normpath(os.path.abspath(os.fspath(model_root)))
        # Compatibility: if runtime.model_dir was accidentally saved as provider/variant leaf, step back to root.
        try:
            profile = get_active_model_profile(config=config)
            provider = str(profile.get("provider", "") or "").strip()
            runtime = dict(profile.get("runtime") or {})
            variant = str(runtime.get("model_variant", "") or profile.get("model_variant", "") or "").strip()
            if provider and variant:
                provider_dir = "openai-clip" if provider == "clip_onnx" else ("siglip2" if provider == "siglip2_onnx" else provider.replace("_", "-"))
                expected_tail = os.path.normcase(os.path.normpath(os.path.join(provider_dir, variant)))
                if os.path.normcase(model_root).endswith(expected_tail):
                    parent = os.path.dirname(os.path.dirname(model_root))
                    if parent:
                        model_root = parent
        except Exception:
            pass
        return model_root

    def _start_model_package_import(self, model_root, selected_files, scan_only):
        if self._model_package_import_worker and self._model_package_import_worker.isRunning():
            self.show_info_dialog(
                self.texts["warning_title"],
                self.texts.get("model_import_in_progress", "Model package import is already running."),
                kind="warning",
            )
            return
        worker = ModelPackageImportWorker(model_root, selected_files=selected_files, scan_only=scan_only)
        self._model_package_import_worker = worker
        worker.progress_signal.connect(self._on_model_package_import_progress)
        worker.finished_signal.connect(self._on_model_package_import_finished)
        worker.error_signal.connect(self._on_model_package_import_error)
        worker.finished.connect(lambda active_worker=worker: self._cleanup_model_package_import_worker(active_worker))
        self._on_model_package_import_progress(0, self.texts.get("model_download_starting", "Starting..."))
        worker.start()

    def _active_model_import_dialog(self):
        dialog = getattr(self.runtime_resource_controller, "dialog", None)
        if dialog is None or not dialog.isVisible():
            return None
        return dialog

    def _on_model_package_import_progress(self, value, text):
        dialog = self._active_model_import_dialog()
        if dialog is not None:
            dialog.set_import_progress_state(max(0, min(100, int(value))), str(text or ""))
        else:
            self.settings_page.lbl_status.setText(str(text or ""))

    def _on_model_package_import_finished(self, result):
        imported = int(result.get("imported", 0))
        updated = int(result.get("updated", 0))
        errors = [str(item) for item in result.get("errors", []) if str(item).strip()]
        checksum_verified_count = int(result.get("checksum_verified_count", 0))
        dialog = self._active_model_import_dialog()
        if imported or updated:
            self.load_settings_values()
            self.check_runtime_resources(show_dialog=False)
            message = self.texts.get("parse_model_package_done", "Model packages parsed: +{imported}, updated {updated}.").format(
                imported=imported,
                updated=updated,
            )
            if checksum_verified_count > 0:
                message = f"{message}\n\nChecksums verified: {checksum_verified_count}"
            if self._ffmpeg_imported_with_package:
                message = f"{message}\n\n{self.texts.get('ffmpeg_import_done', 'FFmpeg imported successfully.')}"
            if dialog is not None:
                dialog.set_import_success_state(
                    self.texts.get("parse_model_package_done", "Model packages parsed: +{imported}, updated {updated}.").format(
                        imported=imported,
                        updated=updated,
                    )
                )
            if errors:
                message = f"{message}\n\n" + "\n".join(errors[:3])
                self.show_info_dialog(self.texts["warning_title"], message, kind="warning")
            else:
                self.show_info_dialog(self.texts["success_title"], message, kind="success")
            self._ffmpeg_imported_with_package = False
            return
        if errors:
            if dialog is not None:
                status = self.runtime_resource_controller.get_status_snapshot()
                dialog.set_error_state(
                    "\n".join(errors[:3]),
                    status["display_files"],
                    "",
                    download_enabled=status["download_enabled"],
                )
            self.show_info_dialog(self.texts["warning_title"], "\n".join(errors[:3]), kind="warning")
            self._ffmpeg_imported_with_package = False
            return
        if dialog is not None:
            dialog.set_manage_state()
        self.show_info_dialog(
            self.texts["warning_title"],
            self.texts.get("parse_model_package_none", "No model_manifest.json found."),
            kind="warning",
        )
        self._ffmpeg_imported_with_package = False

    def _on_model_package_import_error(self, error_text):
        dialog = self._active_model_import_dialog()
        if dialog is not None:
            status = self.runtime_resource_controller.get_status_snapshot()
            dialog.set_error_state(
                str(error_text or ""),
                status["display_files"],
                "",
                download_enabled=status["download_enabled"],
            )
        self.show_error_dialog(
            self.texts.get("parse_model_package_failed", "Failed to parse model package."),
            error_text,
        )
        self._ffmpeg_imported_with_package = False

    def _cleanup_model_package_import_worker(self, worker):
        if self._model_package_import_worker is worker:
            self._model_package_import_worker = None
        try:
            worker.deleteLater()
        except Exception:
            pass

    def remove_current_model_profile(self):
        selected_profile_id = str(self.settings_page.input_active_model_profile.currentData() or "").strip()
        if not selected_profile_id:
            self.show_info_dialog(
                self.texts["warning_title"],
                self.texts.get("remove_model_profile_none", "No model profile is selected."),
                kind="warning",
            )
            return
        config = load_config()
        models = dict(config.get("models") or {})
        profiles = [item for item in models.get("profiles", []) if isinstance(item, dict)]
        remaining_after_remove = max(0, len(profiles) - 1)
        confirm_text = self.texts.get(
            "remove_model_profile_confirm",
            "Remove the current model profile and delete its model resources and model-scoped data?",
        )
        if remaining_after_remove == 0:
            confirm_text = (
                f"{confirm_text}\n\n"
                + self.texts.get(
                    "remove_model_profile_last_warning",
                    "This is the last available model profile. After removal, no model will be available until you import one.",
                )
            )
        if not self.show_confirm_dialog(self.texts["confirm_title"], confirm_text):
            return
        try:
            result = remove_model_profile(selected_profile_id)
            reset_engine()
            self.load_settings_values()
            self.check_runtime_resources(show_dialog=False)
            self._update_inference_backend_hint()
            self.refresh_library_table()
            active_profile = str(result.get("active_profile", "") or "").strip()
            removed_resource_dir = str(result.get("removed_resource_dir", "") or "").strip()
            removed_asset_dir = str(result.get("removed_asset_dir", "") or "").strip()
            summary = self.texts.get(
                "remove_model_profile_done",
                "Model removed. Active profile: {active}.",
            ).format(active=active_profile or "none")
            details = []
            if removed_resource_dir:
                details.append(f"Resource dir: {removed_resource_dir}")
            if removed_asset_dir:
                details.append(f"Data dir: {removed_asset_dir}")
            message = summary if not details else f"{summary}\n\n" + "\n".join(details)
            self.show_info_dialog(self.texts["success_title"], message, kind="success")
        except Exception as exc:
            self.show_error_dialog(
                self.texts.get("remove_model_profile_failed", "Failed to remove model profile."),
                exc,
            )

    def _update_inference_backend_hint(self):
        config = load_config()
        status = get_engine_runtime_status()
        backend_text = ""
        show_help_link = False

        if status["initialized"]:
            backend_text = status["backend"] or ""
            if status["warning"]:
                issue_text = self._build_runtime_issue_summary(status)
                if str(status.get("backend") or "").upper() == "GPU":
                    backend_text = f"{backend_text} ({issue_text})".strip()
                else:
                    backend_text = self.texts["setting_inference_cpu_issue"].format(issue=issue_text)
                show_help_link = True
                self.settings_page.hint_inference_backend.setProperty("state", "warn")
            elif str(status["backend"]).upper() == "GPU":
                self.settings_page.hint_inference_backend.setProperty("state", "ok")
            else:
                self.settings_page.hint_inference_backend.setProperty("state", "neutral")
        else:
            self.settings_page.hint_inference_backend.setProperty("state", "neutral")

        backend_label = (
            self.texts["setting_inference_backend"].format(backend=backend_text)
            if backend_text else self.texts["setting_inference_backend"].format(
                backend=self.texts["setting_inference_uninitialized"]
            )
        )
        if show_help_link:
            backend_label = f"{backend_label} | {self.texts['setting_gpu_runtime_link_only']}"
        ffmpeg_label = self.texts["setting_ffmpeg_active"].format(path=get_ffmpeg_status_text())
        data_label = self._build_data_storage_status_text(config)
        self.settings_page.set_runtime_status_texts(backend_label, ffmpeg_label, data_label)

    def _build_runtime_issue_summary(self, status):
        issue = str(status.get("issue") or "").strip()
        diagnostics = dict(status.get("diagnostics") or {})
        issue_text = self._get_runtime_issue_text(issue or diagnostics.get("issue"))

        missing_dlls = [str(item) for item in diagnostics.get("missing_dlls") or [] if str(item).strip()]
        if missing_dlls:
            return f"{issue_text}: {', '.join(missing_dlls)}"

        missing_msvc_dlls = [str(item) for item in diagnostics.get("missing_msvc_dlls") or [] if str(item).strip()]
        if missing_msvc_dlls:
            return f"{issue_text}: {', '.join(missing_msvc_dlls)}"

        available_providers = [str(item) for item in diagnostics.get("available_providers") or [] if str(item).strip()]
        if issue == "directml" and available_providers:
            return f"{issue_text}: {', '.join(available_providers)}"

        return issue_text

    def _build_runtime_diagnostics_detail(self, status):
        diagnostics = dict(status.get("diagnostics") or {})
        lines = []
        backend = str(status.get("backend") or "").strip() or self.texts.get("setting_inference_uninitialized", "Not initialized")
        lines.append(f"Backend: {backend}")
        lines.append(f"Initialized: {bool(status.get('initialized'))}")
        lines.append(f"Prefer GPU: {bool(status.get('prefer_gpu'))}")
        issue_text = self._build_runtime_issue_summary(status)
        if issue_text:
            lines.append(issue_text)

        missing_dlls = [str(item) for item in diagnostics.get("missing_dlls") or [] if str(item).strip()]
        if missing_dlls:
            lines.append(self.texts.get("setting_runtime_detail_missing_dlls", "Missing DLLs: {items}").format(items=", ".join(missing_dlls)))

        missing_msvc_dlls = [str(item) for item in diagnostics.get("missing_msvc_dlls") or [] if str(item).strip()]
        if missing_msvc_dlls:
            lines.append(self.texts.get("setting_runtime_detail_missing_msvc_dlls", "Missing VC++ DLLs: {items}").format(items=", ".join(missing_msvc_dlls)))

        available_providers = [str(item) for item in diagnostics.get("available_providers") or [] if str(item).strip()]
        if available_providers:
            lines.append(self.texts.get("setting_runtime_detail_available_providers", "Available providers: {items}").format(items=", ".join(available_providers)))

        windows_build = diagnostics.get("windows_build")
        if windows_build:
            lines.append(self.texts.get("setting_runtime_detail_windows_build", "Windows build: {value}").format(value=windows_build))

        probe_stage = str(diagnostics.get("probe_stage") or "").strip()
        if probe_stage:
            probe_stage_key = f"setting_runtime_probe_stage_{probe_stage}"
            probe_stage_text = self.texts.get(probe_stage_key, probe_stage)
            lines.append(self.texts.get("setting_runtime_detail_probe_stage", "Failure stage: {value}").format(value=probe_stage_text))

        probe_exception_type = str(diagnostics.get("probe_exception_type") or "").strip()
        probe_exception_message = str(diagnostics.get("probe_exception_message") or "").strip()
        probe_exception = ": ".join(part for part in [probe_exception_type, probe_exception_message] if part)
        if probe_exception:
            lines.append(self.texts.get("setting_runtime_detail_probe_exception", "Exception: {value}").format(value=probe_exception))

        failure_kind = str(diagnostics.get("failure_kind") or "").strip()
        if failure_kind:
            lines.append(f"Failure kind: {failure_kind}")

        active_providers = diagnostics.get("active_providers")
        if isinstance(active_providers, dict) and active_providers:
            lines.append(f"Active providers: {json.dumps(active_providers, ensure_ascii=False)}")

        return "\n".join(line for line in lines if line)

    def _build_runtime_diagnostics_payload(self, status):
        normalized_status = dict(status or {})
        return {
            "backend": normalized_status.get("backend", ""),
            "initialized": bool(normalized_status.get("initialized")),
            "prefer_gpu": normalized_status.get("prefer_gpu"),
            "issue": normalized_status.get("issue", ""),
            "warning": normalized_status.get("warning", ""),
            "summary": self._build_runtime_issue_summary(normalized_status),
            "detail": self._build_runtime_diagnostics_detail(normalized_status),
            "diagnostics": dict(normalized_status.get("diagnostics") or {}),
        }

    def _get_runtime_issue_text(self, issue):
        issue_key_map = {
            "directml": "setting_runtime_issue_directml",
            "directx": "setting_runtime_issue_directx",
            "windows": "setting_runtime_issue_windows",
            "windows_version": "setting_runtime_issue_windows_version",
            "msvc": "setting_runtime_issue_msvc",
            "probe_timeout": "setting_runtime_issue_probe_timeout",
            "probe_launch_failed": "setting_runtime_issue_probe_launch_failed",
            "visual_provider_not_activated": "setting_runtime_issue_visual_provider_not_activated",
            "text_provider_not_activated": "setting_runtime_issue_text_provider_not_activated",
            "visual_probe_failed": "setting_runtime_issue_visual_probe_failed",
            "text_probe_failed": "setting_runtime_issue_text_probe_failed",
            "session_init_failed": "setting_runtime_issue_session_init_failed",
        }
        text_key = issue_key_map.get(str(issue or "").strip(), "setting_runtime_issue_unknown")
        return self.texts.get(text_key, self.texts.get("setting_runtime_issue_unknown", "DirectML runtime"))

    def show_runtime_diagnostics(self):
        status = get_engine_runtime_status()
        payload = self._build_runtime_diagnostics_payload(status)
        lines = []
        if payload["summary"]:
            lines.append(payload["summary"])
        if payload["detail"] and payload["detail"] != payload["summary"]:
            lines.append(payload["detail"])
        if payload["warning"]:
            lines.append(payload["warning"])
        text = "\n\n".join(line for line in lines if line).strip()
        if not text:
            text = json.dumps(payload, ensure_ascii=False, indent=2)
        dialog = AppMessageDialog(
            self.texts.get("setting_show_runtime_diagnostics_title", "GPU diagnostics"),
            text,
            kind="info",
            parent=self,
            is_dark=self.is_dark_mode,
            language=self.language,
            confirm=True,
            cancel_text=self.texts["close"],
            confirm_text=self.texts.get("setting_copy_runtime_diagnostics", "Copy GPU diagnostics"),
        )
        dialog.exec()
        if dialog.confirmed():
            QApplication.clipboard().setText(json.dumps(payload, ensure_ascii=False, indent=2))
            self.settings_page.lbl_status.setText(
                self.texts.get(
                    "setting_copy_runtime_diagnostics_done",
                    self.texts.get("details_copy_done", "Copied to clipboard."),
                )
            )

    def _build_data_storage_status_text(self, config):
        normalized_config = dict(config or {})
        data_root = str(normalized_config.get("data_root", "") or "").strip()
        if data_root:
            data_root = os.path.normpath(data_root)
        else:
            data_root = get_configured_data_root(normalized_config)
        return self.texts["setting_data_active"].format(data_root=data_root)

    def _handle_runtime_resource_exit(self):
        self.startup_cancelled = True
        self.close()

    def check_runtime_resources(self, show_dialog=True):
        return self.runtime_resource_controller.check_resources(show_dialog=show_dialog)

    def start_runtime_resource_download(self):
        self.runtime_resource_controller.start_download()

    def open_runtime_resource_dialog(self):
        self.runtime_resource_controller.show_manage_dialog()

    def open_model_package_download_page(self):
        app_meta = get_app_meta()
        target_url = str(app_meta.get("model_manifest_url", "") or "").strip()
        if not target_url:
            self.show_info_dialog(
                self.texts["warning_title"],
                self.texts["download_models_unavailable"],
                kind="warning",
            )
            return
        webbrowser.open(target_url)

    def start_network_search(self):
        if not self.check_runtime_resources():
            self.link_page.lbl_search_status.setText(self.texts["model_features_disabled"])
            return
        query_text = self.link_page.input_link.text().strip()
        query_data = query_text
        is_text = True
        if query_text:
            query_info = prepare_text_query(query_text)
            if query_info["too_short"]:
                self.link_page.lbl_search_status.setText(self.texts["query_too_short"])
                return
            if query_info["changed"]:
                self.link_page.input_link.setText(query_info["normalized"])
            if query_info["generic"]:
                self.show_info_dialog(
                    self.texts["query_generic_title"],
                    self.texts["query_generic_hint"],
                    kind="info",
                )
            query_data = query_info["normalized"]
        if not query_data:
            query_data = self.network_query_img_path
            is_text = False
        if not query_data:
            self.link_page.lbl_search_status.setText(self.texts["empty_query"])
            return
        self.switch_page("link")
        self.network_search_controller.start_search(query_data, is_text)

    def upload_network_query_image(self):
        path, _ = QFileDialog.getOpenFileName(self, self.texts["select_image"], "", self.texts["image_filter"])
        if not path:
            return
        self._set_network_image_query(path)

    def _set_network_image_query(self, path):
        self.network_query_img_path = path
        self.link_page.query_image_label.setPixmap(
            QPixmap(path).scaled(420, 180, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )
        self.link_page.lbl_search_status.setText(self.texts["image_loaded"])

    def start_network_build(self):
        raw_text = self.link_page.build_links_input.toPlainText().strip()
        links = re.findall(r"https?://[^\s,]+", raw_text)
        if not links:
            self.link_page.lbl_build_status.setText(self.texts["network_link_editor_empty"])
            return
        precheck = precheck_remote_links(links)
        accepted_links = precheck.get("accepted_links", [])
        blocked_count = int(precheck.get("blocked_count", 0))
        risky_count = int(precheck.get("risky_count", 0))
        if not accepted_links:
            self.link_page.lbl_build_status.setText(
                f"{self.texts['network_precheck_all_blocked']} "
                f"({self.texts['network_precheck_summary'].format(accepted=0, blocked=blocked_count, risky=risky_count)})"
            )
            return
        mode = str(self.link_page.mode_combo.currentData() or "download")
        if blocked_count > 0 or risky_count > 0:
            self.link_page.lbl_build_status.setText(
                self.texts["network_precheck_summary"].format(
                    accepted=int(precheck.get("accepted_count", 0)),
                    blocked=blocked_count,
                    risky=risky_count,
                )
            )
        self.switch_page("link")
        self.network_search_controller.start_build(accepted_links, mode)

    def import_network_library(self):
        zip_path, _ = QFileDialog.getOpenFileName(
            self,
            self.texts["network_import_title"],
            "",
            self.texts["network_zip_filter"],
        )
        if not zip_path:
            return
        self.switch_page("link")
        try:
            self.network_search_controller.import_zip(zip_path)
        except Exception as exc:
            self.show_error_dialog(self.texts["network_import_failed"], exc)

    def export_network_library(self):
        zip_path, _ = QFileDialog.getSaveFileName(
            self,
            self.texts["network_export_title"],
            "remote_library.zip",
            self.texts["network_zip_filter"],
        )
        if not zip_path:
            return
        self.switch_page("link")
        try:
            self.network_search_controller.export_zip(zip_path)
        except Exception as exc:
            self.show_error_dialog(self.texts["network_export_failed"], exc)

    def show_local_vector_details(self):
        try:
            detail = list_local_vector_details(validate_contents=False)
            headers = self.texts["library_vectors_headers"]
            ready_state_text = self._local_vector_asset_state_text("ready")
            rows, payloads = self._build_local_vector_detail_rows(detail)
            subtitle = self.texts["library_vectors_subtitle"].format(
                total=detail["total_entries"],
                vector_dir=detail["vector_dir"],
                index_dir=detail["index_dir"],
            )
            dialog = ResourceTableDialog(
                parent=self,
                is_dark=self.is_dark_mode,
                language=self.language,
                title=self.texts["library_vectors_title"],
                subtitle=subtitle,
                headers=headers,
                rows=rows,
                row_payloads=payloads,
                export_default_name="local_vector_details.json",
                stretch_column=3,
                allow_sorting=False,
                fixed_column_widths={
                    0: 52,
                    1: 220,
                    2: 220,
                    5: 86,
                    6: 86,
                    7: 86,
                    8: 132,
                    9: 200,
                },
                issue_row_predicate=lambda row, ready_text=ready_state_text: row[8] != ready_text,
                extra_actions=[
                    {
                        "label": self.texts["details_open_selected"],
                        "object_name": "Ghost",
                        "handler": self._open_selected_vector_detail_path,
                    },
                    {
                        "label": self.texts["details_copy_selected"],
                        "object_name": "Ghost",
                        "handler": self._copy_selected_vector_detail_path,
                    },
                ],
                row_double_click_handler=self._open_vector_detail_payload,
            )
            dialog.set_summary_text(self.texts["library_vectors_validation_loading"])
            self._start_local_vector_detail_validation(dialog)
            dialog.exec()
        except Exception as exc:
            self.show_error_dialog(self.texts["library_vectors_load_failed"], exc)

    def _build_local_vector_detail_rows(self, detail):
        rows = []
        payloads = []
        for index, item in enumerate(detail["entries"], start=1):
            rows.append(
                [
                    index,
                    item["library_path"],
                    item["video_rel_path"],
                    os.path.basename(item["vector_file"]) if item.get("vector_file") else "",
                    os.path.basename(item["index_file"]) if item.get("index_file") else "",
                    self.texts["details_yes"] if item.get("source_exists") else self.texts["details_no"],
                    self.texts["details_yes"] if item["vector_exists"] else self.texts["details_no"],
                    self.texts["details_yes"] if item["index_exists"] else self.texts["details_no"],
                    self._local_vector_asset_state_text(item.get("asset_state", "")),
                    self._local_vector_failure_reason_text(item.get("sync_failure_reason", "")),
                ]
            )
            payloads.append(item)
        return rows, payloads

    def _start_local_vector_detail_validation(self, dialog):
        worker = LocalVectorDetailsWorker()
        self._local_vector_detail_worker = worker
        worker.result_ready.connect(
            lambda detail, dlg=dialog: self._finish_local_vector_detail_validation(
                dlg,
                detail,
            )
        )
        worker.error_signal.connect(
            lambda _message, dlg=dialog: self._fail_local_vector_detail_validation(dlg)
        )
        worker.finished.connect(lambda active_worker=worker: self._cleanup_local_vector_detail_worker(active_worker))
        worker.start()

    def _finish_local_vector_detail_validation(self, dialog, detail):
        if dialog is None or not dialog.isVisible():
            return
        rows, payloads = self._build_local_vector_detail_rows(detail)
        dialog.set_rows(rows, payloads)
        dialog.set_summary_text(self.texts["library_vectors_validation_done"])

    def _fail_local_vector_detail_validation(self, dialog):
        if dialog is None or not dialog.isVisible():
            return
        dialog.set_summary_text(self.texts["library_vectors_validation_failed"])

    def _cleanup_local_vector_detail_worker(self, worker):
        if self._local_vector_detail_worker is worker:
            self._local_vector_detail_worker = None
        try:
            worker.deleteLater()
        except Exception:
            pass

    def _local_vector_asset_state_text(self, asset_state):
        state_key = str(asset_state or "").strip().lower() or "ready"
        return self.texts.get(f"library_asset_state_{state_key}", state_key)

    def _local_vector_failure_reason_text(self, reason):
        reason_key = str(reason or "").strip().lower()
        if not reason_key:
            return ""
        return self.texts.get(f"library_sync_failure_reason_{reason_key}", reason_key)

    def _open_vector_detail_payload(self, dialog, payload, item=None):
        column = item.column() if item is not None else 3
        library_path = str(payload.get("library_path", "")).strip()
        video_rel_path = str(payload.get("video_rel_path", "")).strip()
        vector_file = str(payload.get("vector_file", "")).strip()
        index_file = str(payload.get("index_file", "")).strip()

        if column == 1:
            if not library_path:
                dialog.status_hint.setText(self.texts["details_nothing_selected"])
                return
            open_folder_in_explorer(library_path)
            dialog.status_hint.setText(library_path)
            return

        if column == 2:
            if not library_path or not video_rel_path:
                dialog.status_hint.setText(self.texts["details_nothing_selected"])
                return
            video_path = os.path.join(library_path, video_rel_path)
            if os.path.exists(video_path):
                open_in_explorer(video_path)
                dialog.status_hint.setText(video_path)
            else:
                open_folder_in_explorer(library_path)
                dialog.status_hint.setText(video_path)
            return

        if column == 3:
            if not vector_file:
                dialog.status_hint.setText(self.texts["details_nothing_selected"])
                return
            open_in_explorer(vector_file) if os.path.exists(vector_file) else open_folder_in_explorer(os.path.dirname(vector_file))
            dialog.status_hint.setText(vector_file)
            return

        if column == 4:
            if not index_file:
                dialog.status_hint.setText(self.texts["details_nothing_selected"])
                return
            open_in_explorer(index_file) if os.path.exists(index_file) else open_folder_in_explorer(os.path.dirname(index_file))
            dialog.status_hint.setText(index_file)

    def _open_selected_vector_detail_path(self, dialog):
        selected = dialog.get_selected_payloads()
        if not selected:
            dialog.status_hint.setText(self.texts["details_nothing_selected"])
            return
        self._open_vector_detail_payload(dialog, selected[0], dialog.table.currentItem())

    def _copy_selected_vector_detail_path(self, dialog):
        selected = dialog.get_selected_payloads()
        if not selected:
            dialog.status_hint.setText(self.texts["details_nothing_selected"])
            return
        payload = selected[0]
        target_path = payload["vector_file"] if payload.get("vector_exists") else payload["index_file"]
        QApplication.clipboard().setText(target_path)
        dialog.status_hint.setText(self.texts["details_copy_done"])

    def show_network_link_details(self):
        try:
            detail = list_remote_link_details()
            headers = self.texts["network_links_headers"]
            rows = []
            payloads = []
            for index, item in enumerate(detail["entries"], start=1):
                rows.append(
                    [
                        index,
                        item.get("title", ""),
                        item.get("source_link", "") or item.get("source_id", ""),
                        int(item.get("frames", 0)),
                        f"{float(item.get('min_time', 0.0)):.2f}",
                        f"{float(item.get('max_time', 0.0)):.2f}",
                    ]
                )
                payloads.append(item)
            subtitle = self.texts["network_links_subtitle"].format(
                links=detail["total_links"],
                vectors=detail["total_vectors"],
                vector_file=detail["vector_file"],
            )
            ResourceTableDialog(
                parent=self,
                is_dark=self.is_dark_mode,
                language=self.language,
                title=self.texts["network_links_title"],
                subtitle=subtitle,
                headers=headers,
                rows=rows,
                row_payloads=payloads,
                export_default_name="remote_link_details.json",
                stretch_column=2,
                allow_sorting=False,
                fixed_column_widths={
                    0: 52,
                    3: 86,
                    4: 116,
                    5: 116,
                },
                extra_actions=[
                    {
                        "label": self.texts["details_open_selected_link"],
                        "object_name": "Ghost",
                        "handler": self._open_selected_network_link,
                    },
                    {
                        "label": self.texts["details_copy_selected_link"],
                        "object_name": "Ghost",
                        "handler": self._copy_selected_network_link,
                    },
                ],
                row_double_click_handler=self._open_network_link_payload,
            ).exec()
        except Exception as exc:
            self.show_error_dialog(self.texts["network_links_load_failed"], exc)

    def _open_network_link_payload(self, dialog, payload, item=None):
        column = item.column() if item is not None else 2
        if column not in {1, 2}:
            return
        link = str(payload.get("source_link", "") or payload.get("source_id", "")).strip()
        if not link:
            dialog.status_hint.setText(self.texts["details_nothing_selected"])
            return
        webbrowser.open(link)
        dialog.status_hint.setText(link)

    def _open_selected_network_link(self, dialog):
        selected = dialog.get_selected_payloads()
        if not selected:
            dialog.status_hint.setText(self.texts["details_nothing_selected"])
            return
        self._open_network_link_payload(dialog, selected[0], dialog.table.currentItem())

    def _copy_selected_network_link(self, dialog):
        selected = dialog.get_selected_payloads()
        if not selected:
            dialog.status_hint.setText(self.texts["details_nothing_selected"])
            return
        link = str(selected[0].get("source_link", "") or selected[0].get("source_id", "")).strip()
        if not link:
            dialog.status_hint.setText(self.texts["details_nothing_selected"])
            return
        QApplication.clipboard().setText(link)
        dialog.status_hint.setText(self.texts["details_copy_done"])

    def open_remix_embed_cache_folder(self):
        open_folder_in_explorer(get_remix_embed_cache_dir(load_config()))

    def open_network_download_cache_folder(self):
        storage_paths = get_data_storage_paths()
        cache_dirs = [
            storage_paths["remote_build_cache_dir"],
            storage_paths["link_cache_dir"],
        ]
        for cache_dir in cache_dirs:
            if os.path.exists(cache_dir):
                open_folder_in_explorer(cache_dir)
                return
        os.makedirs(cache_dirs[0], exist_ok=True)
        open_folder_in_explorer(cache_dirs[0])

    def _finish_runtime_resource_download(self, result):
        self.check_runtime_resources(show_dialog=False)
        self.settings_page.input_model_dir.setText(result.get("model_dir", get_configured_model_dir()))
        if result.get("ffmpeg_path"):
            self.settings_page.input_ffmpeg_path.setText(result["ffmpeg_path"])
            self._update_inference_backend_hint()

    def _apply_runtime_resource_status(self, status):
        self.models_ready = status["model_ready"]
        self.search_page.btn_search.setEnabled(self.models_ready)
        self.network_search_controller.refresh_status()
        self.library_page.btn_sync_db.setEnabled(status["resources_ready"])
        if status["resources_ready"]:
            self.search_controller.start_warmup()
            self.preview_controller.start_warmup()
        if not status["resources_ready"]:
            status_text = self.texts["model_features_disabled"]
            self.search_page.lbl_status.setText(status_text)
            self.link_page.lbl_build_status.setText(status_text)
            self.link_page.lbl_search_status.setText(status_text)
            self.library_page.lbl_status.setText(status_text)
        self._update_runtime_banner(status)

    def _update_runtime_banner(self, status):
        model_ready = bool(status.get("model_ready"))
        ffmpeg_ready = bool(status.get("ffmpeg_ready"))
        if (not model_ready) and (not ffmpeg_ready):
            missing_text = self.texts.get("models_missing_generic_both", "Model and FFmpeg are not ready.")
        elif not model_ready:
            missing_text = self.texts.get("models_missing_generic_model", "Model resources are missing.")
        elif not ffmpeg_ready:
            missing_text = self.texts.get("models_missing_generic_ffmpeg", "FFmpeg is missing.")
        else:
            missing_text = self.texts.get("models_missing_generic_unknown", "Runtime resources are incomplete.")
        banner_text = self.texts.get("runtime_banner_missing", "Runtime resources are not ready: {missing}").format(missing=missing_text)
        action_text = self.texts.get("runtime_banner_open_import", "Go Import")
        for page in (self.search_page, self.link_page, self.library_page, self.settings_page):
            banner = page.header.runtime_banner
            banner_label = page.header.runtime_banner_text
            banner_btn = page.header.runtime_banner_action
            banner_btn.setText(action_text)
            if status.get("resources_ready"):
                banner.hide()
            else:
                banner_label.setText(banner_text)
                banner.show()
