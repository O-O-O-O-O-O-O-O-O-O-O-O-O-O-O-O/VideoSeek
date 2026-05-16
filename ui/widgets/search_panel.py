"""Local search query controls (text, image drop, mode, mobile bridge, actions)."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSizePolicy

from ui.widgets.layout import COMPONENT_SIZES
from ui.widgets.scaffold import VSCard


class SearchPanel(VSCard):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = self.content_layout

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

        layout.addWidget(self.controls_title)
        layout.addWidget(self.controls_hint)
        layout.addWidget(self.img_label)
        layout.addWidget(self.text_search)
        layout.addLayout(mode_row)
        layout.addLayout(mobile_row)
        layout.addLayout(action_row)
