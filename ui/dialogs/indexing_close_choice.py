from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from ui.widgets.layout import WINDOW_SIZES, message_dialog_min_width
from ui.widgets.scaffold import VSCard
from ui.widgets.styles import repolish_widget


class IndexingCloseChoiceDialog(QDialog):
    """Ask how to handle window close while library indexing is running."""

    def __init__(self, texts, parent=None, is_dark=True, language="zh"):
        super().__init__(parent)
        self._texts = texts
        self._choice = "cancel"
        self.setWindowTitle(texts.get("indexing_close_dialog_title", "Indexing in progress"))
        self.setModal(True)
        self.setMinimumWidth(
            message_dialog_min_width(
                WINDOW_SIZES["message_dialog"]["minimum_width"] + 80,
                WINDOW_SIZES["message_dialog"]["screen_margin"],
            )
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 18, 18, 18)
        card = VSCard(variant="dialog", margins=(22, 22, 22, 18), spacing=14)
        layout = card.content_layout

        top = QHBoxLayout()
        top.setSpacing(12)
        badge = QLabel()
        badge.setObjectName("MessageBadge")
        badge.setAlignment(Qt.AlignCenter)
        badge.setText("!")
        badge.setProperty("kind", "warning")
        repolish_widget(badge)
        top_text = QVBoxLayout()
        title_label = QLabel(texts.get("indexing_close_dialog_title", "Indexing in progress"))
        title_label.setObjectName("DialogHeroTitle")
        body_label = QLabel(texts.get("indexing_close_dialog_body", ""))
        body_label.setObjectName("DialogBodyLabel")
        body_label.setWordWrap(True)
        top_text.addWidget(title_label)
        top_text.addWidget(body_label)
        top.addWidget(badge, 0)
        top.addLayout(top_text, 1)

        actions = QVBoxLayout()
        actions.setSpacing(8)
        background_btn = QPushButton(texts.get("indexing_close_choice_background", "Continue in background"))
        background_btn.setObjectName("PrimaryButton")
        background_btn.clicked.connect(lambda: self._choose("background"))
        stop_btn = QPushButton(texts.get("indexing_close_choice_stop_exit", "Stop indexing and quit"))
        stop_btn.setObjectName("GhostButton")
        stop_btn.clicked.connect(lambda: self._choose("stop_exit"))

        actions.addWidget(background_btn)
        actions.addWidget(stop_btn)

        footer = QHBoxLayout()
        footer.addStretch()
        cancel_btn = QPushButton(texts.get("cancel", "Cancel"))
        cancel_btn.setObjectName("GhostButton")
        cancel_btn.clicked.connect(self.reject)
        footer.addWidget(cancel_btn)

        layout.addLayout(top)
        layout.addLayout(actions)
        layout.addLayout(footer)
        outer.addWidget(card)

    def _choose(self, choice):
        self._choice = choice
        self.accept()

    def choice(self):
        return self._choice
