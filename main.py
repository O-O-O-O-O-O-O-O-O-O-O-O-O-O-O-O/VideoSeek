# main.py
import sys
from src.app.logging_utils import get_logger, setup_logging
from src.core.clip_embedding import gpu_probe_cli_main

if __name__ == "__main__":
    setup_logging()
    logger = get_logger("main")

    if "--gpu-probe" in sys.argv:
        sys.exit(gpu_probe_cli_main())

    from PySide6.QtWidgets import QApplication, QMessageBox, QProgressDialog
    from src.storage.migration_runner import run_startup_migration
    from ui.windows.gui import MainWindow

    app = QApplication(sys.argv)

    # 设置全局字体
    font = app.font()
    font.setFamily("Microsoft YaHei UI")
    app.setFont(font)

    logger.info("Application starting")
    progress_dialog = QProgressDialog("", "", 0, 100)
    progress_dialog.setWindowTitle("VideoSeek 数据迁移")
    progress_dialog.setLabelText("正在检查并迁移本地数据结构，请勿关闭应用...")
    progress_dialog.setCancelButton(None)
    # Avoid flashing a tiny startup dialog when migration finishes quickly.
    progress_dialog.setMinimumDuration(600)
    progress_dialog.setAutoClose(False)
    progress_dialog.setAutoReset(False)
    progress_dialog.setValue(0)

    try:
        result = run_startup_migration(
            progress_callback=lambda value, text: (
                progress_dialog.setValue(int(value)),
                progress_dialog.setLabelText(str(text)),
                app.processEvents(),
            )
        )
    except Exception as exc:
        logger.exception("Startup migration failed")
        progress_dialog.close()
        QMessageBox.critical(
            None,
            "启动迁移失败",
            f"VideoSeek 在迁移本地数据结构时失败：\n\n{exc}\n\n"
            "请从备份恢复后重试。",
        )
        sys.exit(1)

    progress_dialog.close()
    if result.get("migrated"):
        migrated_local = int(result.get("migrated_local_payloads", 0) or 0)
        migrated_local_files = int(result.get("migrated_local_asset_files", 0) or 0)
        migrated_global = int(result.get("migrated_global_payloads", 0) or 0)
        migrated_remote = int(result.get("migrated_remote_payloads", 0) or 0)
        backup_dir = str(result.get("backup_dir", "") or "").strip()
        detail_lines = [
            "VideoSeek 已完成数据结构升级，应用将继续启动。",
            "",
            f"- 本地资产文件迁移(目录重构): {migrated_local_files}",
            f"- 本地向量载荷迁移: {migrated_local}",
            f"- 全局索引元数据迁移: {migrated_global}",
            f"- 远程索引元数据迁移: {migrated_remote}",
        ]
        if backup_dir:
            detail_lines.extend(["", f"备份目录: {backup_dir}"])
        QMessageBox.information(
            None,
            "数据迁移完成",
            "\n".join(detail_lines),
        )

    window = MainWindow()
    if getattr(window, "startup_cancelled", False):
        logger.info("Startup cancelled before main window was shown")
        sys.exit(0)
    window.show()

    exit_code = app.exec()
    logger.info("Application exiting with code %s", exit_code)
    sys.exit(exit_code)
