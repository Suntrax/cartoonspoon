import sys

from gui import MainWindow
from chromedriver_updating import update_chromedriver

from PySide6.QtWidgets import QApplication


if __name__ == "__main__":
    app = QApplication(sys.argv)

    # Setup
    update_chromedriver()

    # Launch GUI
    window = MainWindow()
    window.show()

    sys.exit(app.exec())
