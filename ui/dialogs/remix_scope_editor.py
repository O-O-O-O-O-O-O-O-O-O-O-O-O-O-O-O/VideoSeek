"""Modal editor for remix match library scope (tree moved in/out of the dialog)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from ui.widgets.scaffold import VSCard
from ui.widgets.styles import repolish_widget


class RemixScopeEditorDialog(QDialog):
    def __init__(self, parent, remix_page, texts: dict, *, is_dark: bool, entries_cache_getter):
        super().__init__(parent)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setWindowTitle(str(texts.get("remix_scope_dialog_title", texts.get("remix_scope_title", ""))))
        self.resize(820, 560)
        self._remix_page = remix_page
        self._texts = texts
        self._is_dark = bool(is_dark)
        self._entries_cache_getter = entries_cache_getter
        self._body = remix_page.scope_list_body
        self._stash = remix_page._scope_editor_stash
        self._stash_layout = remix_page._scope_stash_layout

        self._snapshot_paths = list(remix_page.scope_tree.collect_checked_video_paths())
        self._snapshot_expanded = list(remix_page.scope_tree.collect_expanded_library_paths())

        self.setObjectName("RemixScopeEditorDialog")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        shell = VSCard(margins=(18, 16, 18, 16), spacing=12)
        inner = shell.content_layout

        hero = QLabel(str(texts.get("remix_scope_dialog_title", texts.get("remix_scope_title", ""))))
        hero.setObjectName("DialogHeroTitle")
        inner.addWidget(hero)

        self._body.setParent(self)
        inner.addWidget(self._body, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        cancel = QPushButton(str(texts.get("cancel", "Cancel")))
        cancel.setObjectName("GhostButton")
        cancel.clicked.connect(self.reject)
        ok = QPushButton(str(texts.get("remix_scope_dialog_ok", texts.get("confirm_action", "OK"))))
        ok.setObjectName("PrimaryButton")
        ok.clicked.connect(self.accept)
        btn_row.addWidget(cancel, 0)
        btn_row.addWidget(ok, 0)
        inner.addLayout(btn_row)
        root.addWidget(shell, 1)

        self._apply_palette()

    def _apply_palette(self) -> None:
        repolish_widget(self)

    def _restore_body_to_stash(self) -> None:
        self._body.setParent(self._stash)
        self._stash_layout.addWidget(self._body)

    def accept(self) -> None:
        self._restore_body_to_stash()
        self._remix_page.refresh_scope_summary(self._texts)
        super().accept()

    def reject(self) -> None:
        entries = self._entries_cache_getter()
        if entries:
            self._remix_page.scope_tree.refresh_from_entries(
                entries,
                checked_abs_paths=self._snapshot_paths,
                expanded_lib_paths=self._snapshot_expanded,
            )
        else:
            self._remix_page.scope_tree.apply_checked_paths(self._snapshot_paths)
        self._restore_body_to_stash()
        self._remix_page.refresh_scope_summary(self._texts)
        super().reject()
