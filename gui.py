import os
import re
import time
from typing import Optional

from torrenter import QBittorrentClient
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
    QListWidget,
    QListWidgetItem,
    QHBoxLayout,
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
            if anime_name.endswith("-m"):
                is_movie = True
                anime_name = anime_name[:-2]
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
                if tmdb_id == "unknown":
                    self.progress_text.emit(f"⚠️ No TMDB info found for '{tmdb_query}'. Using defaults.")
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
                    ext = os.path.splitext(name)[1] if "." in name else ".mkv"
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
        # Initialize instance attributes
        self.torrent_file_list: Optional[QListWidget] = None
        self.torrent_url: Optional[QLineEdit] = None
        self.load_torrent_btn: Optional[QPushButton] = None
        self.select_all_btn: Optional[QPushButton] = None
        self.deselect_all_btn: Optional[QPushButton] = None
        self.download_selected_btn: Optional[QPushButton] = None

        self.is_movie = None
        self.auto_update_chromedriver = False
        self.qbittorrent_auto_connect = False
        self.worker = None
        self.service = authenticate_drive_api()
        self.query = None
        self.chromedriver_auto_update_action = None
        self.disconnect_qbittorrent_action = None
        self.qbittorrent_auto_connect_action = None

        # GUI widgets (shared)
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
        self.setFixedSize(600, 600)

        self.load_settings()
        self.create_menu_bar()
        self.setup_ui()
        self.qb_client_obj: Optional[QBittorrentClient] = None

        if self.auto_update_chromedriver:
            update_chromedriver(self.progress_log.append)

        self.qb_client_obj = QBittorrentClient(
            log_callback=self.progress_log.append,
            auto_connect=self.qbittorrent_auto_connect
        )

    def setup_ui(self):
        """Set up the main UI components (default Kayoanime screen)"""
        # Use a grid layout for the central widget
        self.layout = QGridLayout()

        # Input section
        self.anime_label = QLabel('Enter anime name / Google drive link / Drive folder id:')
        self.anime_name = QLineEdit(placeholderText='Anime name / Drive link / Drive id')
        self.scrape_button = QPushButton('Scrape')
        self.scrape_button.clicked.connect(self.scrape_anime_name)

        # Shared log and progress bars
        self.progress_log = QTextEdit()
        self.progress_log.setReadOnly(True)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.file_progress_bar = QProgressBar()
        self.file_progress_bar.setValue(0)

        # Add default widgets to layout
        self.layout.addWidget(self.anime_label, 0, 0)
        self.layout.addWidget(self.anime_name, 1, 0)
        self.layout.addWidget(self.scrape_button, 1, 1)
        self.layout.addWidget(self.progress_log, 2, 0, 1, 2)
        self.layout.addWidget(self.file_progress_bar, 3, 0, 1, 2)
        self.layout.addWidget(self.progress_bar, 4, 0, 1, 2)

        # Apply layout to central widget
        self.widget = QWidget()
        self.widget.setLayout(self.layout)
        self.setCentralWidget(self.widget)

    def clear_layout(self):
        """Helper: remove all widgets from layout (but don't destroy shared objects)"""
        # remove widgets from layout
        for i in reversed(range(self.layout.count())):
            item = self.layout.itemAt(i)
            if item is None:
                continue
            widget = item.widget()
            if widget:
                # detach widget from layout/parent but don't delete shared objects
                widget.setParent(None)

    def load_default_screen(self):
        """Restore the normal scrape UI (reuse shared log and progress bars)."""
        # Remove current widgets
        self.clear_layout()

        # Recreate default input widgets (but reuse progress_log and progress bars)
        self.anime_label = QLabel('Enter anime name / Google drive link / Drive folder id:')
        self.anime_name = QLineEdit(placeholderText='Anime name / Drive link / Drive id')
        self.scrape_button = QPushButton('Scrape')
        self.scrape_button.clicked.connect(self.scrape_anime_name)

        # Add widgets back into the shared layout
        self.layout.addWidget(self.anime_label, 0, 0)
        self.layout.addWidget(self.anime_name, 1, 0)
        self.layout.addWidget(self.scrape_button, 1, 1)
        self.layout.addWidget(self.progress_log, 2, 0, 1, 2)
        self.layout.addWidget(self.file_progress_bar, 3, 0, 1, 2)
        self.layout.addWidget(self.progress_bar, 4, 0, 1, 2)

    def load_torrent_screen(self):
        """Build the Torrent UI but reuse the same progress log and bars."""
        self.clear_layout()

        # Torrent URL input + load button
        url_label = QLabel("Enter Torrent / Magnet URL:")
        self.torrent_url = QLineEdit()
        self.torrent_url.setPlaceholderText("Torrent / Magnet url")

        self.load_torrent_btn = QPushButton("Load Torrent")
        self.load_torrent_btn.clicked.connect(self.load_torrent_info)

        # File list with checkboxes
        self.torrent_file_list = QListWidget()
        self.torrent_file_list.setSelectionMode(QListWidget.SingleSelection)
        self.torrent_file_list.setMinimumHeight(220)

        # Buttons for selection + download
        btn_row = QHBoxLayout()
        self.select_all_btn = QPushButton("Select All")
        self.select_all_btn.clicked.connect(self.select_all_files)
        self.deselect_all_btn = QPushButton("Deselect All")
        self.deselect_all_btn.clicked.connect(self.deselect_all_files)
        self.download_selected_btn = QPushButton("Download Selected")
        self.download_selected_btn.clicked.connect(self.download_selected_files)

        btn_row.addWidget(self.select_all_btn)
        btn_row.addWidget(self.deselect_all_btn)
        btn_row.addWidget(self.download_selected_btn)

        # Add everything to the shared layout, then reuse log + progress bars below
        # Put URL row
        self.layout.addWidget(url_label, 0, 0)
        self.layout.addWidget(self.torrent_url, 1, 0)
        self.layout.addWidget(self.load_torrent_btn, 1, 1)

        # File list label + widget
        self.layout.addWidget(QLabel("Files in torrent (check to download):"), 2, 0, 1, 2)
        self.layout.addWidget(self.torrent_file_list, 3, 0, 1, 2)

        # Buttons
        container = QWidget()
        container.setLayout(btn_row)
        self.layout.addWidget(container, 4, 0, 1, 2)

        # Shared log/progress bars below
        self.layout.addWidget(self.progress_log, 5, 0, 1, 2)
        self.layout.addWidget(self.file_progress_bar, 6, 0, 1, 2)
        self.layout.addWidget(self.progress_bar, 7, 0, 1, 2)

    def load_torrent_info(self):
        """Add torrent to qbittorrent (as needed) and populate file list with checkboxes."""
        url = self.torrent_url.text().strip()
        if not url:
            QMessageBox.warning(self, "Input Required", "Enter a torrent or magnet URL.")
            return

        if not self.qb_client_obj or not self.qb_client_obj.is_connected:
            QMessageBox.warning(self, "qBittorrent", "Not connected to qBittorrent.")
            return

        try:
            client = self.qb_client_obj._client
            self.progress_log.append(f"Adding torrent: {url}")
            # Add the torrent (we won't try to control paused/started behavior strictly here)
            # qbittorrentapi accepts `urls` argument
            try:
                client.torrents_add(urls=url)
            except Exception as e:
                # Some versions raise descriptive exceptions; log and continue to query torrents_info
                self.progress_log.append(f"Warning while adding torrent: {e}")

            # Wait briefly so qBittorrent can register the new torrent and its metadata
            time.sleep(1)

            # Fetch torrent list and pick the most recent torrent that matches the magnet or name
            torrents = client.torrents_info()
            if not torrents:
                QMessageBox.warning(self, "Error", "Unable to load torrent information.")
                return

            # Try to find the most recently added torrent (last in list is often newest)
            latest = torrents[-1]
            torrent_hash = getattr(latest, "hash", None) or latest.get("hash")

            if not torrent_hash:
                QMessageBox.warning(self, "Error", "Could not determine torrent hash.")
                return

            self.progress_log.append(f"Loaded torrent: {latest.get('name') if isinstance(latest, dict) else getattr(latest, 'name', 'unknown')} (hash: {torrent_hash})")

            # Get files for that torrent
            files = client.torrents_files(torrent_hash)
            # files is a list-like of dicts/objects with fields like 'name' and 'size' etc.
            # Populate the QListWidget with checkboxes
            self.torrent_file_list.clear()
            for f in files:
                # `f` may be a dict or object; handle both
                fname = f.get("name") if isinstance(f, dict) else getattr(f, "name", str(f))
                fsize = None
                try:
                    fsize = int(f.get("size")) if isinstance(f, dict) and f.get("size") is not None else int(getattr(f, "size", 0))
                except Exception:
                    fsize = None

                display_text = fname
                if fsize:
                    # human-readable size
                    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
                        if fsize < 1024.0:
                            display_text = f"{fname} — {fsize:3.1f}{unit}"
                            break
                        fsize /= 1024.0

                item = QListWidgetItem(display_text)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Unchecked)
                self.torrent_file_list.addItem(item)

            self.progress_log.append(f"Found {self.torrent_file_list.count()} files in torrent.")
            # store last loaded torrent hash on the UI for later operations
            self._last_loaded_torrent_hash = torrent_hash

        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to load torrent info: {e}")
            self.progress_log.append(f"Error loading torrent info: {e}")

    def select_all_files(self):
        if not self.torrent_file_list:
            return
        for i in range(self.torrent_file_list.count()):
            item = self.torrent_file_list.item(i)
            item.setCheckState(Qt.Checked)

    def deselect_all_files(self):
        if not self.torrent_file_list:
            return
        for i in range(self.torrent_file_list.count()):
            item = self.torrent_file_list.item(i)
            item.setCheckState(Qt.Unchecked)

    def get_selected_torrent_file_indices(self):
        """Return list of indices (0-based) of checked items in the torrent list."""
        if not self.torrent_file_list:
            return []
        selected_indices = []
        for i in range(self.torrent_file_list.count()):
            item = self.torrent_file_list.item(i)
            if item.checkState() == Qt.Checked:
                selected_indices.append(i)
        return selected_indices

    def download_selected_files(self):
        """Add torrent (again if needed) and try to set file priorities so only selected files download."""
        selected_indices = self.get_selected_torrent_file_indices()
        if not selected_indices:
            QMessageBox.warning(self, "No files selected", "Please select at least one file to download.")
            return

        if not hasattr(self, "_last_loaded_torrent_hash") or not self._last_loaded_torrent_hash:
            QMessageBox.warning(self, "Torrent not loaded", "Please load the torrent first (Load Torrent).")
            return

        if not self.qb_client_obj or not self.qb_client_obj.is_connected:
            QMessageBox.warning(self, "qBittorrent", "Not connected to qBittorrent.")
            return

        client = self.qb_client_obj._client
        torrent_hash = self._last_loaded_torrent_hash
        self.progress_log.append(f"Preparing to download {len(selected_indices)} file(s) from torrent {torrent_hash}")

        # Attempt to set file priorities: set selected files to normal/high and others to skip
        # qbittorrent webapi uses file ids (0-based indices) in the filePrio endpoint.
        # Different qbittorrentapi versions expose different method names — try common ones.
        try_methods = [
            ("torrents_file_priority", {"torrent_hash": torrent_hash, "file_ids": selected_indices, "priority": 1}),
            ("torrents_set_file_priority", {"torrent_hash": torrent_hash, "file_ids": selected_indices, "priority": 1}),
            ("torrents_file_prio", {"torrent_hash": torrent_hash, "file_ids": selected_indices, "priority": 1}),
            ("torrents_file_priority", {"torrent_hash": torrent_hash, "file_ids": selected_indices, "priority": 1}),
            ("file_priority", {"torrent_hash": torrent_hash, "file_ids": selected_indices, "priority": 1}),
        ]

        succeeded = False
        # first, set all files to "skip" (priority 0 or 0 means do not download) if possible, then enable selected.
        try:
            # try to set all files to priority 0 (skip) if the API supports it
            # Build list of all indices
            all_indices = list(range(self.torrent_file_list.count()))
            for method_name, params in try_methods:
                func = getattr(client, method_name, None)
                if callable(func):
                    try:
                        # attempt to set all to 0 first (skip)
                        # adapt param names if necessary
                        call_kwargs = {}
                        if "torrent_hash" in params:
                            call_kwargs["torrent_hash"] = torrent_hash
                        if "file_ids" in params:
                            call_kwargs["file_ids"] = all_indices
                        call_kwargs["priority"] = 0
                        func(**call_kwargs)
                        succeeded = True
                        break
                    except Exception:
                        # try the next method
                        continue
        except Exception:
            pass

        # Now set selected ones to normal (priority 1)
        set_selected_ok = False
        for method_name, params in try_methods:
            func = getattr(client, method_name, None)
            if callable(func):
                try:
                    call_kwargs = {}
                    if "torrent_hash" in params:
                        call_kwargs["torrent_hash"] = torrent_hash
                    if "file_ids" in params:
                        call_kwargs["file_ids"] = selected_indices
                    call_kwargs["priority"] = 1
                    func(**call_kwargs)
                    set_selected_ok = True
                    break
                except Exception as e:
                    # log and try next
                    self.progress_log.append(f"API method {method_name} failed to set priorities: {e}")
                    continue

        if set_selected_ok:
            self.progress_log.append("Successfully set file priorities for selected files. Download should begin shortly.")
        else:
            # If we couldn't set priorities via API, log it and fall back to adding the torrent normally.
            self.progress_log.append("Could not programmatically set file priorities on this qBittorrent API version.")
            self.progress_log.append("Torrent is added — please open qBittorrent and manually uncheck unwanted files if necessary.")

        # Optionally: start/resume torrent to begin download
        try:
            # resume torrent to ensure it will download
            resume_func = getattr(client.torrents_resume, "all", None)
            # many versions support client.torrents_resume(torrent_hashes=...) or client.torrents_resume()
            if hasattr(client, "torrents_resume"):
                try:
                    client.torrents_resume(torrent_hashes=torrent_hash)
                except Exception:
                    # try simple resume
                    try:
                        client.torrents_resume()
                    except Exception:
                        pass
            self.progress_log.append("Triggered torrent resume/start.")
        except Exception:
            pass

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
                    if line.startswith("auto_connect_qbittorrent="):
                        value = line.split("=")[1].strip()
                        self.qbittorrent_auto_connect = (value == "1")
        except Exception as e:
            print(f"Error loading settings: {e}")
            self.auto_update_chromedriver = False
            self.qbittorrent_auto_connect = False

    def save_settings(self):
        """Save settings to settings.txt file"""
        try:
            with open("settings.txt", "w") as file:
                file.write(f"auto_update_chromedriver={'1' if self.auto_update_chromedriver else '0'}\n")
                file.write(f"auto_connect_qbittorrent={'1' if self.qbittorrent_auto_connect else '0'}\n")
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
        chromedriver_update_action.triggered.connect(lambda: update_chromedriver(self.progress_log.append))
        tools_menu.addAction(chromedriver_update_action)

        # Connect action
        qbittorrent_connect_action = QAction("Connect to qBittorrent", self)
        qbittorrent_connect_action.triggered.connect(self.manual_connect_qbittorrent)
        tools_menu.addAction(qbittorrent_connect_action)

        # Disconnect action
        disconnect_action = QAction("Disconnect from qBittorrent", self)
        disconnect_action.triggered.connect(self.disconnect_qbittorrent)
        tools_menu.addAction(disconnect_action)

        # Create checkbox action for auto-update
        self.chromedriver_auto_update_action = QAction("Auto Update Chromedriver", self)
        self.chromedriver_auto_update_action.setCheckable(True)
        self.chromedriver_auto_update_action.setChecked(self.auto_update_chromedriver)
        self.chromedriver_auto_update_action.triggered.connect(self.toggle_auto_update_chromedriver)
        tools_menu.addAction(self.chromedriver_auto_update_action)

        self.qbittorrent_auto_connect_action = QAction("Auto Connect qBittorrent", self)
        self.qbittorrent_auto_connect_action.setCheckable(True)
        self.qbittorrent_auto_connect_action.setChecked(self.qbittorrent_auto_connect)
        self.qbittorrent_auto_connect_action.triggered.connect(self.toggle_auto_connect_qbittorrent)
        tools_menu.addAction(self.qbittorrent_auto_connect_action)

        # Provider Menu
        provider_menu = menubar.addMenu("Provider")
        provider_action = QAction("Kayoanime", self)
        provider_action.triggered.connect(self.load_default_screen)
        provider_menu.addAction(provider_action)

        # Torrent
        torrent_action = QAction("Torrent", self)
        torrent_action.triggered.connect(self.load_torrent_screen)
        provider_menu.addAction(torrent_action)

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

    def toggle_auto_connect_qbittorrent(self):
        self.qbittorrent_auto_connect = self.qbittorrent_auto_connect_action.isChecked()
        self.save_settings()
        status = "enabled" if self.qbittorrent_auto_connect else "disabled"
        self.progress_log.append(f"Auto connect qBittorrent: {status}")

        if not self.qb_client_obj:
            self.qb_client_obj = QBittorrentClient(log_callback=self.progress_log.append)

        if self.qbittorrent_auto_connect and not self.qb_client_obj.is_connected:
            self.qb_client_obj.connect()
        elif not self.qbittorrent_auto_connect and self.qb_client_obj.is_connected:
            self.qb_client_obj.disconnect()

    def manual_connect_qbittorrent(self):
        if not self.qb_client_obj:
            self.qb_client_obj = QBittorrentClient(log_callback=self.progress_log.append)

        if self.qb_client_obj.is_connected:
            self.progress_log.append("ℹ️ Already connected to qBittorrent!")
        else:
            self.qb_client_obj.connect()

    def disconnect_qbittorrent(self):
        if self.qb_client_obj and self.qb_client_obj.is_connected:
            self.qb_client_obj.disconnect()
        else:
            self.progress_log.append("ℹ️ No qBittorrent connection to disconnect.")

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
        self.is_movie = True if self.query.endswith("-m") else False
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
