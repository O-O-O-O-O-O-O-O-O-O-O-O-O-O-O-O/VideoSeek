"""Side-by-side VLC preview: remix and source each play their full matched segment (remix page only)."""
from __future__ import annotations

import os

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ui.vlc_player import VlcPreviewPlayer, create_vlc_preview_instance


class RemixCompareDialog(QDialog):
    def __init__(
        self,
        parent,
        remix_path: str,
        remix_start_sec: float,
        remix_end_sec: float,
        source_path: str,
        source_start_sec: float,
        source_end_sec: float,
        texts: dict,
    ):
        super().__init__(parent)
        self.setWindowTitle(texts.get("remix_compare_dialog_title", "Compare preview"))
        self.resize(1280, 720)

        self._vlc_shutdown = False
        self._started = False
        self._compare_vlc_shutdown_complete = False
        self._shared_vlc = create_vlc_preview_instance()

        r0 = float(remix_start_sec)
        r1 = float(remix_end_sec)
        s0 = float(source_start_sec)
        s1 = float(source_end_sec)
        self._remix_path = os.fspath(remix_path)
        self._source_path = os.fspath(source_path)
        self._remix_start = r0
        self._source_start = s0
        # Each side plays its own matched span on its timeline (not truncated to the shorter clip).
        self._remix_stop = self._segment_play_end(r0, r1)
        self._source_stop = self._segment_play_end(s0, s1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        row = QHBoxLayout()
        row.setSpacing(12)

        left_col = QVBoxLayout()
        self.lbl_left = QLabel()
        self.lbl_left.setObjectName("CardHint")
        self.remix_host = QWidget()
        self.remix_host.setMinimumHeight(320)
        self.remix_host.setStyleSheet("background-color: black;")
        left_col.addWidget(self.lbl_left)
        left_col.addWidget(self.remix_host, 1)

        right_col = QVBoxLayout()
        self.lbl_right = QLabel()
        self.lbl_right.setObjectName("CardHint")
        self.source_host = QWidget()
        self.source_host.setMinimumHeight(320)
        self.source_host.setStyleSheet("background-color: black;")
        right_col.addWidget(self.lbl_right)
        right_col.addWidget(self.source_host, 1)

        row.addLayout(left_col, 1)
        row.addLayout(right_col, 1)
        layout.addLayout(row, 1)

        btn_row = QHBoxLayout()
        self.btn_play = QPushButton()
        self.btn_play.setObjectName("PrimaryButton")
        self.btn_play.setMinimumHeight(36)
        self.btn_close = QPushButton()
        self.btn_close.setObjectName("GhostButton")
        self.btn_close.setMinimumHeight(36)
        btn_row.addStretch(1)
        btn_row.addWidget(self.btn_play)
        btn_row.addWidget(self.btn_close)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        if self._shared_vlc is not None:
            self._vlc_left = VlcPreviewPlayer(self.remix_host, shared_instance=self._shared_vlc)
            self._vlc_right = VlcPreviewPlayer(self.source_host, shared_instance=self._shared_vlc)
        else:
            self._vlc_left = VlcPreviewPlayer(self.remix_host)
            self._vlc_right = VlcPreviewPlayer(self.source_host)

        self.btn_play.clicked.connect(self._play_both)
        self.btn_close.clicked.connect(self._on_close_clicked)
        self._apply_texts(texts)
        self._autoplay_timer = QTimer(self)
        self._autoplay_timer.setSingleShot(True)
        self._autoplay_timer.timeout.connect(self._try_autoplay)
        self._autoplay_timer.start(150)

    @staticmethod
    def _segment_play_end(start_sec: float, end_sec: float) -> float:
        span = float(end_sec) - float(start_sec)
        if span <= 1e-6:
            return float(start_sec) + 0.12
        return float(end_sec)

    def _apply_texts(self, texts: dict):
        self.lbl_left.setText(texts.get("remix_compare_panel_remix", "Remix"))
        self.lbl_right.setText(texts.get("remix_compare_panel_source", "Source"))
        self.btn_play.setText(texts.get("remix_compare_play", "Play"))
        self.btn_close.setText(texts.get("remix_compare_close", "Close"))

    def _on_close_clicked(self):
        self._shutdown_players()
        self.accept()

    def _try_autoplay(self):
        if self._started or self._vlc_shutdown:
            return
        self._play_both()

    def _play_both(self):
        if self._vlc_shutdown:
            return
        self._started = True
        self._vlc_left.play(self._remix_path, self._remix_start, self._remix_stop)
        self._vlc_right.play(self._source_path, self._source_start, self._source_stop)

    def _shutdown_players(self):
        self._vlc_shutdown = True
        if getattr(self, "_autoplay_timer", None) is not None:
            self._autoplay_timer.stop()
        if self._compare_vlc_shutdown_complete:
            return
        for pl in (getattr(self, "_vlc_left", None), getattr(self, "_vlc_right", None)):
            if pl is None:
                continue
            try:
                pl.shutdown()
            except Exception:
                pass
        shared = getattr(self, "_shared_vlc", None)
        if shared is not None:
            try:
                shared.release()
            except Exception:
                pass
            self._shared_vlc = None
        self._compare_vlc_shutdown_complete = True

    def done(self, result: int = 0) -> None:
        self._shutdown_players()
        super().done(result)

    def closeEvent(self, event):
        self._shutdown_players()
        super().closeEvent(event)
