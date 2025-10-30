import os
import re

from web_scraping import scrape_tmdb_info
from helper_functions import sanitize_filename
from google_drive import download_file, list_files_in_folder, authenticate_drive_api


from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QLineEdit,
    QPushButton,
    QMainWindow,
    QGridLayout,
    QWidget,
)

from web_scraping import scrape_drive_links


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.service = authenticate_drive_api()

        self.query = None
        self.setWindowTitle("cartoonspoon")

        self.layout = QGridLayout()

        self.anime_label = QLabel('Enter anime name / Google drive link / Drive folder id:')
        self.anime_name = QLineEdit(placeholderText='Anime name / Drive link / Drive id')
        self.scrape_button = QPushButton('Scrape')
        self.scrape_button.clicked.connect(self.scrape_anime_name)

        self.layout.addWidget(self.anime_label, 0, 0)
        self.layout.addWidget(self.anime_name, 1, 0)
        self.layout.addWidget(self.scrape_button, 1, 1)

        self.widget = QWidget()
        self.widget.setLayout(self.layout)
        self.setCentralWidget(self.widget)

    def scrape_anime_name(self):
        self.query = self.anime_name.text()
        if not self.query:
            return
        print(self.query)
        self.anime_name.setDisabled(True)

        if "drive.google.com" in self.query or re.match(r"^[a-zA-Z0-9_-]{25,}$", self.query):
            print("Direct Google Drive link/ID detected.")

            # Ask for anime name for TMDB scraping

            # Normalize to full URL
            if re.match(r"^[a-zA-Z0-9_-]{25,}$", self.query):
                # treat as ID
                drive_links = [["Direct Input", f"https://drive.google.com/drive/folders/{self.query}"]]
            else:
                drive_links = [["Direct Input", self.query]]

        else:
            # Normal search on KayoAnime
            drive_links = scrape_drive_links(self.query)
            anime_name = self.query  # use the original search term

        if not drive_links:
            print("No Google Drive links found.")
            return

        print("\nGoogle Drive links found:")
        for i, (name, url) in enumerate(drive_links):
            print(f"{i}: {name} -> {url}")

        for name, url in drive_links:
            is_movie = "movie" in (anime_name or name).lower() or "film" in (anime_name or name).lower()

            # use anime_name if provided, else fallback to name/query
            tmdb_query = anime_name or self.query or name

            if is_movie:
                title, year, tmdb_id = scrape_tmdb_info(tmdb_query, content_type="movie")
                safe_title = sanitize_filename(title)
                folder_name = f"{safe_title} ({year}) [tmdbid-{tmdb_id}]"
                base_path = os.path.join("downloads", folder_name)
                os.makedirs(base_path, exist_ok=True)

                match_folder = re.search(r"/folders/([a-zA-Z0-9_-]+)", url)
                match_file = re.search(r"/file/d/([a-zA-Z0-9_-]+)", url)

                if match_folder:
                    folder_id = match_folder.group(1)
                    files = list_files_in_folder(self.service, folder_id)
                    files = sorted(files, key=lambda f: f['name'])
                    for file in files:
                        ext = os.path.splitext(file['name'])[1]
                        movie_name = f"{safe_title} ({year}) [tmdbid-{tmdb_id}]{ext}"
                        download_file(self.service, file['id'], movie_name, base_path)

                elif match_file:
                    file_id = match_file.group(1)
                    ext = os.path.splitext(name)[1] if "." in name else ".mp4"
                    movie_name = f"{safe_title} ({year}) [tmdbid-{tmdb_id}]{ext}"
                    download_file(self.service, file_id, movie_name, base_path)

                else:
                    print("Could not parse Google Drive link:", url)

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

                match_folder = re.search(r"/folders/([a-zA-Z0-9_-]+)", url)
                match_file = re.search(r"/file/d/([a-zA-Z0-9_-]+)", url)

                if match_folder:
                    folder_id = match_folder.group(1)
                    files = list_files_in_folder(self.service, folder_id)
                    files = sorted(files, key=lambda f: f['name'])
                    for file in files:
                        ext = os.path.splitext(file['name'])[1]
                        episode_name = f"{safe_title} S{season_num:02d}E{episode_counter:02d}{ext}"
                        download_file(self.service, file['id'], episode_name, base_path)
                        episode_counter += 1

                elif match_file:
                    file_id = match_file.group(1)
                    ext = os.path.splitext(name)[1] if "." in name else ".mp4"
                    episode_name = f"{safe_title} S{season_num:02d}E{episode_counter:02d}{ext}"
                    download_file(self.service, file_id, episode_name, base_path)
                    episode_counter += 1

                else:
                    print("Could not parse Google Drive link:", url)
