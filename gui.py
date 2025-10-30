import os
import re

from web_scraping import scrape_tmdb_info
from helper_functions import sanitize_filename
from chromedriver_updating import update_chromedriver
from google_drive import download_file, list_files_in_folder, authenticate_drive_api

from PySide6.QtWidgets import (
    QTextEdit,
    QLabel,
    QLineEdit,
    QPushButton,
    QMainWindow,
    QGridLayout,
    QWidget,
    QProgressBar,
    QMessageBox,
)

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QIcon
from PySide6.QtCore import QThread, Signal

from web_scraping import scrape_drive_links


class DownloadWorker(QThread):
    progress_text = Signal(str)  # text updates
    progress_value = Signal(int)  # overall progress bar updates
    file_progress = Signal(int)  # individual file progress bar updates
    finished = Signal()  # download finished

    def __init__(self, service, drive_links, query):
        super().__init__()
        self.service = service
        self.drive_links = drive_links
        self.query = query

    def run(self):
        anime_name = self.query
        files_map = []  # List of (file_id, file_name, base_path) for all files
        for name, url in self.drive_links:
            match_folder = re.search(r"/folders/([a-zA-Z0-9_-]+)", url)
            match_file = re.search(r"/file/d/([a-zA-Z0-9_-]+)", url)
            is_movie = "movie" in (anime_name or name).lower() or "film" in (anime_name or name).lower()
            tmdb_query = anime_name or self.query or name

            if is_movie:
                title, year, tmdb_id = scrape_tmdb_info(tmdb_query, content_type="movie")
                safe_title = sanitize_filename(title)
                folder_name = f"{safe_title} ({year}) [tmdbid-{tmdb_id}]"
                base_path = os.path.join("downloads", folder_name)
                os.makedirs(base_path, exist_ok=True)
                if match_folder:
                    folder_id = match_folder.group(1)
                    files_list = sorted(list_files_in_folder(self.service, folder_id), key=lambda x: x['name'])
                    for file_item in files_list:
                        files_map.append((file_item['id'], file_item['name'], base_path))
                elif match_file:
                    files_map.append((match_file.group(1), name, base_path))
            else:
                # Series logic
                title, year, tmdb_id = scrape_tmdb_info(tmdb_query, content_type="tv")
                safe_title = sanitize_filename(title)
                root_folder = os.path.join("downloads", f"{safe_title} ({year}) [tmdbid-{tmdb_id}]")
                os.makedirs(root_folder, exist_ok=True)
                season_match = re.search(r"Season\s*(\d+)", name, re.IGNORECASE)
                season_num = int(season_match.group(1)) if season_match else 1
                season_folder = f"Season {season_num:02d}"
                base_path = os.path.join(root_folder, season_folder)
                os.makedirs(base_path, exist_ok=True)
                episode_counter = 1
                if match_folder:
                    folder_id = match_folder.group(1)
                    files_list = sorted(list_files_in_folder(self.service, folder_id), key=lambda x: x['name'])
                    for file_item in files_list:
                        ext = os.path.splitext(file_item['name'])[1]
                        episode_name = f"{safe_title} S{season_num:02d}E{episode_counter:02d}{ext}"
                        files_map.append((file_item['id'], episode_name, base_path))
                        episode_counter += 1
                elif match_file:
                    ext = os.path.splitext(name)[1] if "." in name else ".mp4"
                    episode_name = f"{safe_title} S{season_num:02d}E{episode_counter:02d}{ext}"
                    files_map.append((match_file.group(1), episode_name, base_path))

        if not files_map:
            self.progress_text.emit("No files to download.")
            self.finished.emit()
            return

        total_files = len(files_map)
        downloaded_files = 0

        for file_id, fname, base_path in files_map:
            self.progress_text.emit(f"Starting download: {fname}")

            # Wrap download_file with progress callback
            download_file(self.service, file_id, fname, base_path,
                          progress_callback=lambda p: self.file_progress.emit(p))

            self.progress_text.emit(f"Downloaded {fname}")
            downloaded_files += 1
            percent = int(downloaded_files / total_files * 100)
            self.progress_value.emit(percent)

        self.finished.emit()

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        # Initialize all instance attributes
        self.auto_update_chromedriver = False
        self.worker = None
        self.service = authenticate_drive_api()
        self.query = None
        self.chromedriver_auto_update_action = None

        # GUI widgets
        self.layout = None
        self.anime_label = None
        self.anime_name = None
        self.scrape_button = None
        self.progress_log = None
        self.progress_bar = None
        self.file_progress_bar = None
        self.widget = None

        self.setWindowTitle("cartoonspoon")
        self.setWindowIcon(QIcon('assets/icon.png'))
        self.setFixedSize(400, 400)

        self.load_settings()
        self.create_menu_bar()
        self.setup_ui()

        if self.auto_update_chromedriver:
            update_chromedriver(self.progress_log.append)

    def setup_ui(self):
        """Set up the main UI components"""
        self.layout = QGridLayout()

        self.anime_label = QLabel('Enter anime name / Google drive link / Drive folder id:')
        self.anime_name = QLineEdit(placeholderText='Anime name / Drive link / Drive id')
        self.scrape_button = QPushButton('Scrape')
        self.scrape_button.clicked.connect(self.scrape_anime_name)

        self.progress_log = QTextEdit()
        self.progress_log.setReadOnly(True)
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.file_progress_bar = QProgressBar()
        self.file_progress_bar.setValue(0)

        self.layout.addWidget(self.anime_label, 0, 0)
        self.layout.addWidget(self.anime_name, 1, 0)
        self.layout.addWidget(self.scrape_button, 1, 1)
        self.layout.addWidget(self.progress_log, 2, 0, 1, 2)
        self.layout.addWidget(self.file_progress_bar, 3, 0, 1, 2)
        self.layout.addWidget(self.progress_bar, 4, 0, 1, 2)

        self.widget = QWidget()
        self.widget.setLayout(self.layout)
        self.setCentralWidget(self.widget)

    def load_settings(self):
        """Load settings from settings.txt file"""
        try:
            if os.path.exists("settings.txt"):
                with open("settings.txt", "r") as file:
                    settings = file.readlines()
                for line in settings:
                    line = line.strip()
                    if line.startswith("auto_update_chromedriver="):
                        value = line.split("=")[1].strip()
                        self.auto_update_chromedriver = (value == "1")
                        break
        except Exception as e:
            print(f"Error loading settings: {e}")
            self.auto_update_chromedriver = False

    def save_settings(self):
        """Save settings to settings.txt file"""
        try:
            with open("settings.txt", "w") as file:
                file.write(f"auto_update_chromedriver={'1' if self.auto_update_chromedriver else '0'}\n")
        except Exception as e:
            print(f"Error saving settings: {e}")

    def create_menu_bar(self):
        menubar = self.menuBar()

        # File Menu
        file_menu = menubar.addMenu("File")
        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # Tools Menu
        tools_menu = menubar.addMenu("Tools")
        clear_log_action = QAction("Clear Log", self)
        clear_log_action.triggered.connect(self.clear_log)
        tools_menu.addAction(clear_log_action)

        chromedriver_update_action = QAction("Update Chromedriver", self)
        # Use lambda to ensure progress_log.append is available when called
        chromedriver_update_action.triggered.connect(lambda: update_chromedriver(self.progress_log.append))
        tools_menu.addAction(chromedriver_update_action)

        # Create checkbox action for auto-update
        self.chromedriver_auto_update_action = QAction("Auto Update Chromedriver", self)
        self.chromedriver_auto_update_action.setCheckable(True)
        self.chromedriver_auto_update_action.setChecked(self.auto_update_chromedriver)
        self.chromedriver_auto_update_action.triggered.connect(self.toggle_auto_update_chromedriver)
        tools_menu.addAction(self.chromedriver_auto_update_action)

        # Help Menu
        help_menu = menubar.addMenu("Help")
        about_action = QAction("About", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

    def toggle_auto_update_chromedriver(self):
        """Toggle the auto-update setting and save it"""
        self.auto_update_chromedriver = self.chromedriver_auto_update_action.isChecked()
        self.save_settings()
        status = "enabled" if self.auto_update_chromedriver else "disabled"
        self.progress_log.append(f"Auto update chromedriver: {status}")

        # Auto-update immediately if enabled
        if self.auto_update_chromedriver:
            update_chromedriver(self.progress_log.append)

    def clear_log(self):
        self.progress_log.clear()

    def show_about(self):
        about_box = QMessageBox(self)
        about_box.setWindowTitle("About cartoonspoon")
        about_box.setTextFormat(Qt.TextFormat.RichText)
        about_box.setText(
            "A Google Drive anime scraper and downloader.\n"
            "<a href='https://github.com/Suntrax/cartoonspoon'>Check out on github</a>."
        )
        about_box.exec()

    def scrape_anime_name(self):
        self.query = self.anime_name.text().strip()
        if not self.query:
            QMessageBox.warning(
                self,
                "Input Required",
                "Please enter an anime name, Google Drive link, or folder ID before scraping.",
            )
            return
        self.anime_name.setDisabled(True)
        self.scrape_button.setDisabled(True)
        self.progress_log.append(f"Processing: {self.query}")
        self.progress_bar.setValue(0)
        self.file_progress_bar.setValue(0)

        if "drive.google.com" in self.query or re.match(r"^[a-zA-Z0-9_-]{25,}$", self.query):
            if re.match(r"^[a-zA-Z0-9_-]{25,}$", self.query):
                drive_links = [["Direct Input", f"https://drive.google.com/drive/folders/{self.query}"]]
            else:
                drive_links = [["Direct Input", self.query]]
        else:
            drive_links = scrape_drive_links(self.query)

        if not drive_links:
            self.progress_log.append("No Google Drive links found.")
            self.anime_name.setDisabled(False)
            self.scrape_button.setDisabled(False)
            return

        for i, (name, url) in enumerate(drive_links):
            self.progress_log.append(f"{i}: {name} -> {url}")

        self.worker = DownloadWorker(self.service, drive_links, self.query)
        self.worker.progress_text.connect(self.progress_log.append)
        self.worker.progress_value.connect(self.progress_bar.setValue)
        self.worker.file_progress.connect(self.file_progress_bar.setValue)
        self.worker.finished.connect(self.download_finished)
        self.worker.start()

    def download_finished(self):
        self.progress_log.append("All downloads finished!")
        self.anime_name.setDisabled(False)
        self.scrape_button.setDisabled(False)
        self.progress_bar.setValue(100)
        self.file_progress_bar.setValue(100)