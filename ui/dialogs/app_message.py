from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from src.app.i18n import get_texts
from ui.layout import WINDOW_SIZES, message_dialog_min_width

from .common import dialog_palette

class AppMessageDialog(QDialog):
    def __init__(
        self,
        title,
        text,
        kind="info",
        parent=None,
        is_dark=True,
        language="zh",
        confirm=False,
        cancel_text="",
        confirm_text="",
    ):
        super().__init__(parent)
        texts = get_texts(language)
        palette = dialog_palette(is_dark)

        kind_map = {
            "info": ("i", palette["accent"]),
            "success": ("OK", "#2ec27e" if is_dark else "#198754"),
            "warning": ("!", "#e0a100" if is_dark else "#b78103"),
            "error": ("X", "#e55353" if is_dark else "#c0392b"),
        }
        badge_text, badge_color = kind_map.get(kind, kind_map["info"])

        self._result = False
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(
            message_dialog_min_width(
                WINDOW_SIZES["message_dialog"]["minimum_width"],
                WINDOW_SIZES["message_dialog"]["screen_margin"],
            )
        )
        self.setStyleSheet(
            f"""
            QDialog {{ background: {palette['bg']}; }}
            QLabel {{ color: {palette['text']}; background: transparent; }}
            #Card {{ background: {palette['card']}; border: 1px solid {palette['border']}; border-radius: 20px; }}
            #Title {{ font-size: 22px; font-weight: 800; }}
            #Body {{ color: {palette['muted']}; font-size: 13px; }}
            #Badge {{
                min-width: 34px; max-width: 34px; min-height: 34px; max-height: 34px;
                border-radius: 17px; background: {badge_color}; color: white; font-weight: 800;
            }}
            QPushButton {{
                border: none; border-radius: 12px; padding: 10px 18px; font-weight: 700;
            }}
            #Primary {{ background: {palette['accent']}; color: white; }}
            #Ghost {{ background: transparent; color: {palette['muted']}; border: 1px solid {palette['border']}; }}
            """
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 18, 18, 18)
        card = QFrame()
        card.setObjectName("Card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(22, 22, 22, 18)
        layout.setSpacing(14)

        top = QHBoxLayout()
        top.setSpacing(12)
        badge = QLabel(badge_text)
        badge.setObjectName("Badge")
        badge.setAlignment(Qt.AlignCenter)
        top_text = QVBoxLayout()
        title_label = QLabel(title)
        title_label.setObjectName("Title")
        body_label = QLabel(text)
        body_label.setObjectName("Body")
        body_label.setWordWrap(True)
        top_text.addWidget(title_label)
        top_text.addWidget(body_label)
        top.addWidget(badge, 0)
        top.addLayout(top_text, 1)

        buttons = QHBoxLayout()
        buttons.addStretch()
        if confirm:
            cancel_label = str(cancel_text or "").strip() or texts["cancel"]
            confirm_label = str(confirm_text or "").strip() or texts["confirm_action"]
            cancel = QPushButton(cancel_label)
            cancel.setObjectName("Ghost")
            cancel.clicked.connect(self.reject)
            ok = QPushButton(confirm_label)
            ok.setObjectName("Primary")
            ok.clicked.connect(self._accept_confirm)
            buttons.addWidget(cancel)
            buttons.addWidget(ok)
        else:
            ok = QPushButton(texts["close"])
            ok.setObjectName("Primary")
            ok.clicked.connect(self.accept)
            buttons.addWidget(ok)

        layout.addLayout(top)
        layout.addLayout(buttons)
        outer.addWidget(card)

    def _accept_confirm(self):
        self._result = True
        self.accept()

    def confirmed(self):
        return self._result

