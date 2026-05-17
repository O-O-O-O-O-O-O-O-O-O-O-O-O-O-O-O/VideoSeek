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
    from src.app.config import set_startup_migration_summary
    from src.app.single_instance import SingleInstanceServer, try_activate_existing_instance
    from src.storage.migration_runner import run_startup_migration
    from ui.windows.gui import MainWindow

    app = QApplication(sys.argv)

    if try_activate_existing_instance():
        logger.info("Another instance is running; activating existing window")
        sys.exit(0)

    single_instance_server = SingleInstanceServer(parent=app)

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
    set_startup_migration_summary(result)

    window = MainWindow()
    single_instance_server.set_activate_handler(window._show_main_window_from_tray)
    if getattr(window, "startup_cancelled", False):
        logger.info("Startup cancelled before main window was shown")
        sys.exit(0)
    window.show()

    exit_code = app.exec()
    logger.info("Application exiting with code %s", exit_code)
    sys.exit(exit_code)
