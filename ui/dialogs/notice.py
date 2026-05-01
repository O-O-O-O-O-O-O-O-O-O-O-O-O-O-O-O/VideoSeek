from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)

from src.app.i18n import get_texts
from ui.layout import WINDOW_SIZES, apply_dialog_size

from .common import dialog_palette

class NoticeDialog(QDialog):
    def __init__(self, parent=None, is_dark=True, language="zh", notice=None):
        super().__init__(parent)
        texts = get_texts(language)
        notice = notice or {}

        self.setWindowTitle(texts["notice_title"])
        apply_dialog_size(
            self,
            WINDOW_SIZES["notice_dialog"]["preferred"],
            WINDOW_SIZES["notice_dialog"]["minimum"],
            WINDOW_SIZES["notice_dialog"]["screen_margin"],
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

        title = QLabel(notice.get("title", texts["notice_heading"]))
        title.setStyleSheet("font-size: 22px; font-weight: 800;")
        subtitle = QLabel(notice.get("subtitle", texts["notice_subtitle"]))
        subtitle.setStyleSheet(f"color: {muted}; font-size: 12px;")
        subtitle.setWordWrap(True)

        content = QTextBrowser()
        content.setReadOnly(True)
        content.setOpenExternalLinks(True)
        if notice.get("format") == "html":
            content.setHtml(notice.get("body", texts["notice_body"]))
        else:
            content.setPlainText(notice.get("body", texts["notice_body"]))

        button_row = QHBoxLayout()
        button_row.addStretch()
        close_button = QPushButton(texts["close"])
        close_button.setFixedWidth(110)
        close_button.clicked.connect(self.accept)
        button_row.addWidget(close_button)

        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(content)
        layout.addLayout(button_row)

