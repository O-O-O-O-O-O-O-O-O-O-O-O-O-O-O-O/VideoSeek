import webbrowser

from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)

from src.app.config import get_app_version
from src.app.i18n import get_texts
from ui.widgets.layout import WINDOW_SIZES, apply_dialog_size

from .common import dialog_palette

class AboutDialog(QDialog):
    def __init__(self, parent=None, is_dark=True, language="zh", version_info=None, about=None):
        super().__init__(parent)
        texts = get_texts(language)
        version_info = version_info or {}
        about = about or {}

        self.setWindowTitle(texts["about_title"])
        apply_dialog_size(
            self,
            WINDOW_SIZES["about_dialog"]["preferred"],
            WINDOW_SIZES["about_dialog"]["minimum"],
            WINDOW_SIZES["about_dialog"]["screen_margin"],
        )

        palette = dialog_palette(is_dark)
        bg = palette["bg"]
        card = palette["card"]
        text = palette["text"]
        muted = palette["muted"]
        accent = palette["accent"]
        border = palette["border"]

        self.setStyleSheet(f"""
            QDialog {{ background: {bg}; }}
            QLabel {{ color: {text}; background: transparent; }}
            QTextEdit, QTextBrowser {{
                background: {card};
                color: {muted};
                border: 1px solid {border};
                border-radius: 16px;
                padding: 12px;
                font-size: 13px;
            }}
            QPushButton {{
                background: {accent};
                color: white;
                border: none;
                border-radius: 12px;
                padding: 10px 18px;
                font-weight: 700;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        title_text = about.get("title", texts["app_name"])
        subtitle_text = about.get("badge", texts["about_badge"])
        title = QLabel(title_text)
        title.setStyleSheet("font-size: 22px; font-weight: 800;")
        subtitle = QLabel(subtitle_text)
        subtitle.setStyleSheet(f"color: {muted}; font-size: 12px;")
        subtitle.setWordWrap(True)
        version = QLabel(texts["version_label"].format(version=get_app_version()))
        version.setStyleSheet(f"color: {muted}; font-size: 12px;")
        version_status = QLabel(version_info.get("status_text", texts["version_check_unavailable"]))
        version_status.setStyleSheet(f"color: {muted}; font-size: 13px;")
        version_status.setWordWrap(True)

        divider = QFrame()
        divider.setFrameShape(QFrame.HLine)
        divider.setStyleSheet(f"background: {border}; max-height: 1px; margin: 8px 0;")

        body = QTextBrowser()
        body.setReadOnly(True)
        body.setOpenExternalLinks(True)
        if about.get("format") == "html":
            body.setHtml(about.get("body", texts["about_body"]))
        else:
            body.setPlainText(about.get("body", texts["about_body"]))

        download_button = QPushButton(texts["download_latest"])
        download_button.setFixedHeight(40)
        download_button.setVisible(bool(version_info.get("download_url")) and version_info.get("has_update"))
        download_button.clicked.connect(lambda: webbrowser.open(version_info["download_url"]))

        close_button = QPushButton(texts["close"])
        close_button.setFixedHeight(40)
        close_button.clicked.connect(self.accept)

        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(version)
        layout.addWidget(version_status)
        layout.addWidget(divider)
        layout.addWidget(body)
        button_row = QHBoxLayout()
        button_row.addStretch()
        if download_button.isVisible():
            button_row.addWidget(download_button)
        button_row.addWidget(close_button)

        layout.addLayout(button_row)

