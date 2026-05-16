"""Thumbnail table cell QLabel (#ThumbPreview)."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QLabel


def make_thumb_label(*, text: str = "", pixmap: QPixmap | None = None) -> QLabel:
    label = QLabel()
    label.setObjectName("ThumbPreview")
    label.setAlignment(Qt.AlignCenter)
    if pixmap is not None and not pixmap.isNull():
        label.setPixmap(pixmap)
    elif text:
        label.setText(text)
    return label
