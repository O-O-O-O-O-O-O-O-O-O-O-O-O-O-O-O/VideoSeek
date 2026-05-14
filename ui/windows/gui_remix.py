"""Remix Source Match wiring — extracted from MainWindow to shrink gui.py."""

from __future__ import annotations

import os
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QFileDialog, QLabel

from src.app.config import load_config
from src.services.library_service import list_local_vector_details
from src.services.remix_embedding_cache import get_remix_embed_cache_dir
from src.utils import open_folder_in_explorer
from ui.dialogs.remix_scope_editor import RemixScopeEditorDialog
from ui.playback.remix_compare_dialog import RemixCompareDialog
from ui.views.table_views import populate_remix_result_table
from ui.workers import RemixMatchWorker, ThumbLoader


class RemixGuiMixin:
    """Slots and helpers for `RemixMatchPage`; mixed into `MainWindow`."""

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

    def _refresh_remix_scope_tree(self):
        try:
            detail = list_local_vector_details(validate_contents=False)
        except Exception:
            return
        w = self.remix_page.scope_tree
        prev_paths = None
        prev_expanded = None
        if self._remix_scope_restore_selection and w.total_video_items() > 0:
            try:
                prev_paths = list(w.collect_checked_video_paths())
            except Exception:
                prev_paths = None
            try:
                prev_expanded = list(w.collect_expanded_library_paths())
            except Exception:
                prev_expanded = None
        entries = detail.get("entries", [])
        self._remix_scope_entries_cache = list(entries)
        w.refresh_from_entries(entries, checked_abs_paths=prev_paths, expanded_lib_paths=prev_expanded)
        if w.total_video_items() > 0:
            self._remix_scope_restore_selection = True
        self.remix_page._sync_remix_disclosure_headers()
        QTimer.singleShot(0, self.remix_page.scope_tree.reflow_all_lib_trees)
        self.remix_page.refresh_scope_summary(self.texts)

    def _remix_scope_select_all(self):
        w = self.remix_page.scope_tree
        total = w.total_video_items()
        if total <= 0:
            return
        t = self.texts
        title = t.get("remix_scope_select_all_confirm_title", t.get("confirm_title", ""))
        body_tpl = t.get(
            "remix_scope_select_all_confirm_body",
            "About to check {count} indexed videos. Full-library remix matching is very slow. Continue?",
        )
        if not self.show_confirm_dialog(title, body_tpl.format(count=total), kind="warning"):
            return
        w.select_all_videos()

    def _remix_scope_select_none(self):
        self.remix_page.scope_tree.select_no_videos()

    def open_remix_scope_editor(self):
        dlg = RemixScopeEditorDialog(
            self,
            self.remix_page,
            self.texts,
            is_dark=self.is_dark_mode,
            entries_cache_getter=lambda: getattr(self, "_remix_scope_entries_cache", []),
        )
        dlg.exec()
        QTimer.singleShot(0, self.remix_page.scope_tree.reflow_all_lib_trees)

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
        worker = getattr(self, "remix_worker", None)
        if worker is None or not worker.isRunning():
            return
        worker.stop()

    def start_remix_match(self):
        if not self.check_runtime_resources():
            self.remix_page.lbl_status.setText(self.texts["model_features_disabled"])
            return
        mix = self.remix_page.input_mix_path.text().strip()
        if not mix or not os.path.isfile(mix):
            self.remix_page.lbl_status.setText(self.texts["remix_mix_hint"])
            return
        scope_paths = self.remix_page.scope_tree.collect_checked_video_paths()
        if not scope_paths:
            self.remix_page.lbl_status.setText(self.texts["remix_scope_none_selected"])
            return

        self._stop_remix_thumbnail_loading()
        self.remix_page.btn_run.setEnabled(False)
        self.remix_page.btn_stop.setEnabled(False)
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
        self.remix_page.btn_stop.setEnabled(True)

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

    def open_remix_embed_cache_folder(self):
        open_folder_in_explorer(get_remix_embed_cache_dir(load_config()))
