from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QTextEdit,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ui.layout import COMPONENT_SIZES


def _fallback_text(texts, key, zh_text, en_text):
    if key in texts:
        return texts[key]
    return en_text if str(texts.get("delete", "")).lower() == "delete" else zh_text


class SamplingRuleRow(QWidget):
    def __init__(self, on_change, on_remove, parent=None):
        super().__init__(parent)
        self._on_change = on_change
        self._on_remove = on_remove

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.start_input = QLineEdit()
        self.end_input = QLineEdit()
        self.fps_input = NoWheelDoubleSpinBox()
        self.fps_input.setRange(0.01, 24.0)
        self.fps_input.setDecimals(2)
        self.fps_input.setSingleStep(0.1)
        self.btn_remove = QPushButton()
        self.btn_remove.setObjectName("GhostButton")
        self.btn_remove.setMinimumHeight(34)

        for widget, width in ((self.start_input, 92), (self.end_input, 92)):
            widget.setMinimumWidth(width)
            widget.setMaximumWidth(width + 36)
            widget.setMinimumHeight(34)

        self.fps_input.setMinimumWidth(86)
        self.fps_input.setMaximumWidth(126)
        self.fps_input.setMinimumHeight(34)

        layout.addWidget(self.start_input, 0)
        layout.addWidget(self.end_input, 0)
        layout.addWidget(self.fps_input, 0)
        layout.addWidget(self.btn_remove, 0)
        layout.addStretch(1)

        self.start_input.textChanged.connect(self._emit_change)
        self.end_input.textChanged.connect(self._emit_change)
        self.fps_input.valueChanged.connect(self._emit_change)
        self.btn_remove.clicked.connect(lambda: self._on_remove(self))

    def _emit_change(self, *_args):
        self._on_change()

    def set_texts(self, start_text, end_text, fps_value):
        self.start_input.setText(start_text)
        self.end_input.setText(end_text)
        self.fps_input.setValue(max(0.01, float(fps_value)))

    def get_rule_text(self):
        start_text = self.start_input.text().strip()
        end_text = self.end_input.text().strip()
        fps_text = f"{self.fps_input.value():.2f}".rstrip("0").rstrip(".")
        if not start_text and not end_text:
            return ""
        return f"{start_text}-{end_text}={fps_text}"


class ClickableLabel(QLabel):
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self._click_handler = None

    def set_click_handler(self, handler):
        self._click_handler = handler
        self.setCursor(Qt.PointingHandCursor)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and callable(self._click_handler) and self.rect().contains(event.position().toPoint()):
            self._click_handler()
        super().mouseReleaseEvent(event)


class _NoWheelMixin:
    def wheelEvent(self, event):
        event.ignore()


class NoWheelSpinBox(_NoWheelMixin, QSpinBox):
    pass


class NoWheelDoubleSpinBox(_NoWheelMixin, QDoubleSpinBox):
    pass


class NoWheelComboBox(_NoWheelMixin, QComboBox):
    pass


class SettingDetailPopup(QFrame):
    def __init__(self, parent=None, is_dark=True):
        super().__init__(parent, Qt.ToolTip | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setObjectName("SettingDetailPopup")
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self._anchor_label = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)

        self.title_label = QLabel()
        self.title_label.setObjectName("SettingDetailPopupTitle")
        self.title_label.setWordWrap(True)

        self.body_label = QLabel()
        self.body_label.setObjectName("SettingDetailPopupBody")
        self.body_label.setWordWrap(True)

        layout.addWidget(self.title_label)
        layout.addWidget(self.body_label)
        self.set_dark_mode(is_dark)

    def set_dark_mode(self, is_dark):
        bg = "#1b2433" if is_dark else "#ffffff"
        border = "#3a4a67" if is_dark else "#d5ddea"
        title = "#f5f8ff" if is_dark else "#121826"
        body = "#b4c0d4" if is_dark else "#5f6e84"
        shadow = "rgba(6, 12, 22, 0.28)" if is_dark else "rgba(15, 23, 42, 0.12)"
        self.setStyleSheet(
            f"""
            #SettingDetailPopup {{
                background: {bg};
                border: 1px solid {border};
                border-radius: 12px;
            }}
            #SettingDetailPopupTitle {{
                color: {title};
                font-size: 13px;
                font-weight: 700;
                background: transparent;
            }}
            #SettingDetailPopupBody {{
                color: {body};
                font-size: 12px;
                font-weight: 600;
                line-height: 1.45em;
                background: transparent;
            }}
            """
        )
        self.setGraphicsEffect(None)

    def show_for_label(self, label, title, text):
        self._anchor_label = label
        self.title_label.setText(title)
        self.body_label.setText(text)
        self.body_label.setMaximumWidth(320)
        self.adjustSize()

        anchor_global = label.mapToGlobal(label.rect().topRight())
        x = anchor_global.x() + 10
        y = anchor_global.y() - 4
        screen = label.screen()
        available = screen.availableGeometry() if screen is not None else self.screen().availableGeometry()

        if x + self.width() > available.right() - 12:
            left_anchor = label.mapToGlobal(label.rect().topLeft())
            x = left_anchor.x() - self.width() - 10
        if x < available.left() + 12:
            x = available.left() + 12
        if y + self.height() > available.bottom() - 12:
            y = max(available.top() + 12, available.bottom() - self.height() - 12)
        if y < available.top() + 12:
            y = available.top() + 12

        self.move(QPoint(x, y))
        self.show()
        self.raise_()

    def hide_and_clear(self):
        self._anchor_label = None
        self.hide()

    def eventFilter(self, watched, event):
        if not self.isVisible():
            return False
        if event.type() == QEvent.MouseButtonPress:
            global_pos = event.globalPosition().toPoint()
            if self.geometry().contains(global_pos):
                return False
            if self._anchor_label is not None:
                anchor_rect = self._anchor_label.rect()
                anchor_pos = self._anchor_label.mapFromGlobal(global_pos)
                if anchor_rect.contains(anchor_pos):
                    return False
            self.hide_and_clear()
        elif event.type() == QEvent.KeyPress and event.key() == Qt.Key_Escape:
            self.hide_and_clear()
        elif event.type() in {QEvent.Wheel, QEvent.Scroll, QEvent.ScrollPrepare}:
            self.hide_and_clear()
        elif event.type() == QEvent.WindowDeactivate:
            self.hide_and_clear()
        return False

    def closeEvent(self, event):
        self.hide_and_clear()
        super().closeEvent(event)


class NavigationSidebar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("NavSidebar")
        self.setFixedWidth(COMPONENT_SIZES["sidebar_width"])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 20, 18, 18)
        layout.setSpacing(14)

        self.title = QLabel("VideoSeek")
        self.title.setObjectName("BrandTitle")
        self.subtitle = QLabel("Local video search workspace")
        self.subtitle.setObjectName("BrandSubtitle")
        self.subtitle.setWordWrap(True)
        layout.addWidget(self.title)
        layout.addWidget(self.subtitle)

        self.hero_card = QFrame()
        self.hero_card.setObjectName("HeroCard")
        hero_layout = QVBoxLayout(self.hero_card)
        hero_layout.setContentsMargins(14, 14, 14, 14)
        hero_layout.setSpacing(6)
        self.hero_tag = QLabel("WORKSPACE")
        self.hero_tag.setObjectName("HeroTag")
        self.hero_title = QLabel("Operate search, indexing, and settings separately")
        self.hero_title.setObjectName("HeroTitle")
        self.hero_title.setWordWrap(True)
        self.hero_body = QLabel("A cleaner shell for search, libraries, and runtime controls.")
        self.hero_body.setObjectName("HeroBody")
        self.hero_body.setWordWrap(True)
        hero_layout.addWidget(self.hero_tag)
        hero_layout.addWidget(self.hero_title)
        hero_layout.addWidget(self.hero_body)
        layout.addWidget(self.hero_card)

        self.btn_page_search = self._build_nav_button("Search", checked=True)
        self.btn_page_link = self._build_nav_button("Link Match")
        self.btn_page_remix = self._build_nav_button("Remix", checked=False)
        self.btn_page_library = self._build_nav_button("Libraries")
        self.btn_page_settings = self._build_nav_button("Settings")
        layout.addWidget(self.btn_page_search)
        layout.addWidget(self.btn_page_link)
        layout.addWidget(self.btn_page_remix)
        layout.addWidget(self.btn_page_library)
        layout.addWidget(self.btn_page_settings)
        self.runtime_hint = QLabel("")
        self.runtime_hint.setObjectName("StatusLabel")
        self.runtime_hint.setWordWrap(True)
        self.runtime_hint.hide()
        layout.addWidget(self.runtime_hint)
        layout.addStretch()

        self.btn_notice = QPushButton("Notes")
        self.btn_notice.setObjectName("SecondaryButton")
        self.btn_about = QPushButton("About")
        self.btn_about.setObjectName("SecondaryButton")
        self.btn_language = QPushButton("EN")
        self.btn_language.setObjectName("GhostButton")
        self.btn_theme = QPushButton("Dark")
        self.btn_theme.setObjectName("PrimaryButton")

        for button in [self.btn_notice, self.btn_about, self.btn_language, self.btn_theme]:
            button.setCursor(Qt.PointingHandCursor)
            button.setFixedHeight(COMPONENT_SIZES["sidebar_action_height"])
            layout.addWidget(button)

    def _build_nav_button(self, text, checked=False):
        button = QPushButton(text)
        button.setObjectName("NavButton")
        button.setCheckable(True)
        button.setChecked(checked)
        button.setCursor(Qt.PointingHandCursor)
        button.setFixedHeight(COMPONENT_SIZES["nav_button_height"])
        return button

    def set_current_page(self, page_name):
        mapping = {
            "search": self.btn_page_search,
            "link": self.btn_page_link,
            "remix": self.btn_page_remix,
            "library": self.btn_page_library,
            "settings": self.btn_page_settings,
        }
        for name, button in mapping.items():
            button.setChecked(name == page_name)


class PageHeader(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("PageHeader")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(4)
        self.title = QLabel()
        self.title.setObjectName("PageTitle")
        self.subtitle = QLabel()
        self.subtitle.setObjectName("PageSubtitle")
        self.subtitle.setWordWrap(True)
        self.runtime_banner = QFrame()
        self.runtime_banner.setObjectName("RuntimeBanner")
        banner_layout = QHBoxLayout(self.runtime_banner)
        banner_layout.setContentsMargins(10, 8, 10, 8)
        banner_layout.setSpacing(8)
        self.runtime_banner_text = QLabel()
        self.runtime_banner_text.setObjectName("RuntimeBannerText")
        self.runtime_banner_text.setWordWrap(True)
        self.runtime_banner_action = QPushButton()
        self.runtime_banner_action.setObjectName("AccentGhostButton")
        self.runtime_banner_action.setMinimumHeight(30)
        banner_layout.addWidget(self.runtime_banner_text, 1)
        banner_layout.addWidget(self.runtime_banner_action, 0)
        self.runtime_banner.hide()
        layout.addWidget(self.title)
        layout.addWidget(self.subtitle)
        layout.addWidget(self.runtime_banner)


class SearchPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        self.header = PageHeader()
        root.addWidget(self.header)

        self.indexing_notice = QFrame()
        self.indexing_notice.setObjectName("RuntimeBanner")
        indexing_notice_layout = QHBoxLayout(self.indexing_notice)
        indexing_notice_layout.setContentsMargins(12, 8, 12, 8)
        indexing_notice_layout.setSpacing(8)
        self.indexing_notice_text = QLabel()
        self.indexing_notice_text.setObjectName("RuntimeBannerText")
        self.indexing_notice_text.setWordWrap(True)
        indexing_notice_layout.addWidget(self.indexing_notice_text, 1)
        self.indexing_notice.hide()
        root.addWidget(self.indexing_notice)

        self.session_card = QFrame()
        self.session_card.setObjectName("PanelCard")
        session_layout = QHBoxLayout(self.session_card)
        session_layout.setContentsMargins(18, 12, 18, 12)
        session_layout.setSpacing(12)
        self.session_title = QLabel()
        self.session_title.setObjectName("CardTitle")
        self.session_hint = QLabel()
        self.session_hint.setObjectName("CardHint")
        self.session_hint.setWordWrap(True)
        self.lbl_status = QLabel()
        self.lbl_status.setObjectName("StatusLabel")
        self.lbl_status.setWordWrap(True)
        session_layout.addWidget(self.session_title, 0)
        session_layout.addWidget(self.session_hint, 1)
        session_layout.addWidget(self.lbl_status, 1)
        root.addWidget(self.session_card)

        compare_row = QHBoxLayout()
        compare_row.setSpacing(12)

        self.query_card = QFrame()
        self.query_card.setObjectName("PanelCard")
        query_layout = QVBoxLayout(self.query_card)
        query_layout.setContentsMargins(18, 18, 18, 18)
        query_layout.setSpacing(10)

        self.controls_title = QLabel()
        self.controls_title.setObjectName("CardTitle")
        self.controls_hint = QLabel()
        self.controls_hint.setObjectName("CardHint")
        self.controls_hint.setWordWrap(True)
        self.img_label = QLabel()
        self.img_label.setObjectName("ImageDropZone")
        self.img_label.setAlignment(Qt.AlignCenter)
        self.img_label.setWordWrap(True)
        self.img_label.setFixedHeight(COMPONENT_SIZES["image_drop_min_height"])
        self.img_label.setMinimumWidth(0)
        self.img_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.text_search = QLineEdit()
        self.text_search.setObjectName("SearchInput")
        self.search_mode = QComboBox()
        self.search_mode.setObjectName("SearchModeSelect")
        self.search_mode.setFixedWidth(COMPONENT_SIZES["settings_input_width"] + 36)
        self.search_mode_label = QLabel()
        self.search_mode_label.setObjectName("CardHint")
        mode_row = QHBoxLayout()
        mode_row.setSpacing(8)
        mode_row.addWidget(self.search_mode_label)
        mode_row.addWidget(self.search_mode)
        mode_row.addStretch()

        mobile_row = QHBoxLayout()
        mobile_row.setSpacing(8)
        self.mobile_toggle_label = QLabel()
        self.mobile_toggle_label.setObjectName("CardHint")
        self.btn_mobile_toggle = QPushButton()
        self.btn_mobile_toggle.setObjectName("MobileBridgeToggle")
        self.btn_mobile_toggle.setCursor(Qt.PointingHandCursor)
        self.btn_mobile_toggle.setCheckable(True)
        self.btn_mobile_qr = QPushButton()
        self.btn_mobile_qr.setObjectName("MobileBridgeQrButton")
        mobile_row.addWidget(self.mobile_toggle_label)
        mobile_row.addWidget(self.btn_mobile_toggle)
        mobile_row.addWidget(self.btn_mobile_qr)
        mobile_row.addStretch()

        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        self.btn_search = QPushButton()
        self.btn_search.setObjectName("SearchButton")
        self.btn_clear = QPushButton()
        self.btn_clear.setObjectName("DangerGhostButton")
        action_row.addWidget(self.btn_search, 1)
        action_row.addWidget(self.btn_clear)

        query_layout.addWidget(self.controls_title)
        query_layout.addWidget(self.controls_hint)
        query_layout.addWidget(self.img_label)
        query_layout.addWidget(self.text_search)
        query_layout.addLayout(mode_row)
        query_layout.addLayout(mobile_row)
        query_layout.addLayout(action_row)

        self.preview_card = QFrame()
        self.preview_card.setObjectName("PanelCard")
        preview_layout = QVBoxLayout(self.preview_card)
        preview_layout.setContentsMargins(18, 18, 18, 18)
        preview_layout.setSpacing(10)
        preview_header = QHBoxLayout()
        preview_header.setContentsMargins(0, 0, 0, 0)
        preview_header.setSpacing(10)
        self.preview_title = QLabel()
        self.preview_title.setObjectName("CardTitle")
        preview_header.addWidget(self.preview_title, 1)
        self.preview_host = QFrame()
        self.preview_host.setObjectName("VideoContainer")
        self.preview_host.setMinimumHeight(COMPONENT_SIZES["preview_host_min_height"])
        self.preview_host_layout = QVBoxLayout(self.preview_host)
        self.preview_host_layout.setContentsMargins(6, 6, 6, 6)
        self.preview_placeholder = QLabel()
        self.preview_placeholder.setObjectName("PreviewPlaceholder")
        self.preview_placeholder.setAlignment(Qt.AlignCenter)
        self.preview_placeholder.setWordWrap(True)
        self.preview_host_layout.addWidget(self.preview_placeholder)
        preview_layout.addLayout(preview_header)
        preview_layout.addWidget(self.preview_host, 1)
        compare_row.addWidget(self.query_card, 5)
        compare_row.addWidget(self.preview_card, 7)
        root.addLayout(compare_row, 3)

        self.results_card = QFrame()
        self.results_card.setObjectName("PanelCard")
        results_layout = QVBoxLayout(self.results_card)
        results_layout.setContentsMargins(18, 18, 18, 18)
        results_layout.setSpacing(10)
        results_header = QHBoxLayout()
        results_header.setContentsMargins(0, 0, 0, 0)
        results_header.setSpacing(10)
        self.results_title = QLabel()
        self.results_title.setObjectName("CardTitle")
        self.btn_expand_preview = QPushButton()
        self.btn_expand_preview.setObjectName("GhostButton")
        self.btn_export_tasks = QPushButton()
        self.btn_export_tasks.setObjectName("GhostButton")
        results_header.addWidget(self.results_title, 1)
        results_header.addWidget(self.btn_expand_preview)
        results_header.addWidget(self.btn_export_tasks)
        self.result_table = ResultTable()
        self.result_table.setMinimumHeight(COMPONENT_SIZES["result_table_min_height"])
        results_layout.addLayout(results_header)
        results_layout.addWidget(self.result_table)
        root.addWidget(self.results_card, 4)


class LibraryPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        self.header = PageHeader()
        root.addWidget(self.header)

        self.toolbar_card = QFrame()
        self.toolbar_card.setObjectName("PanelCard")
        toolbar_card_layout = QVBoxLayout(self.toolbar_card)
        toolbar_card_layout.setContentsMargins(18, 16, 18, 16)
        toolbar_card_layout.setSpacing(10)

        def _toolbar_divider():
            divider = QFrame()
            divider.setFrameShape(QFrame.VLine)
            divider.setFrameShadow(QFrame.Plain)
            divider.setObjectName("ToolbarDivider")
            return divider

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self.btn_add_lib = QPushButton()
        self.btn_add_lib.setObjectName("UpdateButton")
        self.btn_sync_db = QPushButton()
        self.btn_sync_db.setObjectName("PrimaryButton")
        self.btn_stop_index = QPushButton()
        self.btn_stop_index.setObjectName("DangerGhostButton")
        self.btn_stop_index.setEnabled(False)
        self.btn_stop_index.setVisible(False)
        self.btn_index_issues = QPushButton()
        self.btn_index_issues.setObjectName("GhostButton")
        self.btn_index_issues.setEnabled(False)
        self.btn_cleanup_missing = QPushButton()
        self.btn_cleanup_missing.setObjectName("GhostButton")
        self.btn_vector_details = QPushButton()
        self.btn_vector_details.setObjectName("GhostButton")
        self.btn_debug_gpu_oom = QPushButton()
        self.btn_debug_gpu_oom.setObjectName("GhostButton")
        self.btn_debug_gpu_oom.setVisible(False)
        self.btn_debug_system_oom = QPushButton()
        self.btn_debug_system_oom.setObjectName("GhostButton")
        self.btn_debug_system_oom.setVisible(False)
        toolbar.addWidget(self.btn_add_lib)
        toolbar.addWidget(self.btn_sync_db)
        toolbar.addSpacing(4)
        toolbar.addWidget(_toolbar_divider())
        toolbar.addSpacing(4)
        toolbar.addWidget(self.btn_index_issues)
        toolbar.addSpacing(4)
        toolbar.addWidget(_toolbar_divider())
        toolbar.addSpacing(4)
        toolbar.addWidget(self.btn_cleanup_missing)
        toolbar.addWidget(self.btn_vector_details)
        toolbar.addWidget(self.btn_debug_gpu_oom)
        toolbar.addWidget(self.btn_debug_system_oom)
        toolbar.addStretch()
        toolbar.addWidget(self.btn_stop_index)

        progress_row = QHBoxLayout()
        progress_row.setSpacing(12)
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFixedHeight(COMPONENT_SIZES["progress_bar_height"])
        self.progress_bar.setMinimumWidth(COMPONENT_SIZES["progress_bar_min_width"])
        self.lbl_status = QLabel()
        self.lbl_status.setObjectName("StatusLabel")
        self.lbl_status.setWordWrap(True)
        progress_row.addWidget(self.progress_bar, 1)
        progress_row.addWidget(self.lbl_status, 1)

        toolbar_card_layout.addLayout(toolbar)
        toolbar_card_layout.addLayout(progress_row)
        root.addWidget(self.toolbar_card)

        self.table_card = QFrame()
        self.table_card.setObjectName("PanelCard")
        table_layout = QVBoxLayout(self.table_card)
        table_layout.setContentsMargins(18, 18, 18, 18)
        table_layout.setSpacing(10)
        self.table_title = QLabel()
        self.table_title.setObjectName("CardTitle")
        self.lib_table = QTableWidget(0, 4)
        self.lib_table.setObjectName("LibTable")
        self.lib_table.verticalHeader().setVisible(False)
        self.lib_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.lib_table.setFocusPolicy(Qt.NoFocus)
        self.lib_table.setColumnWidth(0, 42)
        self.lib_table.setColumnWidth(2, 90)
        self.lib_table.setColumnWidth(3, 206)
        self.lib_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.lib_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.lib_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Fixed)
        self.lib_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Fixed)
        self.lib_table.verticalHeader().setDefaultSectionSize(42)
        table_layout.addWidget(self.table_title)
        table_layout.addWidget(self.lib_table)
        root.addWidget(self.table_card, 1)



class LinkSearchPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        self.header = PageHeader()
        root.addWidget(self.header)

        self.notice_card = QFrame()
        self.notice_card.setObjectName("NoticeCard")
        notice_layout = QVBoxLayout(self.notice_card)
        notice_layout.setContentsMargins(16, 12, 16, 12)
        notice_layout.setSpacing(0)
        self.notice_body = QLabel()
        self.notice_body.setObjectName("NoticeBody")
        self.notice_body.setWordWrap(True)
        notice_layout.addWidget(self.notice_body)
        root.addWidget(self.notice_card)

        self.control_card = QFrame()
        self.control_card.setObjectName("PanelCard")
        control_layout = QVBoxLayout(self.control_card)
        control_layout.setContentsMargins(18, 18, 18, 18)
        control_layout.setSpacing(12)

        self.input_link = QLineEdit()
        self.input_link.setObjectName("SearchInput")
        self.query_image_label = QLabel()
        self.query_image_label.setObjectName("ImageDropZone")
        self.query_image_label.setAlignment(Qt.AlignCenter)
        self.query_image_label.setWordWrap(True)
        self.query_image_label.setFixedHeight(COMPONENT_SIZES.get("link_query_preview_min_height", 210))
        self.query_image_label.setMinimumWidth(0)
        self.query_image_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)

        mode_row = QHBoxLayout()
        mode_row.setSpacing(8)
        self.mode_label = QLabel()
        self.mode_label.setObjectName("CardHint")
        self.mode_combo = QComboBox()
        self.mode_combo.setObjectName("SearchModeSelect")
        self.mode_combo.setFixedWidth(COMPONENT_SIZES["settings_input_width"] + 72)
        self.build_links_input = QTextEdit()
        self.build_links_input.setObjectName("SearchInput")
        self.build_links_input.setMinimumHeight(140)
        mode_row.addWidget(self.mode_label)
        mode_row.addWidget(self.mode_combo)
        mode_row.addStretch()

        self.btn_build = QPushButton()
        self.btn_build.setObjectName("PrimaryButton")
        self.btn_build.setMinimumWidth(126)
        self.btn_run = QPushButton()
        self.btn_run.setObjectName("SearchButton")
        self.btn_run.setMinimumWidth(156)
        self.btn_clear = QPushButton()
        self.btn_clear.setObjectName("DangerGhostButton")
        self.btn_clear.setMinimumWidth(98)
        self.btn_import = QPushButton()
        self.btn_import.setObjectName("AccentGhostButton")
        self.btn_import.setMinimumWidth(126)
        self.btn_export = QPushButton()
        self.btn_export.setObjectName("AccentGhostButton")
        self.btn_export.setMinimumWidth(126)
        self.btn_link_details = QPushButton()
        self.btn_link_details.setObjectName("AccentGhostButton")
        self.btn_link_details.setMinimumWidth(126)
        self.btn_open_cache = QPushButton()
        self.btn_open_cache.setObjectName("AccentGhostButton")
        self.btn_open_cache.setMinimumWidth(126)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(COMPONENT_SIZES["progress_bar_height"])
        self.progress_bar.setVisible(False)

        self.build_title = QLabel()
        self.build_title.setObjectName("CardTitle")
        self.build_hint = QLabel()
        self.build_hint.setObjectName("CardHint")
        self.build_hint.setWordWrap(True)
        self.search_title = QLabel()
        self.search_title.setObjectName("CardTitle")
        self.search_hint = QLabel()
        self.search_hint.setObjectName("CardHint")
        self.search_hint.setWordWrap(True)
        self.lbl_build_status = QLabel()
        self.lbl_build_status.setObjectName("StatusLabel")
        self.lbl_build_status.setWordWrap(True)
        self.lbl_search_status = QLabel()
        self.lbl_search_status.setObjectName("StatusLabel")
        self.lbl_search_status.setWordWrap(True)

        build_utility_row = QGridLayout()
        build_utility_row.setHorizontalSpacing(8)
        build_utility_row.setVerticalSpacing(8)
        build_utility_row.addWidget(self.btn_build, 0, 0)
        build_utility_row.addWidget(self.btn_import, 0, 1)
        build_utility_row.addWidget(self.btn_export, 0, 2)
        build_utility_row.addWidget(self.btn_link_details, 1, 0)
        build_utility_row.addWidget(self.btn_open_cache, 1, 1)
        build_utility_row.setColumnStretch(0, 1)
        build_utility_row.setColumnStretch(1, 1)
        build_utility_row.setColumnStretch(2, 1)

        build_status_row = QHBoxLayout()
        build_status_row.setSpacing(12)
        build_status_row.addWidget(self.progress_bar, 2)
        build_status_row.addWidget(self.lbl_build_status, 3)

        build_panel = QWidget()
        build_layout = QVBoxLayout(build_panel)
        build_layout.setContentsMargins(0, 0, 0, 0)
        build_layout.setSpacing(10)
        build_layout.addWidget(self.build_title)
        build_layout.addWidget(self.build_hint)
        build_layout.addWidget(self.build_links_input)
        build_layout.addLayout(mode_row)
        build_layout.addLayout(build_utility_row)
        build_layout.addLayout(build_status_row)

        search_action_row = QHBoxLayout()
        search_action_row.setSpacing(8)
        search_action_row.addWidget(self.btn_run, 1)
        search_action_row.addWidget(self.btn_clear)

        search_panel = QWidget()
        search_layout = QVBoxLayout(search_panel)
        search_layout.setContentsMargins(0, 0, 0, 0)
        search_layout.setSpacing(10)
        search_layout.addWidget(self.search_title)
        search_layout.addWidget(self.search_hint)
        search_layout.addWidget(self.input_link)
        search_layout.addWidget(self.query_image_label)
        search_layout.addLayout(search_action_row)
        search_layout.addWidget(self.lbl_search_status)

        section_row = QHBoxLayout()
        section_row.setSpacing(16)
        section_row.addWidget(build_panel, 1)
        section_row.addWidget(search_panel, 1)

        control_layout.addLayout(section_row)
        self.controls_title = self.build_title
        self.controls_hint = self.build_hint
        self.lbl_status = self.lbl_search_status
        root.addWidget(self.control_card)

        self.results_card = QFrame()
        self.results_card.setObjectName("PanelCard")
        results_layout = QVBoxLayout(self.results_card)
        results_layout.setContentsMargins(18, 18, 18, 18)
        results_layout.setSpacing(10)
        self.results_title = QLabel()
        self.results_title.setObjectName("CardTitle")
        self.result_table = LinkResultTable()
        self.result_table.setMinimumHeight(COMPONENT_SIZES["result_table_min_height"])
        results_layout.addWidget(self.results_title)
        results_layout.addWidget(self.result_table)
        root.addWidget(self.results_card, 1)


class LinkResultTable(QTableWidget):
    def __init__(self, parent=None):
        super().__init__(0, 6, parent)
        self.setObjectName("ResultTable")
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(72)
        self.setAlternatingRowColors(False)
        self.setFocusPolicy(Qt.NoFocus)
        self.setShowGrid(False)
        self.horizontalHeader().setStretchLastSection(False)
        self.setColumnWidth(0, 46)
        self.setColumnWidth(2, 90)
        self.setColumnWidth(3, 74)
        self.setColumnWidth(4, 300)
        self.setColumnWidth(5, 116)
        self.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.horizontalHeader().setSectionResizeMode(2, QHeaderView.Fixed)
        self.horizontalHeader().setSectionResizeMode(3, QHeaderView.Fixed)
        self.horizontalHeader().setSectionResizeMode(4, QHeaderView.Fixed)
        self.horizontalHeader().setSectionResizeMode(5, QHeaderView.Fixed)


class RemixMatchPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        self.header = PageHeader()
        root.addWidget(self.header)

        spin_w = max(104, COMPONENT_SIZES.get("settings_input_width", 116) + 8)

        def make_divider():
            line = QFrame()
            line.setObjectName("RemixSectionDivider")
            line.setFrameShape(QFrame.HLine)
            line.setFrameShadow(QFrame.Plain)
            line.setFixedHeight(1)
            return line

        self.match_card = QFrame()
        self.match_card.setObjectName("PanelCard")
        match_layout = QVBoxLayout(self.match_card)
        match_layout.setContentsMargins(18, 18, 18, 18)
        match_layout.setSpacing(12)

        self.mix_label = QLabel()
        self.mix_label.setObjectName("CardTitle")
        self.mix_hint = QLabel()
        self.mix_hint.setObjectName("CardHint")
        self.mix_hint.setWordWrap(True)
        mix_row = QHBoxLayout()
        mix_row.setSpacing(8)
        self.input_mix_path = QLineEdit()
        self.input_mix_path.setObjectName("SearchInput")
        self.btn_browse_mix = QPushButton()
        self.btn_browse_mix.setObjectName("AccentGhostButton")
        self.btn_browse_mix.setMinimumWidth(100)
        mix_row.addWidget(self.input_mix_path, 1)
        mix_row.addWidget(self.btn_browse_mix, 0)

        self.section_params_title = QLabel()
        self.section_params_title.setObjectName("CardTitle")

        params = QGridLayout()
        params.setHorizontalSpacing(14)
        params.setVerticalSpacing(10)
        params.setColumnStretch(4, 1)
        self.lbl_sample_fps = QLabel()
        self.lbl_sample_fps.setObjectName("CardHint")
        self.input_sample_fps = NoWheelDoubleSpinBox()
        self.input_sample_fps.setRange(0.1, 12.0)
        self.input_sample_fps.setDecimals(2)
        self.input_sample_fps.setSingleStep(0.1)
        self.input_sample_fps.setValue(1.0)
        self.lbl_score = QLabel()
        self.lbl_score.setObjectName("CardHint")
        self.input_score_threshold = NoWheelDoubleSpinBox()
        self.input_score_threshold.setRange(0.05, 0.99)
        self.input_score_threshold.setDecimals(2)
        self.input_score_threshold.setSingleStep(0.02)
        self.input_score_threshold.setValue(0.26)
        self.lbl_gap = QLabel()
        self.lbl_gap.setObjectName("CardHint")
        self.input_merge_gap = NoWheelDoubleSpinBox()
        self.input_merge_gap.setRange(0.2, 30.0)
        self.input_merge_gap.setDecimals(1)
        self.input_merge_gap.setSingleStep(0.5)
        self.input_merge_gap.setValue(2.5)
        self.lbl_min_seg = QLabel()
        self.lbl_min_seg.setObjectName("CardHint")
        self.input_min_segment = NoWheelDoubleSpinBox()
        self.input_min_segment.setRange(0.0, 120.0)
        self.input_min_segment.setDecimals(1)
        self.input_min_segment.setSingleStep(0.5)
        self.input_min_segment.setValue(1.5)
        self.lbl_remix_cluster = QLabel()
        self.lbl_remix_cluster.setObjectName("CardHint")
        self.input_remix_cluster_gap = NoWheelDoubleSpinBox()
        self.input_remix_cluster_gap.setRange(0.1, 90.0)
        self.input_remix_cluster_gap.setDecimals(1)
        self.input_remix_cluster_gap.setSingleStep(0.5)
        self.input_remix_cluster_gap.setValue(2.5)
        self.lbl_faiss_top_k = QLabel()
        self.lbl_faiss_top_k.setObjectName("CardHint")
        self.input_faiss_top_k = NoWheelSpinBox()
        self.input_faiss_top_k.setRange(1, 200)
        self.input_faiss_top_k.setValue(48)
        self.lbl_speed_min = QLabel()
        self.lbl_speed_min.setObjectName("CardHint")
        self.input_speed_min = NoWheelDoubleSpinBox()
        self.input_speed_min.setRange(0.05, 3.0)
        self.input_speed_min.setDecimals(2)
        self.input_speed_min.setSingleStep(0.05)
        self.input_speed_min.setValue(0.25)
        self.lbl_speed_max = QLabel()
        self.lbl_speed_max.setObjectName("CardHint")
        self.input_speed_max = NoWheelDoubleSpinBox()
        self.input_speed_max.setRange(0.5, 12.0)
        self.input_speed_max.setDecimals(2)
        self.input_speed_max.setSingleStep(0.1)
        self.input_speed_max.setValue(4.0)
        self.lbl_ransac_iters = QLabel()
        self.lbl_ransac_iters.setObjectName("CardHint")
        self.input_ransac_iters = NoWheelSpinBox()
        self.input_ransac_iters.setRange(32, 8000)
        self.input_ransac_iters.setSingleStep(32)
        self.input_ransac_iters.setValue(384)
        self.lbl_min_line_pts = QLabel()
        self.lbl_min_line_pts.setObjectName("CardHint")
        self.input_min_line_points = NoWheelSpinBox()
        self.input_min_line_points.setRange(2, 60)
        self.input_min_line_points.setValue(2)
        for spin in (
            self.input_sample_fps,
            self.input_score_threshold,
            self.input_merge_gap,
            self.input_min_segment,
            self.input_remix_cluster_gap,
            self.input_faiss_top_k,
            self.input_speed_min,
            self.input_speed_max,
            self.input_ransac_iters,
            self.input_min_line_points,
        ):
            spin.setMinimumWidth(spin_w)
        params.addWidget(self.lbl_sample_fps, 0, 0)
        params.addWidget(self.input_sample_fps, 0, 1)
        params.addWidget(self.lbl_score, 0, 2)
        params.addWidget(self.input_score_threshold, 0, 3)
        params.addWidget(self.lbl_gap, 1, 0)
        params.addWidget(self.input_merge_gap, 1, 1)
        params.addWidget(self.lbl_min_seg, 1, 2)
        params.addWidget(self.input_min_segment, 1, 3)
        params.addWidget(self.lbl_remix_cluster, 2, 0)
        params.addWidget(self.input_remix_cluster_gap, 2, 1)
        params.addWidget(self.lbl_faiss_top_k, 2, 2)
        params.addWidget(self.input_faiss_top_k, 2, 3)
        params.addWidget(self.lbl_speed_min, 3, 0)
        params.addWidget(self.input_speed_min, 3, 1)
        params.addWidget(self.lbl_speed_max, 3, 2)
        params.addWidget(self.input_speed_max, 3, 3)
        params.addWidget(self.lbl_ransac_iters, 4, 0)
        params.addWidget(self.input_ransac_iters, 4, 1)
        params.addWidget(self.lbl_min_line_pts, 4, 2)
        params.addWidget(self.input_min_line_points, 4, 3)

        self.remix_params_guide = QLabel()
        self.remix_params_guide.setObjectName("CardHint")
        self.remix_params_guide.setWordWrap(True)
        self.remix_params_guide.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.btn_open_remix_cache = QPushButton()
        self.btn_open_remix_cache.setObjectName("AccentGhostButton")
        self.btn_open_remix_cache.setMinimumWidth(120)

        guide_panel = QFrame()
        guide_panel.setObjectName("SubPanelCard")
        guide_layout = QVBoxLayout(guide_panel)
        guide_layout.setContentsMargins(14, 12, 14, 12)
        guide_layout.setSpacing(10)
        guide_layout.addWidget(self.remix_params_guide)
        remix_cache_btn_row = QHBoxLayout()
        remix_cache_btn_row.addStretch(1)
        remix_cache_btn_row.addWidget(self.btn_open_remix_cache)
        guide_layout.addLayout(remix_cache_btn_row)

        match_layout.addWidget(self.mix_label)
        match_layout.addWidget(self.mix_hint)
        match_layout.addLayout(mix_row)
        match_layout.addWidget(make_divider())
        match_layout.addWidget(self.section_params_title)
        match_layout.addLayout(params)
        match_layout.addWidget(make_divider())
        match_layout.addWidget(guide_panel)
        root.addWidget(self.match_card)

        self.scope_card = QFrame()
        self.scope_card.setObjectName("PanelCard")
        scope_layout = QVBoxLayout(self.scope_card)
        scope_layout.setContentsMargins(18, 18, 18, 18)
        scope_layout.setSpacing(12)

        self.scope_title = QLabel()
        self.scope_title.setObjectName("CardTitle")
        self.scope_group = QButtonGroup(self)
        self.radio_scope_all = QRadioButton()
        self.radio_scope_restricted = QRadioButton()
        self.scope_group.addButton(self.radio_scope_all, 0)
        self.scope_group.addButton(self.radio_scope_restricted, 1)
        self.radio_scope_all.setChecked(True)
        scope_radio_row = QHBoxLayout()
        scope_radio_row.setSpacing(16)
        scope_radio_row.addWidget(self.radio_scope_all)
        scope_radio_row.addWidget(self.radio_scope_restricted)
        scope_radio_row.addStretch(1)
        self.scope_table_hint = QLabel()
        self.scope_table_hint.setObjectName("CardHint")
        self.scope_table_hint.setWordWrap(True)
        scope_tool_row = QHBoxLayout()
        scope_tool_row.setSpacing(8)
        self.btn_scope_all = QPushButton()
        self.btn_scope_all.setObjectName("GhostButton")
        self.btn_scope_none = QPushButton()
        self.btn_scope_none.setObjectName("GhostButton")
        scope_tool_row.addWidget(self.btn_scope_all)
        scope_tool_row.addWidget(self.btn_scope_none)
        scope_tool_row.addStretch(1)
        self.scope_table = QTableWidget(0, 3)
        self.scope_table.setObjectName("LibTable")
        self.scope_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.scope_table.verticalHeader().setVisible(False)
        self.scope_table.setAlternatingRowColors(False)
        self.scope_table.setShowGrid(False)
        self.scope_table.setMinimumHeight(180)
        self.scope_table.horizontalHeader().setStretchLastSection(False)
        _ssh = self.scope_table.horizontalHeader()
        _ssh.setSectionResizeMode(0, QHeaderView.Fixed)
        _ssh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        _ssh.setSectionResizeMode(2, QHeaderView.Stretch)
        self.scope_table.setColumnWidth(0, 64)
        self.scope_table.verticalHeader().setDefaultSectionSize(44)

        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        self.btn_run = QPushButton()
        self.btn_run.setObjectName("PrimaryButton")
        self.btn_run.setMinimumWidth(140)
        self.btn_stop = QPushButton()
        self.btn_stop.setObjectName("DangerGhostButton")
        self.btn_stop.setMinimumWidth(100)
        self.btn_stop.setEnabled(False)
        self.btn_clear = QPushButton()
        self.btn_clear.setObjectName("GhostButton")
        action_row.addWidget(self.btn_run)
        action_row.addWidget(self.btn_stop)
        action_row.addWidget(self.btn_clear)
        action_row.addStretch(1)
        self.lbl_status = QLabel()
        self.lbl_status.setObjectName("StatusLabel")
        self.lbl_status.setWordWrap(True)

        scope_layout.addWidget(self.scope_title)
        scope_layout.addLayout(scope_radio_row)
        scope_layout.addWidget(self.scope_table_hint)
        scope_layout.addLayout(scope_tool_row)
        scope_layout.addWidget(self.scope_table)
        scope_layout.addWidget(make_divider())
        scope_layout.addLayout(action_row)
        scope_layout.addWidget(self.lbl_status)
        root.addWidget(self.scope_card)

        self.results_card = QFrame()
        self.results_card.setObjectName("PanelCard")
        results_layout = QVBoxLayout(self.results_card)
        results_layout.setContentsMargins(18, 18, 18, 18)
        results_layout.setSpacing(10)
        self.results_title = QLabel()
        self.results_title.setObjectName("CardTitle")
        self.result_table = ResultTable()
        self.result_table.setMinimumHeight(min(440, COMPONENT_SIZES["result_table_min_height"]))
        self.result_table.setColumnWidth(7, 250)
        results_layout.addWidget(self.results_title)
        results_layout.addWidget(self.result_table)
        root.addWidget(self.results_card, 1)


class SettingsPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        self.header = PageHeader()
        root.addWidget(self.header)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        root.addWidget(self.scroll, 1)

        self.scroll_content = QWidget()
        self.scroll.setWidget(self.scroll_content)
        content_layout = QVBoxLayout(self.scroll_content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(12)

        self.form_card = QFrame()
        self.form_card.setObjectName("PanelCard")
        form_layout = QVBoxLayout(self.form_card)
        form_layout.setContentsMargins(18, 18, 18, 18)
        form_layout.setSpacing(16)
        content_layout.addWidget(self.form_card)
        content_layout.addStretch()

        self.general_title = QLabel()
        self.general_title.setObjectName("CardTitle")
        form_layout.addWidget(self.general_title)

        self.runtime_status_card = QFrame()
        self.runtime_status_card.setObjectName("SubPanelCard")
        runtime_status_layout = QVBoxLayout(self.runtime_status_card)
        runtime_status_layout.setContentsMargins(14, 12, 14, 12)
        runtime_status_layout.setSpacing(8)
        self.runtime_status_title = QLabel()
        self.runtime_status_title.setObjectName("CardTitle")
        self.runtime_status_header = QWidget()
        runtime_status_header_layout = QHBoxLayout(self.runtime_status_header)
        runtime_status_header_layout.setContentsMargins(0, 0, 0, 0)
        runtime_status_header_layout.setSpacing(8)
        self.runtime_status_backend = QLabel()
        self.runtime_status_backend.setObjectName("StatusHint")
        self.runtime_status_backend.setWordWrap(True)
        self.runtime_status_backend.setTextFormat(Qt.RichText)
        self.runtime_status_backend.setTextInteractionFlags(Qt.TextBrowserInteraction)
        self.runtime_status_backend.setOpenExternalLinks(True)
        self.btn_show_runtime_diagnostics = QPushButton()
        self.btn_show_runtime_diagnostics.setObjectName("AccentGhostButton")
        self.btn_show_runtime_diagnostics.setMinimumHeight(30)
        self.btn_show_runtime_diagnostics.setMinimumWidth(150)
        self.runtime_status_ffmpeg = QLabel()
        self.runtime_status_ffmpeg.setObjectName("StatusHint")
        self.runtime_status_ffmpeg.setWordWrap(True)
        self.runtime_status_data = QLabel()
        self.runtime_status_data.setObjectName("StatusHint")
        self.runtime_status_data.setWordWrap(True)
        runtime_status_header_layout.addWidget(self.runtime_status_title, 0)
        runtime_status_header_layout.addStretch(1)
        runtime_status_header_layout.addWidget(self.btn_show_runtime_diagnostics, 0)
        runtime_status_layout.addWidget(self.runtime_status_header)
        runtime_status_layout.addWidget(self.runtime_status_backend)
        runtime_status_layout.addWidget(self.runtime_status_ffmpeg)
        runtime_status_layout.addWidget(self.runtime_status_data)
        form_layout.addWidget(self.runtime_status_card)

        self.input_fps = NoWheelDoubleSpinBox()
        self.input_fps.setRange(0.01, 24.0)
        self.input_fps.setDecimals(2)
        self.input_fps.setSingleStep(0.1)
        self.input_sampling_fps_mode = NoWheelComboBox()
        self.input_sampling_fps_rules = QLineEdit(self)
        self.input_top_k = NoWheelSpinBox()
        self.input_top_k.setRange(1, 200)
        self.input_frame_neighbor_rerank_enabled = NoWheelComboBox()
        self.input_frame_neighbor_rerank_top_n = NoWheelSpinBox()
        self.input_frame_neighbor_rerank_top_n.setRange(1, 100)
        self.input_frame_neighbor_rerank_window = NoWheelSpinBox()
        self.input_frame_neighbor_rerank_window.setRange(1, 12)
        self.input_preview_seconds = NoWheelSpinBox()
        self.input_preview_seconds.setRange(2, 20)
        self.input_preview_width = NoWheelSpinBox()
        self.input_preview_width.setRange(160, 1920)
        self.input_preview_height = NoWheelSpinBox()
        self.input_preview_height.setRange(90, 1080)
        self.input_thumb_width = NoWheelSpinBox()
        self.input_thumb_width.setRange(80, 480)
        self.input_thumb_height = NoWheelSpinBox()
        self.input_thumb_height.setRange(45, 320)
        self.input_remote_max_frames = NoWheelSpinBox()
        self.input_remote_max_frames.setRange(200, 20000)
        self.input_embedding_batch_size = NoWheelSpinBox()
        self.input_embedding_batch_size.setRange(1, 64)
        self.input_similarity_threshold = NoWheelDoubleSpinBox()
        self.input_similarity_threshold.setRange(0.1, 1.0)
        self.input_similarity_threshold.setSingleStep(0.01)
        self.input_similarity_threshold.setDecimals(2)
        self.input_max_chunk_duration = NoWheelDoubleSpinBox()
        self.input_max_chunk_duration.setRange(1.0, 60.0)
        self.input_max_chunk_duration.setSingleStep(0.5)
        self.input_max_chunk_duration.setDecimals(1)
        self.input_min_chunk_size = NoWheelSpinBox()
        self.input_min_chunk_size.setRange(1, 50)
        self.input_chunk_similarity_mode = NoWheelComboBox()
        self.input_prefer_gpu = NoWheelComboBox()
        self.input_gpu_probe_unknown_keep_gpu = NoWheelComboBox()
        self.input_auto_cleanup_missing_files = NoWheelComboBox()
        self.input_active_model_profile = NoWheelComboBox()
        self.btn_download_runtime_resources = QPushButton()
        self.btn_remove_model_profile = QPushButton()
        self.input_data_root = QLineEdit()
        self.btn_browse_data_root = QPushButton()
        self.input_ffmpeg_path = QLineEdit()
        self.btn_browse_ffmpeg_path = QPushButton()
        self.input_model_dir = QLineEdit()
        self.btn_browse_model_dir = QPushButton()
        self.btn_migrate_model_dir = QPushButton()
        self.section_search_title = QLabel()
        self.section_preview_title = QLabel()
        self.section_index_title = QLabel()
        self.section_runtime_title = QLabel()
        self.label_fps = ClickableLabel()
        self.label_top_k = ClickableLabel()
        self.label_frame_neighbor_rerank_enabled = ClickableLabel()
        self.label_frame_neighbor_rerank_top_n = ClickableLabel()
        self.label_frame_neighbor_rerank_window = ClickableLabel()
        self.label_preview_seconds = ClickableLabel()
        self.label_preview_width = ClickableLabel()
        self.label_preview_height = ClickableLabel()
        self.label_thumb_width = ClickableLabel()
        self.label_thumb_height = ClickableLabel()
        self.label_remote_max_frames = ClickableLabel()
        self.label_embedding_batch_size = ClickableLabel()
        self.label_similarity_threshold = ClickableLabel()
        self.label_max_chunk_duration = ClickableLabel()
        self.label_min_chunk_size = ClickableLabel()
        self.label_chunk_similarity_mode = ClickableLabel()
        self.label_prefer_gpu = ClickableLabel()
        self.label_gpu_probe_unknown_keep_gpu = ClickableLabel()
        self.label_auto_cleanup_missing_files = ClickableLabel()
        self.label_active_model_profile = ClickableLabel()
        self.label_data_root = ClickableLabel()
        self.label_ffmpeg_path = ClickableLabel()
        self.label_model_dir = ClickableLabel()
        self.hint_fps = QLabel()
        self.hint_sampling_fps_mode = QLabel()
        self.hint_sampling_fps_rules = QLabel()
        self.hint_sampling_fps_preview = QLabel()
        self.sampling_rules_summary = QLabel()
        self.btn_edit_sampling_rules = QPushButton()
        self.hint_top_k = QLabel()
        self.hint_frame_neighbor_rerank_enabled = QLabel()
        self.hint_frame_neighbor_rerank_top_n = QLabel()
        self.hint_frame_neighbor_rerank_window = QLabel()
        self.hint_preview_seconds = QLabel()
        self.hint_preview_width = QLabel()
        self.hint_preview_height = QLabel()
        self.hint_thumb_width = QLabel()
        self.hint_thumb_height = QLabel()
        self.hint_remote_max_frames = QLabel()
        self.hint_embedding_batch_size = QLabel()
        self.hint_similarity_threshold = QLabel()
        self.hint_max_chunk_duration = QLabel()
        self.hint_min_chunk_size = QLabel()
        self.hint_chunk_similarity_mode = QLabel()
        self.hint_prefer_gpu = QLabel()
        self.hint_gpu_probe_unknown_keep_gpu = QLabel()
        self.hint_auto_cleanup_missing_files = QLabel()
        self.hint_active_model_profile = QLabel()
        self.hint_data_root = QLabel()
        self.hint_ffmpeg_path = QLabel()
        self.hint_ffmpeg_active = QLabel()
        self.hint_inference_backend = QLabel()
        self.hint_gpu_runtime = QLabel()
        self.hint_model_dir = QLabel()
        self.sampling_rule_rows = []
        self._setting_detail_bindings = []
        self._active_setting_label = None
        self.detail_popup = SettingDetailPopup(is_dark=True)
        QApplication.instance().installEventFilter(self.detail_popup)

        self._configure_setting_input(self.input_fps, width=94)
        self._configure_setting_input(self.input_sampling_fps_mode, width=136)
        self._configure_setting_input(self.input_top_k, width=COMPONENT_SIZES["settings_input_width"])
        self._configure_setting_input(
            self.input_frame_neighbor_rerank_enabled,
            width=COMPONENT_SIZES["settings_input_width"] + 36,
        )
        self._configure_setting_input(
            self.input_frame_neighbor_rerank_top_n,
            width=COMPONENT_SIZES["settings_input_width"],
        )
        self._configure_setting_input(
            self.input_frame_neighbor_rerank_window,
            width=COMPONENT_SIZES["settings_input_width"],
        )
        self._configure_setting_input(self.input_preview_seconds, width=COMPONENT_SIZES["settings_input_width"])
        self._configure_setting_input(self.input_preview_width, width=COMPONENT_SIZES["settings_input_width"])
        self._configure_setting_input(self.input_preview_height, width=COMPONENT_SIZES["settings_input_width"])
        self._configure_setting_input(self.input_thumb_width, width=COMPONENT_SIZES["settings_input_width"])
        self._configure_setting_input(self.input_thumb_height, width=COMPONENT_SIZES["settings_input_width"])
        self._configure_setting_input(self.input_remote_max_frames, width=COMPONENT_SIZES["settings_input_width"])
        self._configure_setting_input(self.input_embedding_batch_size, width=COMPONENT_SIZES["settings_input_width"])
        self._configure_setting_input(self.input_similarity_threshold, width=COMPONENT_SIZES["settings_input_width"])
        self._configure_setting_input(self.input_max_chunk_duration, width=COMPONENT_SIZES["settings_input_width"])
        self._configure_setting_input(self.input_min_chunk_size, width=COMPONENT_SIZES["settings_input_width"])
        self._configure_setting_input(self.input_chunk_similarity_mode, width=COMPONENT_SIZES["settings_input_width"] + 36)
        self._configure_setting_input(self.input_prefer_gpu, width=COMPONENT_SIZES["settings_input_width"] + 36)
        self._configure_setting_input(self.input_gpu_probe_unknown_keep_gpu, width=COMPONENT_SIZES["settings_input_width"] + 36)
        self._configure_setting_input(self.input_auto_cleanup_missing_files, width=COMPONENT_SIZES["settings_input_width"] + 36)
        self._configure_setting_input(self.input_active_model_profile, width=COMPONENT_SIZES["settings_input_width"] + 120)
        self.btn_download_runtime_resources.setObjectName("AccentGhostButton")
        self.btn_download_runtime_resources.setMinimumHeight(34)
        self.btn_remove_model_profile.setObjectName("DangerGhostButton")
        self.btn_remove_model_profile.setMinimumHeight(34)
        self._configure_setting_input(self.input_data_root, width=COMPONENT_SIZES["settings_path_input_width"], expanding=True)
        self._configure_setting_input(self.input_ffmpeg_path, width=COMPONENT_SIZES["settings_path_input_width"], expanding=True)
        self._configure_setting_input(self.input_model_dir, width=COMPONENT_SIZES["settings_path_input_width"], expanding=True)
        self.btn_browse_data_root.setObjectName("AccentGhostButton")
        self.btn_browse_data_root.setMinimumHeight(34)
        self.btn_browse_ffmpeg_path.setObjectName("AccentGhostButton")
        self.btn_browse_ffmpeg_path.setMinimumHeight(34)
        self.btn_browse_model_dir.setObjectName("SuccessGhostButton")
        self.btn_browse_model_dir.setMinimumHeight(34)
        self.btn_migrate_model_dir.setObjectName("AccentGhostButton")
        self.btn_migrate_model_dir.setMinimumHeight(34)

        self.input_data_root_bundle = QWidget()
        input_data_root_bundle_layout = QHBoxLayout(self.input_data_root_bundle)
        input_data_root_bundle_layout.setContentsMargins(0, 0, 0, 0)
        input_data_root_bundle_layout.setSpacing(8)
        input_data_root_bundle_layout.addWidget(self.input_data_root, 1)
        input_data_root_bundle_layout.addWidget(self.btn_browse_data_root, 0)

        self.input_ffmpeg_path_bundle = QWidget()
        input_ffmpeg_path_bundle_layout = QHBoxLayout(self.input_ffmpeg_path_bundle)
        input_ffmpeg_path_bundle_layout.setContentsMargins(0, 0, 0, 0)
        input_ffmpeg_path_bundle_layout.setSpacing(8)
        input_ffmpeg_path_bundle_layout.addWidget(self.input_ffmpeg_path, 1)
        input_ffmpeg_path_bundle_layout.addWidget(self.btn_browse_ffmpeg_path, 0)

        self.input_model_dir_bundle = QWidget()
        input_model_dir_bundle_layout = QHBoxLayout(self.input_model_dir_bundle)
        input_model_dir_bundle_layout.setContentsMargins(0, 0, 0, 0)
        input_model_dir_bundle_layout.setSpacing(8)
        self.model_dir_buttons_row = QWidget()
        model_dir_buttons_layout = QHBoxLayout(self.model_dir_buttons_row)
        model_dir_buttons_layout.setContentsMargins(0, 0, 0, 0)
        model_dir_buttons_layout.setSpacing(8)
        model_dir_buttons_layout.addWidget(self.btn_browse_model_dir, 0)
        model_dir_buttons_layout.addWidget(self.btn_migrate_model_dir, 0)
        input_model_dir_bundle_layout.addWidget(self.input_model_dir, 1)
        input_model_dir_bundle_layout.addWidget(self.model_dir_buttons_row, 0)

        self.input_active_model_profile_bundle = QWidget()
        active_model_profile_bundle_layout = QHBoxLayout(self.input_active_model_profile_bundle)
        active_model_profile_bundle_layout.setContentsMargins(0, 0, 0, 0)
        active_model_profile_bundle_layout.setSpacing(8)
        active_model_profile_bundle_layout.addWidget(self.input_active_model_profile, 1)
        active_model_profile_bundle_layout.addWidget(self.btn_download_runtime_resources, 0)
        active_model_profile_bundle_layout.addWidget(self.btn_remove_model_profile, 0)

        self.sections_stack = QVBoxLayout()
        self.sections_stack.setContentsMargins(0, 0, 0, 0)
        self.sections_stack.setSpacing(12)
        form_layout.addLayout(self.sections_stack)

        for hint_label in (
            self.hint_sampling_fps_mode,
            self.hint_sampling_fps_rules,
            self.hint_sampling_fps_preview,
        ):
            hint_label.setObjectName("StatusHint")
            hint_label.setWordWrap(True)
        self.sampling_rules_summary.setObjectName("StatusHint")
        self.sampling_rules_summary.setWordWrap(False)

        self.input_sampling_bundle = QWidget()
        self.input_sampling_bundle.setObjectName("SamplingBundle")
        sampling_bundle_layout = QHBoxLayout(self.input_sampling_bundle)
        sampling_bundle_layout.setContentsMargins(0, 0, 0, 0)
        sampling_bundle_layout.setSpacing(8)
        sampling_bundle_layout.addWidget(self.input_sampling_fps_mode, 0)
        sampling_bundle_layout.addWidget(self.input_fps, 0)
        self.btn_edit_sampling_rules.setObjectName("AccentGhostButton")
        sampling_bundle_layout.addWidget(self.btn_edit_sampling_rules, 0)
        self.sampling_rules_summary.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        sampling_bundle_layout.addWidget(self.sampling_rules_summary, 1)
        self.input_sampling_fps_rules.hide()

        self.section_search_card, self.section_search_form = self._create_settings_section(self.section_search_title)
        self.section_preview_card, self.section_preview_form = self._create_settings_section(self.section_preview_title)
        self.section_index_card, self.section_index_form = self._create_settings_section(self.section_index_title)
        self.section_runtime_card, self.section_runtime_form = self._create_settings_section(self.section_runtime_title)
        self._add_setting_row(
            self.section_search_form,
            0,
            self.label_fps,
            self.input_sampling_bundle,
            self.hint_fps,
            show_help=False,
        )
        self._add_setting_row(self.section_search_form, 1, self.label_top_k, self.input_top_k, self.hint_top_k)
        self._add_setting_row(
            self.section_search_form,
            2,
            self.label_frame_neighbor_rerank_enabled,
            self.input_frame_neighbor_rerank_enabled,
            self.hint_frame_neighbor_rerank_enabled,
        )
        self.frame_neighbor_rerank_top_n_row = self._add_setting_row(
            self.section_search_form,
            3,
            self.label_frame_neighbor_rerank_top_n,
            self.input_frame_neighbor_rerank_top_n,
            self.hint_frame_neighbor_rerank_top_n,
        )
        self.frame_neighbor_rerank_window_row = self._add_setting_row(
            self.section_search_form,
            4,
            self.label_frame_neighbor_rerank_window,
            self.input_frame_neighbor_rerank_window,
            self.hint_frame_neighbor_rerank_window,
        )
        self._add_setting_row(
            self.section_search_form,
            5,
            self.label_remote_max_frames,
            self.input_remote_max_frames,
            self.hint_remote_max_frames,
        )

        self._add_setting_row(self.section_preview_form, 0, self.label_preview_seconds, self.input_preview_seconds, self.hint_preview_seconds)
        self._add_setting_row(self.section_preview_form, 1, self.label_preview_width, self.input_preview_width, self.hint_preview_width)
        self._add_setting_row(self.section_preview_form, 2, self.label_preview_height, self.input_preview_height, self.hint_preview_height)
        self._add_setting_row(self.section_preview_form, 3, self.label_thumb_width, self.input_thumb_width, self.hint_thumb_width)
        self._add_setting_row(self.section_preview_form, 4, self.label_thumb_height, self.input_thumb_height, self.hint_thumb_height)

        self._add_setting_row(self.section_index_form, 0, self.label_embedding_batch_size, self.input_embedding_batch_size, self.hint_embedding_batch_size)
        self._add_setting_row(self.section_index_form, 1, self.label_similarity_threshold, self.input_similarity_threshold, self.hint_similarity_threshold)
        self._add_setting_row(self.section_index_form, 2, self.label_max_chunk_duration, self.input_max_chunk_duration, self.hint_max_chunk_duration)
        self._add_setting_row(self.section_index_form, 3, self.label_min_chunk_size, self.input_min_chunk_size, self.hint_min_chunk_size)
        self._add_setting_row(self.section_index_form, 4, self.label_chunk_similarity_mode, self.input_chunk_similarity_mode, self.hint_chunk_similarity_mode)

        self._add_setting_row(
            self.section_runtime_form,
            0,
            self.label_prefer_gpu,
            self.input_prefer_gpu,
            self.hint_prefer_gpu,
        )
        self._add_setting_row(
            self.section_runtime_form,
            1,
            self.label_gpu_probe_unknown_keep_gpu,
            self.input_gpu_probe_unknown_keep_gpu,
            self.hint_gpu_probe_unknown_keep_gpu,
        )
        self._add_setting_row(
            self.section_runtime_form,
            2,
            self.label_auto_cleanup_missing_files,
            self.input_auto_cleanup_missing_files,
            self.hint_auto_cleanup_missing_files,
        )
        self._add_setting_row(
            self.section_runtime_form,
            3,
            self.label_active_model_profile,
            self.input_active_model_profile_bundle,
            self.hint_active_model_profile,
        )
        self._add_setting_row(
            self.section_runtime_form,
            4,
            self.label_data_root,
            self.input_data_root_bundle,
            self.hint_data_root,
        )
        self._add_setting_row(
            self.section_runtime_form,
            5,
            self.label_ffmpeg_path,
            self.input_ffmpeg_path_bundle,
            self.hint_ffmpeg_path,
        )
        self._add_setting_row(
            self.section_runtime_form,
            6,
            self.label_model_dir,
            self.input_model_dir_bundle,
            self.hint_model_dir,
            label_vcenter=True,
        )

        self.sections_stack.addWidget(self.section_search_card)
        self.sections_stack.addWidget(self.section_preview_card)
        self.sections_stack.addWidget(self.section_index_card)
        self.sections_stack.addWidget(self.section_runtime_card)

        self.action_card = QFrame()
        self.action_card.setObjectName("PanelCard")
        action_card_layout = QVBoxLayout(self.action_card)
        action_card_layout.setContentsMargins(18, 14, 18, 14)
        action_card_layout.setSpacing(10)

        action_primary_row = QHBoxLayout()
        action_primary_row.setSpacing(8)
        self.btn_save = QPushButton()
        self.btn_save.setObjectName("PrimaryButton")
        self.btn_reset = QPushButton()
        self.btn_reset.setObjectName("GhostButton")
        action_primary_row.addWidget(self.btn_save)
        action_primary_row.addWidget(self.btn_reset)
        action_primary_row.addStretch()
        action_card_layout.addLayout(action_primary_row)

        action_cleanup_row = QHBoxLayout()
        action_cleanup_row.setSpacing(8)
        self.btn_cleanup_old_data_root = QPushButton()
        self.btn_cleanup_old_data_root.setObjectName("DangerGhostButton")
        self.btn_cleanup_old_data_root.hide()
        self.btn_cleanup_old_model_dir = QPushButton()
        self.btn_cleanup_old_model_dir.setObjectName("DangerGhostButton")
        self.btn_cleanup_old_model_dir.hide()
        action_cleanup_row.addWidget(self.btn_cleanup_old_data_root)
        action_cleanup_row.addWidget(self.btn_cleanup_old_model_dir)
        action_cleanup_row.addStretch()
        action_card_layout.addLayout(action_cleanup_row)

        self.lbl_status = QLabel()
        self.lbl_status.setObjectName("StatusLabel")
        self.lbl_status.setWordWrap(True)
        action_card_layout.addWidget(self.lbl_status)
        root.addWidget(self.action_card, 0)
        self.input_sampling_fps_mode.currentIndexChanged.connect(self._handle_sampling_mode_changed)
        self.input_frame_neighbor_rerank_enabled.currentIndexChanged.connect(
            self._handle_frame_neighbor_rerank_enabled_changed
        )
        self._update_sampling_mode_visibility()
        self._update_frame_neighbor_rerank_visibility()

    def _handle_sampling_mode_changed(self, *_args):
        self._update_sampling_mode_visibility()

    def _handle_frame_neighbor_rerank_enabled_changed(self, *_args):
        self._update_frame_neighbor_rerank_visibility()

    def _update_sampling_mode_visibility(self):
        is_dynamic = self.get_sampling_fps_mode() == "dynamic"
        self.input_fps.setVisible(not is_dynamic)
        self.btn_edit_sampling_rules.setVisible(is_dynamic)
        self.sampling_rules_summary.setVisible(is_dynamic)
        self.hint_fps.setVisible(False)
        self.hint_sampling_fps_mode.setVisible(False)
        self.hint_sampling_fps_rules.setVisible(False)
        self.hint_sampling_fps_preview.setVisible(False)

    def _update_frame_neighbor_rerank_visibility(self):
        enabled = bool(self.input_frame_neighbor_rerank_enabled.currentData())
        if hasattr(self, "frame_neighbor_rerank_top_n_row"):
            self.frame_neighbor_rerank_top_n_row.setVisible(enabled)
        if hasattr(self, "frame_neighbor_rerank_window_row"):
            self.frame_neighbor_rerank_window_row.setVisible(enabled)

    def get_sampling_fps_mode(self):
        return str(self.input_sampling_fps_mode.currentData() or "fixed")

    def set_sampling_fps_mode(self, mode):
        normalized_mode = str(mode or "fixed")
        index = self.input_sampling_fps_mode.findData(normalized_mode)
        self.input_sampling_fps_mode.setCurrentIndex(0 if index < 0 else index)
        self._update_sampling_mode_visibility()

    def set_sampling_fps_rules_text(self, rules_text):
        self.input_sampling_fps_rules.setText(str(rules_text or "").strip())
        self.refresh_sampling_rules_summary()

    def get_sampling_fps_rules_text(self):
        return self.input_sampling_fps_rules.text().strip()

    def set_sampling_rules_error_state(self, has_error):
        if has_error:
            self.sampling_rules_summary.setStyleSheet("color: #d9534f;")
            return
        self.sampling_rules_summary.setStyleSheet("")

    def refresh_sampling_rules_summary(self):
        normalized = self.get_sampling_fps_rules_text()
        if not normalized:
            self.sampling_rules_summary.setText("")
            return
        parts = []
        for chunk in normalized.split(";"):
            item = chunk.strip()
            if item:
                parts.append(item)
        self.sampling_rules_summary.setText(" | ".join(parts[:3]) + (" ..." if len(parts) > 3 else ""))

    def _configure_setting_input(self, widget, width, expanding=False):
        widget.setMinimumWidth(width)
        widget.setMaximumWidth(16777215 if expanding else width + 44)
        widget.setMinimumHeight(34)
        widget.setSizePolicy(QSizePolicy.Expanding if expanding else QSizePolicy.Fixed, QSizePolicy.Fixed)
        widget.setProperty("settingField", True)

    def _configure_setting_label(self, label):
        label.setMinimumWidth(140)
        label.setMaximumWidth(210)
        label.setMinimumHeight(40)
        label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        label.setWordWrap(True)
        label.setProperty("settingLabel", True)

    def _create_settings_section(self, title_label):
        card = QFrame()
        card.setObjectName("SubPanelCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        title_label.setObjectName("CardTitle")
        title_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        title_wrap = QWidget()
        title_wrap.setObjectName("SettingsSectionHeader")
        title_wrap_layout = QHBoxLayout(title_wrap)
        title_wrap_layout.setContentsMargins(16, 14, 16, 14)
        title_wrap_layout.setSpacing(0)
        title_wrap_layout.addWidget(title_label)
        title_wrap_layout.addStretch()
        layout.addWidget(title_wrap)
        form = QGridLayout()
        form.setContentsMargins(16, 4, 16, 8)
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(0)
        form.setColumnMinimumWidth(0, 260)
        form.setColumnStretch(0, 0)
        form.setColumnStretch(1, 1)
        layout.addLayout(form)
        return card, form

    def _add_setting_row(
        self,
        grid,
        row,
        label,
        field,
        hint_label,
        *extra_hint_labels,
        show_help=True,
        label_vcenter=False,
    ):
        row_widget = self._build_setting_row(field)
        label_block = self._build_setting_label_block(label, hint_label, extra_hint_labels)
        row_container = QWidget()
        row_container.setObjectName("SettingRowContainer")
        row_layout = QGridLayout(row_container)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setHorizontalSpacing(16)
        row_layout.setVerticalSpacing(0)
        row_layout.setColumnMinimumWidth(0, 260)
        row_layout.setColumnStretch(0, 0)
        row_layout.setColumnStretch(1, 1)
        label_alignment = Qt.AlignLeft | (Qt.AlignVCenter if label_vcenter else Qt.AlignTop)
        row_layout.addWidget(label_block, 0, 0, label_alignment)
        row_layout.addWidget(row_widget, 0, 1)
        grid.addWidget(row_container, row, 0, 1, 2)
        return row_container

    def _build_setting_label_block(self, label, hint_label, extra_hint_labels):
        block = QWidget()
        block.setObjectName("SettingLabelBlock")
        layout = QVBoxLayout(block)
        layout.setContentsMargins(0, 10, 0, 10)
        layout.setSpacing(0)
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(6)
        title_row.addWidget(label, 1)
        layout.addLayout(title_row)
        self._bind_setting_detail(label, hint_label, extra_hint_labels)
        return block

    def _build_setting_detail_text(self, hint_label, extra_hint_labels):
        message_parts = []
        hint_text = hint_label.text().strip() if hint_label is not None else ""
        if hint_text:
            message_parts.append(hint_text)
        for extra_hint in extra_hint_labels:
            if extra_hint is None:
                continue
            extra_text = extra_hint.text().strip()
            if extra_text:
                message_parts.append(extra_text)
        return "\n\n".join(message_parts)

    def _bind_setting_detail(self, label, hint_label, extra_hint_labels):
        self._setting_detail_bindings.append((label, hint_label, extra_hint_labels))
        label.set_click_handler(
            lambda l=label, h=hint_label, e=extra_hint_labels: self._activate_setting_detail(l, h, e)
        )

    def _activate_setting_detail(self, label, hint_label, extra_hint_labels):
        detail_text = self._build_setting_detail_text(hint_label, extra_hint_labels)
        if not detail_text:
            return
        self._active_setting_label = label
        for current_label, _, _ in self._setting_detail_bindings:
            current_label.setStyleSheet("font-weight: 700; color: #3b82f6;" if current_label is label else "")
        self.detail_popup.set_dark_mode(getattr(self.window(), "is_dark_mode", True))
        self.detail_popup.show_for_label(label, label.text().strip(), detail_text)

    def _build_setting_row(self, field):
        row = QWidget()
        row.setObjectName("SettingRow")
        layout = QVBoxLayout(row)
        layout.setContentsMargins(0, 8, 0, 8)
        layout.setSpacing(0)
        field_row = QHBoxLayout()
        field_row.setContentsMargins(0, 0, 0, 0)
        field_row.setSpacing(0)
        stretch = 1 if field.sizePolicy().horizontalPolicy() == QSizePolicy.Expanding else 0
        field_row.addWidget(field, stretch, Qt.AlignLeft)
        if not stretch:
            field_row.addStretch(1)
        layout.addLayout(field_row)
        return row

    def configure_form_labels(self, texts):
        self._current_texts = texts
        self.section_search_title.setText(_fallback_text(texts, "settings_section_search", "检索与采样", "Search & Sampling"))
        self.section_preview_title.setText(_fallback_text(texts, "settings_section_preview", "预览与缩略图", "Preview & Thumbnails"))
        self.section_index_title.setText(_fallback_text(texts, "settings_section_indexing", "索引与分段", "Indexing & Chunking"))
        self.section_runtime_title.setText(_fallback_text(texts, "settings_section_runtime", "运行时与资源", "Runtime & Resources"))
        self.runtime_status_title.setText(_fallback_text(texts, "settings_runtime_status", "当前运行状态", "Current Runtime"))
        self.label_fps.setText(texts["setting_fps"])
        current_mode = self.get_sampling_fps_mode()
        self.input_sampling_fps_mode.blockSignals(True)
        self.input_sampling_fps_mode.clear()
        self.input_sampling_fps_mode.addItem(texts["setting_sampling_fps_mode_fixed"], "fixed")
        self.input_sampling_fps_mode.addItem(texts["setting_sampling_fps_mode_dynamic"], "dynamic")
        restore_index = self.input_sampling_fps_mode.findData(current_mode)
        self.input_sampling_fps_mode.setCurrentIndex(0 if restore_index < 0 else restore_index)
        self.input_sampling_fps_mode.blockSignals(False)
        self.input_sampling_fps_rules.setPlaceholderText(texts["setting_sampling_fps_rules_placeholder"])
        self.btn_edit_sampling_rules.setText(texts["setting_sampling_fps_rules_edit"])
        self.refresh_sampling_rules_summary()
        self.label_top_k.setText(texts["setting_top_k"])
        self.label_frame_neighbor_rerank_enabled.setText(texts["setting_frame_neighbor_rerank_enabled"])
        self.label_frame_neighbor_rerank_top_n.setText(texts["setting_frame_neighbor_rerank_top_n"])
        self.label_frame_neighbor_rerank_window.setText(texts["setting_frame_neighbor_rerank_window"])
        self.label_preview_seconds.setText(texts["setting_preview_seconds"])
        self.label_preview_width.setText(texts["setting_preview_width"])
        self.label_preview_height.setText(texts["setting_preview_height"])
        self.label_thumb_width.setText(texts["setting_thumb_width"])
        self.label_thumb_height.setText(texts["setting_thumb_height"])
        self.label_remote_max_frames.setText(texts["setting_remote_max_frames"])
        self.label_embedding_batch_size.setText(texts["setting_embedding_batch_size"])
        self.label_similarity_threshold.setText(texts["setting_similarity_threshold"])
        self.label_max_chunk_duration.setText(texts["setting_max_chunk_duration"])
        self.label_min_chunk_size.setText(texts["setting_min_chunk_size"])
        self.label_chunk_similarity_mode.setText(texts["setting_chunk_similarity_mode"])
        self.label_prefer_gpu.setText(texts["setting_prefer_gpu"])
        self.label_gpu_probe_unknown_keep_gpu.setText(texts["setting_gpu_probe_unknown_keep_gpu"])
        self.label_auto_cleanup_missing_files.setText(texts["setting_auto_cleanup_missing_files"])
        self.label_active_model_profile.setText(
            _fallback_text(texts, "setting_active_model_profile", "当前模型", "Active Model")
        )
        current_chunk_similarity_mode = self.input_chunk_similarity_mode.currentData()
        self.input_chunk_similarity_mode.blockSignals(True)
        self.input_chunk_similarity_mode.clear()
        self.input_chunk_similarity_mode.addItem(texts["setting_chunk_similarity_mode_chunk"], "chunk")
        self.input_chunk_similarity_mode.addItem(texts["setting_chunk_similarity_mode_frame"], "frame")
        restore_index = self.input_chunk_similarity_mode.findData(current_chunk_similarity_mode)
        self.input_chunk_similarity_mode.setCurrentIndex(0 if restore_index < 0 else restore_index)
        self.input_chunk_similarity_mode.blockSignals(False)
        current_prefer_gpu = self.input_prefer_gpu.currentData()
        self.input_prefer_gpu.blockSignals(True)
        self.input_prefer_gpu.clear()
        self.input_prefer_gpu.addItem(texts["setting_prefer_gpu_option_gpu"], True)
        self.input_prefer_gpu.addItem(texts["setting_prefer_gpu_option_cpu"], False)
        restore_index = self.input_prefer_gpu.findData(current_prefer_gpu)
        self.input_prefer_gpu.setCurrentIndex(0 if restore_index < 0 else restore_index)
        self.input_prefer_gpu.blockSignals(False)
        current_gpu_probe_unknown_keep_gpu = self.input_gpu_probe_unknown_keep_gpu.currentData()
        self.input_gpu_probe_unknown_keep_gpu.blockSignals(True)
        self.input_gpu_probe_unknown_keep_gpu.clear()
        self.input_gpu_probe_unknown_keep_gpu.addItem(texts["setting_gpu_probe_unknown_keep_gpu_option_off"], False)
        self.input_gpu_probe_unknown_keep_gpu.addItem(texts["setting_gpu_probe_unknown_keep_gpu_option_on"], True)
        restore_index = self.input_gpu_probe_unknown_keep_gpu.findData(current_gpu_probe_unknown_keep_gpu)
        self.input_gpu_probe_unknown_keep_gpu.setCurrentIndex(0 if restore_index < 0 else restore_index)
        self.input_gpu_probe_unknown_keep_gpu.blockSignals(False)
        current_auto_cleanup_missing_files = self.input_auto_cleanup_missing_files.currentData()
        self.input_auto_cleanup_missing_files.blockSignals(True)
        self.input_auto_cleanup_missing_files.clear()
        self.input_auto_cleanup_missing_files.addItem(texts["setting_auto_cleanup_missing_files_option_off"], False)
        self.input_auto_cleanup_missing_files.addItem(texts["setting_auto_cleanup_missing_files_option_on"], True)
        restore_index = self.input_auto_cleanup_missing_files.findData(current_auto_cleanup_missing_files)
        self.input_auto_cleanup_missing_files.setCurrentIndex(0 if restore_index < 0 else restore_index)
        self.input_auto_cleanup_missing_files.blockSignals(False)
        current_neighbor_rerank_enabled = self.input_frame_neighbor_rerank_enabled.currentData()
        self.input_frame_neighbor_rerank_enabled.blockSignals(True)
        self.input_frame_neighbor_rerank_enabled.clear()
        self.input_frame_neighbor_rerank_enabled.addItem(texts["setting_frame_neighbor_rerank_enabled_option_off"], False)
        self.input_frame_neighbor_rerank_enabled.addItem(texts["setting_frame_neighbor_rerank_enabled_option_on"], True)
        restore_index = self.input_frame_neighbor_rerank_enabled.findData(current_neighbor_rerank_enabled)
        self.input_frame_neighbor_rerank_enabled.setCurrentIndex(0 if restore_index < 0 else restore_index)
        self.input_frame_neighbor_rerank_enabled.blockSignals(False)
        self.label_data_root.setText(texts["setting_data_root"])
        self.btn_browse_data_root.setText(texts["browse_data_root"])
        self.btn_browse_ffmpeg_path.setText(texts["browse_file"])
        self.btn_browse_model_dir.setText(texts["browse_folder"])
        self.btn_migrate_model_dir.setText(texts["migrate_model_root"])
        self.btn_download_runtime_resources.setText(texts.get("import_runtime_resources", texts["download_models"]))
        self.btn_remove_model_profile.setText(
            texts.get("remove_model_profile", "Remove Current Model")
        )
        self.btn_cleanup_old_data_root.setText(texts["cleanup_old_data_root"])
        self.btn_cleanup_old_model_dir.setText(texts["cleanup_old_model_dir"])
        self.label_ffmpeg_path.setText(texts["setting_ffmpeg_path"])
        self.label_model_dir.setText(texts["setting_model_dir"])
        self.hint_fps.setText(texts["setting_fps_hint"])
        self.hint_sampling_fps_mode.setText(texts["setting_sampling_fps_mode_hint"])
        self.hint_sampling_fps_rules.setText(texts["setting_sampling_fps_rules_hint"])
        self.hint_sampling_fps_preview.setText(texts["setting_sampling_fps_preview"])
        self.hint_top_k.setText(texts["setting_top_k_hint"])
        self.hint_frame_neighbor_rerank_enabled.setText(texts["setting_frame_neighbor_rerank_enabled_hint"])
        self.hint_frame_neighbor_rerank_top_n.setText(texts["setting_frame_neighbor_rerank_top_n_hint"])
        self.hint_frame_neighbor_rerank_window.setText(texts["setting_frame_neighbor_rerank_window_hint"])
        self.hint_preview_seconds.setText(texts["setting_preview_seconds_hint"])
        self.hint_preview_width.setText(texts["setting_preview_width_hint"])
        self.hint_preview_height.setText(texts["setting_preview_height_hint"])
        self.hint_thumb_width.setText(texts["setting_thumb_width_hint"])
        self.hint_thumb_height.setText(texts["setting_thumb_height_hint"])
        self.hint_remote_max_frames.setText(texts["setting_remote_max_frames_hint"])
        self.hint_embedding_batch_size.setText(texts["setting_embedding_batch_size_hint"])
        self.hint_similarity_threshold.setText(texts["setting_similarity_threshold_hint"])
        self.hint_max_chunk_duration.setText(texts["setting_max_chunk_duration_hint"])
        self.hint_min_chunk_size.setText(texts["setting_min_chunk_size_hint"])
        self.hint_chunk_similarity_mode.setText(texts["setting_chunk_similarity_mode_hint"])
        self.hint_prefer_gpu.setText(texts["setting_prefer_gpu_hint"])
        self.hint_gpu_probe_unknown_keep_gpu.setText(texts["setting_gpu_probe_unknown_keep_gpu_hint"])
        self.hint_auto_cleanup_missing_files.setText(texts["setting_auto_cleanup_missing_files_hint"])
        self.hint_active_model_profile.setText(
            _fallback_text(
                texts,
                "setting_active_model_profile_hint",
                "切换后将使用该模型独立的数据目录与模型资源目录。",
                "Switching changes both model resources and model-scoped data paths.",
            )
        )
        self.hint_data_root.setText(texts["setting_data_root_hint"])
        self.hint_ffmpeg_path.setText(texts["setting_ffmpeg_path_hint"])
        self.hint_ffmpeg_active.setText(texts["setting_ffmpeg_active"].format(path=texts["setting_ffmpeg_unknown"]))
        self.hint_inference_backend.setText(
            texts["setting_inference_backend"].format(backend=texts["setting_inference_uninitialized"])
        )
        self.hint_inference_backend.setProperty("state", "neutral")
        self.btn_show_runtime_diagnostics.setText(texts.get("setting_show_runtime_diagnostics", "Show diagnostics"))
        self.hint_gpu_runtime.setText(texts["setting_gpu_runtime_link_only"])
        self.hint_gpu_runtime.setOpenExternalLinks(True)
        self.hint_gpu_runtime.setTextFormat(Qt.RichText)
        self.hint_gpu_runtime.setTextInteractionFlags(Qt.TextBrowserInteraction)
        self.hint_gpu_runtime.setVisible(False)
        self.hint_model_dir.setText(texts["setting_model_dir_hint"])
        self._update_sampling_mode_visibility()
        self._update_frame_neighbor_rerank_visibility()
        for label in [
            self.label_fps,
            self.label_top_k,
            self.label_frame_neighbor_rerank_enabled,
            self.label_frame_neighbor_rerank_top_n,
            self.label_frame_neighbor_rerank_window,
            self.label_preview_seconds,
            self.label_preview_width,
            self.label_preview_height,
            self.label_thumb_width,
            self.label_thumb_height,
            self.label_remote_max_frames,
            self.label_embedding_batch_size,
            self.label_similarity_threshold,
            self.label_max_chunk_duration,
            self.label_min_chunk_size,
            self.label_chunk_similarity_mode,
            self.label_prefer_gpu,
            self.label_gpu_probe_unknown_keep_gpu,
            self.label_auto_cleanup_missing_files,
            self.label_active_model_profile,
            self.label_data_root,
            self.label_ffmpeg_path,
            self.label_model_dir,
        ]:
            self._configure_setting_label(label)
    def refresh_active_setting_detail(self):
        if self._active_setting_label is not None:
            for label, hint_label, extra_hint_labels in self._setting_detail_bindings:
                if label is self._active_setting_label:
                    self._activate_setting_detail(label, hint_label, extra_hint_labels)
                    return
        if self._setting_detail_bindings:
            label, hint_label, extra_hint_labels = self._setting_detail_bindings[0]
            self._activate_setting_detail(label, hint_label, extra_hint_labels)

    def set_runtime_status_texts(self, backend_text, ffmpeg_text, data_text=""):
        self.runtime_status_backend.setText(backend_text or "")
        self.runtime_status_ffmpeg.setText(ffmpeg_text or "")
        self.runtime_status_data.setText(data_text or "")


class ResultTable(QTableWidget):
    def __init__(self, parent=None):
        super().__init__(0, 7, parent)
        self.setObjectName("ResultTable")
        self.setHorizontalHeaderLabels(["#", "Preview", "Video", "Range", "Mode", "Score", "Actions"])
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(88)
        self.setAlternatingRowColors(False)
        self.setFocusPolicy(Qt.NoFocus)
        self.setShowGrid(False)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.horizontalHeader().setStretchLastSection(False)
        self.setColumnWidth(0, 46)
        self.setColumnWidth(1, 164)
        self.setColumnWidth(3, 108)
        self.setColumnWidth(4, 74)
        self.setColumnWidth(5, 74)
        self.setColumnWidth(6, 236)
        self.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.horizontalHeader().setSectionResizeMode(1, QHeaderView.Fixed)
        self.horizontalHeader().setSectionResizeMode(3, QHeaderView.Fixed)
        self.horizontalHeader().setSectionResizeMode(4, QHeaderView.Fixed)
        self.horizontalHeader().setSectionResizeMode(5, QHeaderView.Fixed)
        self.horizontalHeader().setSectionResizeMode(6, QHeaderView.Fixed)
