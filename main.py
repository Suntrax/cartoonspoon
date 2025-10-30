import sys

from gui import MainWindow

from PySide6.QtWidgets import QApplication


if __name__ == "__main__":
    app = QApplication(sys.argv)

    # Launch GUI
    window = MainWindow()
    window.show()

    sys.exit(app.exec())
