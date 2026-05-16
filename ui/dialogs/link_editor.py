from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from src.app.i18n import get_texts
from ui.widgets.layout import WINDOW_SIZES, apply_dialog_size
from ui.widgets.scaffold import VSCard


class LinkEditorDialog(QDialog):
    def __init__(self, parent=None, is_dark=True, language="zh", initial_links=None):
        super().__init__(parent)
        self.texts = get_texts(language)
        self._links = list(initial_links or [])

        self.setWindowTitle(self.texts["network_link_editor_title"])
        apply_dialog_size(
            self,
            WINDOW_SIZES["notice_dialog"]["preferred"],
            WINDOW_SIZES["notice_dialog"]["minimum"],
            WINDOW_SIZES["notice_dialog"]["screen_margin"],
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(0)

        shell = VSCard(margins=(16, 16, 16, 16), spacing=10)
        inner = shell.content_layout

        title = QLabel(self.texts["network_link_editor_title"])
        title.setObjectName("DialogSectionTitle")
        hint = QLabel(self.texts["network_link_editor_hint"])
        hint.setObjectName("Hint")
        hint.setWordWrap(True)

        self.editor = QPlainTextEdit()
        self.editor.setObjectName("DialogPlainBody")
        self.editor.setPlaceholderText(self.texts["network_link_editor_placeholder"])
        self.editor.setPlainText("\n".join(self._links))

        toolbar = QHBoxLayout()
        self.btn_import = QPushButton(self.texts["network_link_editor_import"])
        self.btn_import.setObjectName("GhostButton")
        self.btn_clear = QPushButton(self.texts["network_link_editor_clear"])
        self.btn_clear.setObjectName("GhostButton")
        toolbar.addWidget(self.btn_import)
        toolbar.addWidget(self.btn_clear)
        toolbar.addStretch()

        actions = QHBoxLayout()
        actions.addStretch()
        self.btn_cancel = QPushButton(self.texts["cancel"])
        self.btn_cancel.setObjectName("GhostButton")
        self.btn_ok = QPushButton(self.texts["confirm_action"])
        self.btn_ok.setObjectName("PrimaryButton")
        actions.addWidget(self.btn_cancel)
        actions.addWidget(self.btn_ok)

        inner.addWidget(title)
        inner.addWidget(hint)
        inner.addWidget(self.editor, 1)
        inner.addLayout(toolbar)
        inner.addLayout(actions)
        root.addWidget(shell, 1)

        self.btn_import.clicked.connect(self._import_file)
        self.btn_clear.clicked.connect(self.editor.clear)
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_ok.clicked.connect(self.accept)

    def get_links(self):
        lines = [line.strip() for line in self.editor.toPlainText().splitlines()]
        deduped = []
        seen = set()
        for line in lines:
            if not line or line.startswith("#"):
                continue
            if line in seen:
                continue
            seen.add(line)
            deduped.append(line)
        return deduped

    def _import_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            self.texts["network_links_file_title"],
            "",
            self.texts["network_links_file_filter"],
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as handle:
                imported = [line.rstrip("\n") for line in handle]
        except Exception:
            return
        existing = self.editor.toPlainText().splitlines()
        merged = [line for line in existing if line.strip()]
        merged.extend(imported)
        self.editor.setPlainText("\n".join(merged))
