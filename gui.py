import os
import re

from web_scraping import scrape_tmdb_info
from helper_functions import sanitize_filename
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
)
from PySide6.QtCore import QThread, Signal

from web_scraping import scrape_drive_links


class DownloadWorker(QThread):
    progress_text = Signal(str)     # text updates
    progress_value = Signal(int)    # overall progress bar updates
    file_progress = Signal(int)     # individual file progress bar updates
    finished = Signal()             # download finished

    def __init__(self, service, drive_links, query):
        super().__init__()
        self.service = service
        self.drive_links = drive_links
        self.query = query

    def run(self):
        anime_name = self.query
        # Count total files to download
        total_files = 0
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
                    files = sorted(list_files_in_folder(self.service, folder_id), key=lambda f: f['name'])
                    for f in files:
                        files_map.append((f['id'], f['name'], base_path))
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
                    files = sorted(list_files_in_folder(self.service, folder_id), key=lambda f: f['name'])
                    for f in files:
                        ext = os.path.splitext(f['name'])[1]
                        episode_name = f"{safe_title} S{season_num:02d}E{episode_counter:02d}{ext}"
                        files_map.append((f['id'], episode_name, base_path))
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


# -------------------------
# Main GUI
# -------------------------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.worker = None
        self.service = authenticate_drive_api()
        self.query = None
        self.setWindowTitle("cartoonspoon")

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

    def scrape_anime_name(self):
        self.query = self.anime_name.text()
        if not self.query:
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
