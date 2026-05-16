from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)

from src.app.i18n import get_texts
from ui.widgets.layout import WINDOW_SIZES, apply_dialog_size
from ui.widgets.scaffold import VSCard


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

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        shell = VSCard(spacing=12)
        form = shell.content_layout

        title = QLabel(notice.get("title", texts["notice_heading"]))
        title.setObjectName("DialogHeroTitle")
        subtitle = QLabel(notice.get("subtitle", texts["notice_subtitle"]))
        subtitle.setObjectName("Hint")
        subtitle.setWordWrap(True)

        content = QTextBrowser()
        content.setObjectName("DialogBodyBrowser")
        content.setReadOnly(True)
        content.setOpenExternalLinks(True)
        if notice.get("format") == "html":
            content.setHtml(notice.get("body", texts["notice_body"]))
        else:
            content.setPlainText(notice.get("body", texts["notice_body"]))

        button_row = QHBoxLayout()
        button_row.addStretch()
        close_button = QPushButton(texts["close"])
        close_button.setObjectName("PrimaryButton")
        close_button.setFixedWidth(110)
        close_button.clicked.connect(self.accept)
        button_row.addWidget(close_button)

        form.addWidget(title)
        form.addWidget(subtitle)
        form.addWidget(content)
        form.addLayout(button_row)
        layout.addWidget(shell)
