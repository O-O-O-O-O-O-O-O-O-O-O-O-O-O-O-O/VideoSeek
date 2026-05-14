from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from src.app.i18n import get_texts


class MobileBridgeDialog(QDialog):
    def __init__(self, url, parent=None, is_dark=True, language="zh", qr_pixmap=None):
        super().__init__(parent)
        texts = get_texts(language)

        self.setWindowTitle(texts.get("mobile_bridge_qr_title", "局域网访问"))
        self.setModal(True)
        self.setMinimumWidth(380)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 18, 18, 18)

        card = QFrame()
        card.setObjectName("Card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(22, 22, 22, 18)
        layout.setSpacing(14)

        title = QLabel(texts.get("mobile_bridge_qr_title", "局域网访问"))
        title.setObjectName("DialogPageTitle")
        hint = QLabel(texts.get("mobile_bridge_qr_hint", "手机扫码或访问下面的地址后上传图片。"))
        hint.setObjectName("Hint")
        hint.setWordWrap(True)

        qr_label = QLabel()
        qr_label.setAlignment(Qt.AlignCenter)
        qr_label.setMinimumHeight(220)
        if isinstance(qr_pixmap, QPixmap) and not qr_pixmap.isNull():
            qr_label.setPixmap(qr_pixmap.scaled(220, 220, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            qr_label.setText(texts.get("mobile_bridge_qr_unavailable", "当前环境缺少二维码依赖，请直接访问下面的地址。"))
            qr_label.setWordWrap(True)

        url_label = QLabel(url)
        url_label.setObjectName("DialogCodeBox")
        url_label.setWordWrap(True)
        url_label.setTextInteractionFlags(Qt.TextSelectableByMouse)

        button_row = QHBoxLayout()
        button_row.addStretch()
        copy_button = QPushButton(texts.get("mobile_bridge_copy_url", "复制地址"))
        copy_button.setObjectName("GhostButton")
        copy_button.clicked.connect(lambda: QApplication.clipboard().setText(url))
        close_button = QPushButton(texts["close"])
        close_button.setObjectName("PrimaryButton")
        close_button.clicked.connect(self.accept)
        button_row.addWidget(copy_button)
        button_row.addWidget(close_button)

        layout.addWidget(title)
        layout.addWidget(hint)
        layout.addWidget(qr_label)
        layout.addWidget(url_label)
        layout.addLayout(button_row)
        outer.addWidget(card)
