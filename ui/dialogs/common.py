from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTableWidgetItem


def dialog_palette(is_dark):
    return {
        "bg": "#161c28" if is_dark else "#f3f6fb",
        "card": "#1d2635" if is_dark else "#ffffff",
        "text": "#f3f5f8" if is_dark else "#1d2430",
        "muted": "#9aa6b7" if is_dark else "#617086",
        "accent": "#4a86ff" if is_dark else "#3b6fd8",
        "border": "#2d3950" if is_dark else "#d5ddea",
    }


class SortableTableWidgetItem(QTableWidgetItem):
    def __init__(self, value):
        super().__init__("" if value is None else str(value))
        self._sort_key = self._build_sort_key(value)

    @staticmethod
    def _build_sort_key(value):
        if value is None:
            return (2, "")
        if isinstance(value, bool):
            return (0, int(value))
        if isinstance(value, (int, float)):
            return (0, float(value))

        text = str(value).strip()
        if not text:
            return (2, "")

        try:
            return (0, int(text))
        except ValueError:
            pass

        try:
            return (0, float(text))
        except ValueError:
            pass

        return (1, text.lower())

    def __lt__(self, other):
        if isinstance(other, SortableTableWidgetItem):
            return self._sort_key < other._sort_key
        return super().__lt__(other)

