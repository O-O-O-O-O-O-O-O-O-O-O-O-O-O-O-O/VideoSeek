import os
import webbrowser

from PySide6.QtCore import QEvent, Qt, QRect
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.domain.remote_search_hit import coerce_remote_search_hit
from src.domain.remix_search_hit import coerce_remix_search_hit
from src.domain.search_hit import coerce_search_hit


_SCOPE_CB_LIGHT = {
    "field": QColor("#f7f9fd"),
    "track": QColor("#dbe3ef"),
    "line": QColor("#afbed8"),
    "accent": QColor("#2f6df6"),
    "accent_hover": QColor("#4a82fb"),
}
_SCOPE_CB_DARK = {
    "field": QColor("#0f1a2b"),
    "track": QColor("#22314a"),
    "line": QColor("#40557f"),
    "accent": QColor("#4e8cff"),
    "accent_hover": QColor("#6ba0ff"),
}


def _remix_scope_cb_theme() -> dict:
    app = QApplication.instance()
    if app is not None and app.property("videoseek_is_dark"):
        return _SCOPE_CB_DARK
    return _SCOPE_CB_LIGHT


class RemixScopeCheckBox(QCheckBox):
    """Self-drawn box + tick (global QSS cannot rely on data: URLs for indicators on Windows)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("RemixScopeCheck")
        self.setMouseTracking(True)
        self.setFixedSize(24, 24)
        self.stateChanged.connect(lambda _s: self.update())

    def changeEvent(self, event):
        if event.type() in (QEvent.Type.StyleChange, QEvent.Type.PaletteChange):
            self.update()
        tc = getattr(QEvent.Type, "ThemeChange", None)
        if tc is not None and event.type() == tc:
            self.update()
        super().changeEvent(event)

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        with QPainter(self) as painter:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            theme = _remix_scope_cb_theme()
            w, h = self.width(), self.height()
            side = min(w, h, 26)
            x = (w - side) // 2
            y = (h - side) // 2
            rect = QRect(x, y, side, side)
            radius = max(5, int(side * 0.28))
            hover = self.underMouse()
            checked = self.isChecked()

            if checked:
                fill = theme["accent_hover"] if hover else theme["accent"]
                border = theme["accent_hover"]
            else:
                fill = theme["track"] if hover else theme["field"]
                border = theme["accent"] if hover else theme["line"]

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(fill)
            painter.drawRoundedRect(rect, radius, radius)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(border, 1))
            painter.drawRoundedRect(rect.adjusted(0, 0, -1, -1), radius, radius)

            if checked:
                pen = QPen(
                    QColor("#ffffff"),
                    max(1.8, side / 9.0),
                    s=Qt.PenStyle.SolidLine,
                    c=Qt.PenCapStyle.RoundCap,
                    j=Qt.PenJoinStyle.RoundJoin,
                )
                painter.setPen(pen)
                ix, iy, sw, sh = rect.x(), rect.y(), rect.width(), rect.height()
                x1, y1 = ix + sw * 0.26, iy + sh * 0.52
                x2, y2 = ix + sw * 0.42, iy + sh * 0.72
                x3, y3 = ix + sw * 0.76, iy + sh * 0.30
                painter.drawLine(round(x1), round(y1), round(x2), round(y2))
                painter.drawLine(round(x2), round(y2), round(x3), round(y3))

            if self.hasFocus():
                painter.setPen(
                    QPen(theme["accent"], 1.5, s=Qt.PenStyle.DashLine)
                )
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(self.rect().adjusted(1, 1, -2, -2), 6, 6)


def remix_scope_row_checkbox(table: QTableWidget, row: int) -> QCheckBox | None:
    """Resolve QCheckBox for remix scope table column 0 (may be wrapped for layout)."""
    w = table.cellWidget(row, 0)
    if isinstance(w, QCheckBox):
        return w
    if w is not None:
        found = w.findChildren(QCheckBox)
        if found:
            return found[0]
    return None


def build_remix_scope_checkbox_widget(video_path: str, *, checked: bool = True) -> tuple[QWidget, QCheckBox]:
    """Centered checkbox cell for remix scope table; returns (wrapper, checkbox)."""
    cb = RemixScopeCheckBox()
    cb.setProperty("video_path", video_path)
    cb.setChecked(checked)
    cb.setAccessibleName(os.path.basename(video_path) or video_path)
    cb.setCursor(Qt.PointingHandCursor)
    cb.setFocusPolicy(Qt.StrongFocus)
    cb.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
    wrap = QWidget()
    wrap.setFocusPolicy(Qt.NoFocus)
    outer = QVBoxLayout(wrap)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.setSpacing(0)
    outer.addStretch(1)
    mid = QHBoxLayout()
    mid.setContentsMargins(0, 0, 0, 0)
    mid.setSpacing(0)
    mid.addStretch(1)
    mid.addWidget(cb, 0, Qt.AlignCenter)
    mid.addStretch(1)
    outer.addLayout(mid)
    outer.addStretch(1)
    return wrap, cb


def _fallback_text(texts, key, zh_text, en_text):
    if key in texts:
        return texts[key]
    return en_text if str(texts.get("delete", "")).lower() == "delete" else zh_text


def populate_library_table(table, libraries, is_indexing, on_sync, on_remove, on_open, texts):
    table.setRowCount(0)
    table.setHorizontalHeaderLabels(texts["library_headers"])

    for index, (path, data) in enumerate(libraries.items(), start=1):
        row = table.rowCount()
        table.insertRow(row)

        order_item = QTableWidgetItem(str(index))
        order_item.setTextAlignment(Qt.AlignCenter)
        table.setItem(row, 0, order_item)

        name_item = QTableWidgetItem(path)
        name_item.setTextAlignment(Qt.AlignCenter)
        name_item.setToolTip(path)
        table.setItem(row, 1, name_item)

        status_item = QTableWidgetItem(_library_status_text(path, data, texts))
        status_item.setForeground(QColor(_library_status_color(path, data)))
        status_item.setTextAlignment(Qt.AlignCenter)
        table.setItem(row, 2, status_item)

        table.setCellWidget(row, 3, _build_library_actions(path, is_indexing, on_sync, on_remove, on_open, texts))


def populate_result_table(table, results, on_preview, on_locate, on_export, texts):
    table.setRowCount(0)
    table.setHorizontalHeaderLabels(texts["result_headers"])
    table.setUpdatesEnabled(False)

    for row, raw in enumerate(results):
        hit = coerce_search_hit(raw)
        start_sec, end_sec, score, video_path = (
            hit.start_sec,
            hit.end_sec,
            hit.score,
            hit.video_path,
        )
        table.insertRow(row)

        order_item = QTableWidgetItem(str(row + 1))
        order_item.setTextAlignment(Qt.AlignCenter)
        order_item.setData(
            Qt.UserRole,
            {
                "video_path": video_path,
                "start_sec": float(start_sec),
                "end_sec": float(end_sec),
                "score": float(score),
            },
        )
        table.setItem(row, 0, order_item)

        preview_placeholder = QLabel(texts["thumb_loading"])
        preview_placeholder.setAlignment(Qt.AlignCenter)
        table.setCellWidget(row, 1, preview_placeholder)

        name_item = QTableWidgetItem(os.path.basename(video_path))
        name_item.setTextAlignment(Qt.AlignCenter)
        name_item.setToolTip(video_path)
        table.setItem(row, 2, name_item)

        time_item = QTableWidgetItem(_format_time_range(start_sec, end_sec))
        time_item.setTextAlignment(Qt.AlignCenter)
        table.setItem(row, 3, time_item)

        mode_item = QTableWidgetItem(_result_mode_label(start_sec, end_sec, texts))
        mode_item.setTextAlignment(Qt.AlignCenter)
        table.setItem(row, 4, mode_item)

        score_item = QTableWidgetItem(f"{int(score * 100)}%")
        score_item.setTextAlignment(Qt.AlignCenter)
        table.setItem(row, 5, score_item)

        table.setCellWidget(
            row,
            6,
            _build_result_actions(video_path, start_sec, end_sec, on_preview, on_locate, on_export, texts),
        )

    table.setUpdatesEnabled(True)


def populate_remix_result_table(table, results, remix_video_path, on_compare, on_locate, on_export, texts):
    table.setRowCount(0)
    table.setColumnCount(8)
    hdr = table.horizontalHeader()
    for col in range(8):
        hdr.setSectionResizeMode(col, QHeaderView.Fixed)
    hdr.setSectionResizeMode(2, QHeaderView.Stretch)
    table.setColumnWidth(0, 46)
    table.setColumnWidth(1, 164)
    table.setColumnWidth(3, 108)
    table.setColumnWidth(4, 108)
    table.setColumnWidth(5, 56)
    table.setColumnWidth(6, 100)
    table.setColumnWidth(7, 250)
    table.setHorizontalHeaderLabels(texts["remix_result_headers"])
    table.setUpdatesEnabled(False)
    remix_path = os.fspath(remix_video_path or "").strip()

    for row, raw in enumerate(results):
        hit = coerce_remix_search_hit(raw)
        start_sec = hit.start_sec
        end_sec = hit.end_sec
        score = hit.score
        video_path = hit.video_path
        remix_start = float(hit.remix_start_sec)
        remix_end = float(hit.remix_end_sec)
        speed_k = float(getattr(hit, "speed_k", 1.0))
        match_conf = float(getattr(hit, "match_confidence", 1.0))
        table.insertRow(row)

        order_item = QTableWidgetItem(str(row + 1))
        order_item.setTextAlignment(Qt.AlignCenter)
        order_item.setData(
            Qt.UserRole,
            {
                "video_path": video_path,
                "start_sec": float(start_sec),
                "end_sec": float(end_sec),
                "score": float(score),
                "remix_start_sec": remix_start,
                "remix_end_sec": remix_end,
                "remix_video_path": remix_path,
                "speed_k": speed_k,
                "match_confidence": match_conf,
            },
        )
        table.setItem(row, 0, order_item)

        preview_placeholder = QLabel(texts["thumb_loading"])
        preview_placeholder.setAlignment(Qt.AlignCenter)
        table.setCellWidget(row, 1, preview_placeholder)

        name_item = QTableWidgetItem(os.path.basename(video_path))
        name_item.setTextAlignment(Qt.AlignCenter)
        name_item.setToolTip(video_path)
        table.setItem(row, 2, name_item)

        source_time_item = QTableWidgetItem(_format_time_range(start_sec, end_sec))
        source_time_item.setTextAlignment(Qt.AlignCenter)
        table.setItem(row, 3, source_time_item)

        remix_time_item = QTableWidgetItem(_format_time_range(remix_start, remix_end))
        remix_time_item.setTextAlignment(Qt.AlignCenter)
        table.setItem(row, 4, remix_time_item)

        speed_item = QTableWidgetItem(f"{speed_k:.2f}x")
        speed_item.setTextAlignment(Qt.AlignCenter)
        table.setItem(row, 5, speed_item)

        match_item = QTableWidgetItem(f"{int(score * 100)}% · {int(match_conf * 100)}%")
        match_item.setToolTip(
            _fallback_text(
                texts,
                "remix_match_tooltip",
                "相似度（CLIP 均值）· 线拟合置信度",
                "CLIP mean · line-fit confidence",
            )
        )
        match_item.setTextAlignment(Qt.AlignCenter)
        table.setItem(row, 6, match_item)

        table.setCellWidget(
            row,
            7,
            _build_remix_result_actions(
                remix_path,
                remix_start,
                remix_end,
                video_path,
                start_sec,
                end_sec,
                on_compare,
                on_locate,
                on_export,
                texts,
            ),
        )

    table.setUpdatesEnabled(True)


def populate_link_result_table(table, results, source_link, on_preview, on_locate, texts):
    table.setRowCount(0)
    table.setHorizontalHeaderLabels(texts["link_result_headers"])
    table.setUpdatesEnabled(False)

    for row, result in enumerate(results):
        table.insertRow(row)

        order_item = QTableWidgetItem(str(row + 1))
        order_item.setTextAlignment(Qt.AlignCenter)
        table.setItem(row, 0, order_item)

        source_time_text = _format_time_value(result["source_time"])
        source_time_item = QTableWidgetItem(source_time_text)
        source_time_item.setTextAlignment(Qt.AlignCenter)
        table.setItem(row, 1, source_time_item)

        name_item = QTableWidgetItem(os.path.basename(result["video_path"]))
        name_item.setToolTip(result["video_path"])
        name_item.setTextAlignment(Qt.AlignCenter)
        table.setItem(row, 2, name_item)

        match_time_item = QTableWidgetItem(_format_time_value(result["match_time"]))
        match_time_item.setTextAlignment(Qt.AlignCenter)
        table.setItem(row, 3, match_time_item)

        score_item = QTableWidgetItem(f"{int(result['score'] * 100)}%")
        score_item.setTextAlignment(Qt.AlignCenter)
        table.setItem(row, 4, score_item)

        link_item = QTableWidgetItem(source_link)
        link_item.setToolTip(source_link)
        table.setItem(row, 5, link_item)

        table.setCellWidget(
            row,
            6,
            _build_link_result_actions(
                video_path=result["video_path"],
                match_sec=result["match_time"],
                source_link=source_link,
                on_preview=on_preview,
                on_locate=on_locate,
                texts=texts,
            ),
        )

    table.setUpdatesEnabled(True)


def populate_network_result_table(table, results, texts):
    table.setRowCount(0)
    table.setHorizontalHeaderLabels(texts["network_result_headers"])
    table.setUpdatesEnabled(False)

    for row, raw in enumerate(results):
        hit = coerce_remote_search_hit(raw)
        table.insertRow(row)

        order_item = QTableWidgetItem(str(row + 1))
        order_item.setTextAlignment(Qt.AlignCenter)
        table.setItem(row, 0, order_item)

        title_item = QTableWidgetItem(hit.title)
        title_item.setToolTip(hit.title)
        table.setItem(row, 1, title_item)

        time_item = QTableWidgetItem(_format_time_value(hit.time_sec))
        time_item.setTextAlignment(Qt.AlignCenter)
        table.setItem(row, 2, time_item)

        score_item = QTableWidgetItem(f"{int(hit.score * 100)}%")
        score_item.setTextAlignment(Qt.AlignCenter)
        table.setItem(row, 3, score_item)

        source_link = hit.source_link
        source_item = QTableWidgetItem(source_link)
        source_item.setToolTip(source_link)
        table.setItem(row, 4, source_item)

        table.setCellWidget(row, 5, _build_network_result_actions(source_link, texts))

    table.setUpdatesEnabled(True)


def _library_status_text(path, data, texts):
    exists = os.path.exists(path)
    has_index = len(data.get("files", {})) > 0
    state = str(data.get("index_state", "")).strip().lower()
    if exists and state == "partial":
        return _fallback_text(texts, "lib_partial", "部分完成", "Partial")
    if exists and has_index:
        return texts["lib_ready"]
    if exists:
        return texts["lib_pending"]
    return _fallback_text(texts, "lib_offline", "离线/不可用", "Offline")


def _library_status_color(path, data):
    exists = os.path.exists(path)
    has_index = len(data.get("files", {})) > 0
    state = str(data.get("index_state", "")).strip().lower()
    if exists and state == "partial":
        return "#1677ff"
    if exists and has_index:
        return "#52c41a"
    if exists:
        return "#faad14"
    return "#8c8c8c"


def _build_library_actions(path, is_indexing, on_sync, on_remove, on_open, texts):
    container = QWidget()
    layout = QHBoxLayout(container)
    layout.setContentsMargins(8, 0, 8, 0)
    layout.setSpacing(10)
    layout.setAlignment(Qt.AlignCenter)

    refresh_button = QPushButton(texts["sync"])
    refresh_button.setProperty("class", "TableBtn")
    refresh_button.setFixedSize(56, 30)
    refresh_button.setCursor(Qt.PointingHandCursor)
    refresh_button.setEnabled(not is_indexing)
    refresh_button.clicked.connect(lambda _, target=path: on_sync(target))

    delete_button = QPushButton(texts["delete"])
    delete_button.setProperty("class", "TableDeleteBtn")
    delete_button.setFixedSize(56, 30)
    delete_button.setCursor(Qt.PointingHandCursor)
    delete_button.setEnabled(not is_indexing)
    delete_button.clicked.connect(lambda _, target=path: on_remove(target))

    open_button = QPushButton(texts["open_folder"])
    open_button.setProperty("class", "TableLocateBtn")
    open_button.setFixedSize(56, 30)
    open_button.setCursor(Qt.PointingHandCursor)
    open_button.clicked.connect(lambda _, target=path: on_open(target))

    layout.addWidget(refresh_button)
    layout.addWidget(open_button)
    layout.addWidget(delete_button)
    return container


def _build_result_actions(video_path, start_sec, end_sec, on_preview, on_locate, on_export, texts):
    container = QWidget()
    layout = QHBoxLayout(container)
    layout.setContentsMargins(10, 0, 10, 0)
    layout.setSpacing(12)
    layout.setAlignment(Qt.AlignCenter)

    preview_button = QPushButton(texts["preview"])
    preview_button.setProperty("class", "TableBtn")
    preview_button.setFixedSize(74, 32)
    preview_button.setCursor(Qt.PointingHandCursor)
    preview_button.setToolTip(texts["preview_tip"])
    preview_button.clicked.connect(
        lambda _, path=video_path, clip_start=start_sec, clip_end=end_sec: on_preview(path, clip_start, clip_end)
    )

    locate_button = QPushButton(texts["locate"])
    locate_button.setProperty("class", "TableLocateBtn")
    locate_button.setFixedSize(74, 32)
    locate_button.setCursor(Qt.PointingHandCursor)
    locate_button.setToolTip(texts["locate_tip"])
    locate_button.clicked.connect(lambda _, path=video_path: on_locate(path))

    export_button = QPushButton(_fallback_text(texts, "export_clip", "导出", "Export"))
    export_button.setProperty("class", "TableBtn")
    export_button.setFixedSize(74, 32)
    export_button.setCursor(Qt.PointingHandCursor)
    export_button.setToolTip(_fallback_text(texts, "export_clip_tip", "导出原画质片段", "Export original-quality clip"))
    export_button.clicked.connect(
        lambda _, path=video_path, clip_start=start_sec, clip_end=end_sec: on_export(path, clip_start, clip_end)
    )

    layout.addWidget(preview_button)
    layout.addWidget(locate_button)
    layout.addWidget(export_button)
    return container


def _build_remix_result_actions(
    remix_path,
    remix_start_sec,
    remix_end_sec,
    video_path,
    start_sec,
    end_sec,
    on_compare,
    on_locate,
    on_export,
    texts,
):
    container = QWidget()
    layout = QHBoxLayout(container)
    layout.setContentsMargins(8, 0, 8, 0)
    layout.setSpacing(6)
    layout.setAlignment(Qt.AlignCenter)

    compare_button = QPushButton(_fallback_text(texts, "remix_compare", "对比", "Compare"))
    compare_button.setProperty("class", "TableBtn")
    compare_button.setFixedSize(58, 30)
    compare_button.setCursor(Qt.PointingHandCursor)
    compare_button.setToolTip(
        _fallback_text(texts, "remix_compare_tip", "并排对比混剪片段与对应原片", "Side-by-side remix vs source clip")
    )
    compare_button.clicked.connect(
        lambda _,
        rp=remix_path,
        rs=remix_start_sec,
        re=remix_end_sec,
        sp=video_path,
        ss=start_sec,
        se=end_sec: on_compare(rp, rs, re, sp, ss, se)
    )

    locate_button = QPushButton(texts["locate"])
    locate_button.setProperty("class", "TableLocateBtn")
    locate_button.setFixedSize(58, 30)
    locate_button.setCursor(Qt.PointingHandCursor)
    locate_button.setToolTip(texts["locate_tip"])
    locate_button.clicked.connect(lambda _, path=video_path: on_locate(path))

    export_button = QPushButton(_fallback_text(texts, "export_clip", "导出", "Export"))
    export_button.setProperty("class", "TableBtn")
    export_button.setFixedSize(58, 30)
    export_button.setCursor(Qt.PointingHandCursor)
    export_button.setToolTip(_fallback_text(texts, "export_clip_tip", "导出原画质片段", "Export original-quality clip"))
    export_button.clicked.connect(
        lambda _, path=video_path, clip_start=start_sec, clip_end=end_sec: on_export(path, clip_start, clip_end)
    )

    layout.addWidget(compare_button)
    layout.addWidget(locate_button)
    layout.addWidget(export_button)
    return container


def _format_time_range(start_sec, end_sec):
    start_text = f"{int(start_sec // 60):02d}:{int(start_sec % 60):02d}"
    end_text = f"{int(end_sec // 60):02d}:{int(end_sec % 60):02d}"
    if abs(float(end_sec) - float(start_sec)) < 1e-3:
        return start_text
    return f"{start_text}-{end_text}"


def _result_mode_label(start_sec, end_sec, texts):
    if abs(float(end_sec) - float(start_sec)) < 1e-3:
        return texts["result_mode_frame"]
    return texts["result_mode_chunk"]


def _build_link_result_actions(video_path, match_sec, source_link, on_preview, on_locate, texts):
    container = QWidget()
    layout = QHBoxLayout(container)
    layout.setContentsMargins(10, 0, 10, 0)
    layout.setSpacing(8)
    layout.setAlignment(Qt.AlignCenter)

    preview_button = QPushButton(texts["preview"])
    preview_button.setProperty("class", "TableBtn")
    preview_button.setFixedSize(58, 30)
    preview_button.setCursor(Qt.PointingHandCursor)
    preview_button.clicked.connect(lambda _, path=video_path, sec=match_sec: on_preview(path, sec))

    locate_button = QPushButton(texts["locate"])
    locate_button.setProperty("class", "TableLocateBtn")
    locate_button.setFixedSize(58, 30)
    locate_button.setCursor(Qt.PointingHandCursor)
    locate_button.clicked.connect(lambda _, path=video_path: on_locate(path))

    source_button = QPushButton(texts["open_link"])
    source_button.setProperty("class", "TableBtn")
    source_button.setFixedSize(58, 30)
    source_button.setCursor(Qt.PointingHandCursor)
    source_button.clicked.connect(lambda _, link=source_link: webbrowser.open(link))

    layout.addWidget(preview_button)
    layout.addWidget(locate_button)
    layout.addWidget(source_button)
    return container


def _build_network_result_actions(source_link, texts):
    container = QWidget()
    layout = QHBoxLayout(container)
    layout.setContentsMargins(10, 0, 10, 0)
    layout.setSpacing(8)
    layout.setAlignment(Qt.AlignCenter)

    open_button = QPushButton(texts["open_link"])
    open_button.setProperty("class", "TableBtn")
    open_button.setFixedSize(90, 30)
    open_button.setCursor(Qt.PointingHandCursor)
    open_button.clicked.connect(lambda _, link=source_link: webbrowser.open(link))
    layout.addWidget(open_button)
    return container


def _format_time_value(seconds):
    seconds = max(0.0, float(seconds))
    total = int(seconds)
    mins = total // 60
    secs = total % 60
    return f"{mins:02d}:{secs:02d}"
