from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from src.app.i18n import get_texts
from src.utils import (
    ensure_sampling_fps_rules_open_tail,
    normalize_sampling_fps_rules_text,
    validate_sampling_fps_rules,
    validate_sampling_fps_rules_full_coverage,
)
from ui.layout import WINDOW_SIZES, apply_dialog_size

from .app_message import AppMessageDialog
from .common import dialog_palette

class SamplingRulesDialog(QDialog):
    def __init__(self, parent=None, is_dark=True, language="zh", rules_text=""):
        super().__init__(parent)
        self.language = language
        self.texts = get_texts(language)
        palette = dialog_palette(is_dark)
        self._rules_text = normalize_sampling_fps_rules_text(rules_text)

        self.setWindowTitle(self.texts["sampling_rules_title"])
        apply_dialog_size(
            self,
            QSize(760, 460),
            QSize(620, 380),
            WINDOW_SIZES["notice_dialog"]["screen_margin"],
        )
        self.setModal(True)
        self.setStyleSheet(
            f"""
            QDialog {{ background: {palette['bg']}; }}
            QLabel {{ color: {palette['text']}; background: transparent; }}
            #Hint {{ color: {palette['muted']}; font-size: 12px; }}
            QTableWidget {{
                background: {palette['card']};
                color: {palette['text']};
                border: 1px solid {palette['border']};
                border-radius: 12px;
                gridline-color: {palette['border']};
                alternate-background-color: {"#202a3b" if is_dark else "#f7f9fd"};
            }}
            QTableWidget::item {{ padding: 6px 8px; }}
            QTableWidget::item:hover {{
                background: {"#2a3a57" if is_dark else "#eef4ff"};
                color: {palette['text']};
            }}
            QTableWidget::item:selected {{
                background: {"#35507c" if is_dark else "#dce8ff"};
                color: {palette['text']};
            }}
            QTableWidget QLineEdit {{
                background: {palette['card']};
                color: {palette['text']};
                border: 1px solid {palette['accent']};
                border-radius: 6px;
                padding: 2px 6px;
                selection-background-color: {"#35507c" if is_dark else "#dce8ff"};
                selection-color: {palette['text']};
            }}
            QHeaderView::section {{
                color: {palette['muted']};
                background: {palette['card']};
                border: none;
                border-bottom: 1px solid {palette['border']};
                padding: 10px 8px;
            }}
            QPushButton {{
                border-radius: 10px;
                border: 1px solid {palette['border']};
                padding: 8px 12px;
                color: {palette['text']};
                background: {palette['card']};
            }}
            #Primary {{ background: {palette['accent']}; color: white; border-color: {palette['accent']}; }}
            """
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        title = QLabel(self.texts["sampling_rules_title"])
        title.setStyleSheet("font-size: 18px; font-weight: 700;")
        hint = QLabel(self.texts["sampling_rules_hint"])
        hint.setObjectName("Hint")
        hint.setWordWrap(True)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(
            [
                self.texts["sampling_rules_col_start"],
                self.texts["sampling_rules_col_end"],
                self.texts["sampling_rules_col_fps"],
            ]
        )
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)

        toolbar = QHBoxLayout()
        self.empty_hint = QLabel(self.texts["sampling_rules_empty"])
        self.empty_hint.setObjectName("Hint")
        self.empty_hint.setWordWrap(True)
        toolbar.addWidget(self.empty_hint, 1)
        self.btn_add = QPushButton(self.texts["sampling_rules_add"])
        self.btn_remove = QPushButton(self.texts["sampling_rules_remove"])
        toolbar.addWidget(self.btn_add)
        toolbar.addWidget(self.btn_remove)

        actions = QHBoxLayout()
        actions.addStretch()
        self.btn_cancel = QPushButton(self.texts["cancel"])
        self.btn_apply = QPushButton(self.texts["sampling_rules_apply"])
        self.btn_apply.setObjectName("Primary")
        actions.addWidget(self.btn_cancel)
        actions.addWidget(self.btn_apply)

        root.addWidget(title)
        root.addWidget(hint)
        root.addWidget(self.table, 1)
        root.addLayout(toolbar)
        root.addLayout(actions)

        self.btn_add.clicked.connect(lambda: self._append_row("", "", ""))
        self.btn_remove.clicked.connect(self._remove_selected_row)
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_apply.clicked.connect(self._apply_rules)

        self._load_rules(self._rules_text)

    def _append_row(self, start_text, end_text, fps_text):
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(start_text))
        self.table.setItem(row, 1, QTableWidgetItem(end_text))
        self.table.setItem(row, 2, QTableWidgetItem(fps_text))

    def _load_rules(self, rules_text):
        normalized = normalize_sampling_fps_rules_text(rules_text)
        if not normalized:
            self._append_row("", "", "")
            return
        for chunk in normalized.split(";"):
            item = chunk.strip()
            if not item or "=" not in item or "-" not in item:
                continue
            range_part, fps_part = item.split("=", 1)
            start_text, end_text = range_part.split("-", 1)
            self._append_row(start_text.strip(), end_text.strip(), fps_part.strip())
        if self.table.rowCount() == 0:
            self._append_row("", "", "")

    def _remove_selected_row(self):
        current_row = self.table.currentRow()
        if current_row >= 0:
            self.table.removeRow(current_row)
        if self.table.rowCount() == 0:
            self._append_row("", "", "")

    def _apply_rules(self):
        parts = []
        for row in range(self.table.rowCount()):
            start_item = self.table.item(row, 0)
            end_item = self.table.item(row, 1)
            fps_item = self.table.item(row, 2)
            start_text = (start_item.text() if start_item else "").strip()
            end_text = (end_item.text() if end_item else "").strip()
            fps_text = (fps_item.text() if fps_item else "").strip()
            if not start_text and not end_text and not fps_text:
                continue
            rule_text = f"{start_text}-{end_text}={fps_text}"
            is_valid, _ = validate_sampling_fps_rules(rule_text)
            if not is_valid:
                AppMessageDialog(
                    self.texts["sampling_rules_title"],
                    self.texts["sampling_rules_invalid_row"].format(row=row + 1),
                    kind="warning",
                    parent=self,
                    is_dark="#161c28" in self.styleSheet(),
                    language=self.language,
                ).exec()
                return
            parts.append(rule_text)

        normalized_rules = normalize_sampling_fps_rules_text("; ".join(parts))
        normalized_rules = ensure_sampling_fps_rules_open_tail(normalized_rules, default_tail_fps=0.5)
        all_valid, invalid_ref = validate_sampling_fps_rules_full_coverage(normalized_rules)
        if not all_valid:
            invalid_row = None
            token = str(invalid_ref or "").strip()
            if token.lower().startswith("rule "):
                raw_num = token[5:].strip()
                if raw_num.isdigit():
                    invalid_row = int(raw_num)
            message = (
                self.texts["sampling_rules_invalid_row"].format(row=invalid_row)
                if invalid_row
                else self.texts["setting_sampling_fps_rules_invalid"]
            )
            AppMessageDialog(
                self.texts["sampling_rules_title"],
                message,
                kind="warning",
                parent=self,
                is_dark="#161c28" in self.styleSheet(),
                language=self.language,
            ).exec()
            return

        self._rules_text = normalized_rules
        self.accept()

    def rules_text(self):
        return self._rules_text

