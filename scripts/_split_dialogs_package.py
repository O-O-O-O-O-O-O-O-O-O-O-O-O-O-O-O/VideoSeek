"""One-off script to split ui/dialogs.py into ui/dialogs/ package. Run from repo root."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "ui" / "dialogs.py"
OUT_DIR = ROOT / "ui" / "dialogs"
lines = SRC.read_text(encoding="utf-8").splitlines(keepends=True)

# 1-based inclusive line ranges from original dialogs.py
COMMON = (40, 85)
FILES = [
    ("common.py", COMMON, ""),
    (
        "app_message.py",
        (87, 180),
        '''from PySide6.QtCore import Qt
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

''',
    ),
    (
        "about.py",
        (182, 277),
        '''import webbrowser

from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)

from src.app.config import get_app_version
from src.app.i18n import get_texts
from ui.layout import WINDOW_SIZES, apply_dialog_size

from .common import dialog_palette

''',
    ),
    (
        "mobile_bridge.py",
        (279, 370),
        '''from PySide6.QtCore import Qt
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

from .common import dialog_palette

''',
    ),
    (
        "notice.py",
        (372, 444),
        '''from PySide6.QtWidgets import (
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

''',
    ),
    (
        "link_editor.py",
        (446, 557),
        '''from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from src.app.i18n import get_texts
from ui.layout import WINDOW_SIZES, apply_dialog_size

from .common import dialog_palette

''',
    ),
    (
        "sampling_rules.py",
        (559, 764),
        '''from PySide6.QtCore import QSize, Qt
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

''',
    ),
    (
        "legacy_resource_table.py",
        (766, 1282),
        '''import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from src.app.i18n import get_texts

from .common import dialog_palette

''',
    ),
    (
        "resource_table.py",
        (1284, 1753),
        '''import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
)

from src.app.i18n import get_texts

from .common import SortableTableWidgetItem, dialog_palette

''',
    ),
    (
        "model_download.py",
        (1755, 1978),
        '''from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from src.app.i18n import get_texts
from ui.layout import WINDOW_SIZES, apply_dialog_size

from .common import dialog_palette

''',
    ),
]

COMMON_HEADER = """from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTableWidgetItem


"""


def slice_lines(start: int, end: int):
    # start/end are 1-based inclusive
    return "".join(lines[start - 1 : end])


def main():
    if not SRC.exists():
        raise SystemExit(
            "Missing ui/dialogs.py — this script slices the monolith into ui/dialogs/. "
            "Restore it from git (e.g. git show HEAD:ui/dialogs.py > ui/dialogs.py) or skip."
        )
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, span, header in FILES:
        start, end = span
        body = slice_lines(start, end)
        if name == "common.py":
            content = COMMON_HEADER + body
        else:
            content = header + body
        (OUT_DIR / name).write_text(content, encoding="utf-8")
        print("wrote", name, len(content.splitlines()), "lines")

    init = '''"""Dialog widgets; split from the former monolithic ui/dialogs.py."""
from .about import AboutDialog
from .app_message import AppMessageDialog
from .common import SortableTableWidgetItem, dialog_palette
from .legacy_resource_table import LegacyResourceTableDialog
from .link_editor import LinkEditorDialog
from .mobile_bridge import MobileBridgeDialog
from .model_download import ModelDownloadDialog
from .notice import NoticeDialog
from .resource_table import ResourceTableDialog
from .sampling_rules import SamplingRulesDialog

__all__ = [
    "AboutDialog",
    "AppMessageDialog",
    "LegacyResourceTableDialog",
    "LinkEditorDialog",
    "MobileBridgeDialog",
    "ModelDownloadDialog",
    "NoticeDialog",
    "ResourceTableDialog",
    "SamplingRulesDialog",
    "SortableTableWidgetItem",
    "dialog_palette",
]
'''
    (OUT_DIR / "__init__.py").write_text(init, encoding="utf-8")
    print("wrote __init__.py")


if __name__ == "__main__":
    main()
