"""QTableWidget configured from TableSpec."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableWidget

from ui.widgets.table_specs import TableSpec


class DataTable(QTableWidget):
    def __init__(self, parent=None, *, spec: TableSpec):
        super().__init__(0, spec.column_count, parent)
        self.spec = spec
        self._apply_spec()

    def _apply_spec(self) -> None:
        spec = self.spec
        self.setObjectName(spec.object_name)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(spec.row_height)
        self.setAlternatingRowColors(False)
        self.setFocusPolicy(Qt.NoFocus)
        self.setShowGrid(False)
        if spec.scroll_per_pixel:
            self.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.horizontalHeader().setStretchLastSection(False)

        header = self.horizontalHeader()
        for index, column in enumerate(spec.columns):
            if column.resize == "stretch":
                header.setSectionResizeMode(index, QHeaderView.Stretch)
            else:
                header.setSectionResizeMode(index, QHeaderView.Fixed)
                if column.width is not None:
                    self.setColumnWidth(index, column.width)

    def apply_header_labels(self, texts: dict) -> None:
        key = self.spec.texts_header_key
        if not key:
            return
        labels = texts.get(key)
        if labels:
            self.setHorizontalHeaderLabels(labels)
