import os
import re
import winreg
import zipfile
import requests
import subprocess
from typing import Callable, Optional


def update_chromedriver(log_callback: Optional[Callable[[str], None]] = print):
    """
    One-click function to update ChromeDriver to match your installed Chrome version.
    Only downloads new version if there's a mismatch.
    Returns the path to chromedriver.exe for immediate use with Selenium.
    """
    try:
        log_callback("🔍 Checking Chrome version...")
        chrome_version = _get_chrome_version(log_callback)
        log_callback(f"✅ Installed Chrome version: {chrome_version}")

        major_version = _get_major_version(chrome_version)
        log_callback(f"✅ Chrome major version: {major_version}")

        # Check if we already have a compatible chromedriver
        chromedriver_path = os.path.join(os.getcwd(), "chromedriver.exe")
        if _is_chromedriver_compatible(chromedriver_path, major_version, log_callback):
            log_callback("✅ ChromeDriver is already up-to-date!")
            return chromedriver_path

        chromedriver_version = _get_chromedriver_version(major_version)
        log_callback(f"🔄 Corresponding ChromeDriver version: {chromedriver_version}")

        chromedriver_path = _download_chromedriver(chromedriver_version, log_callback)
        log_callback(f"✅ ChromeDriver installed at: {os.path.abspath(chromedriver_path)}")

        # Verify installation
        if os.path.exists(chromedriver_path):
            result = subprocess.run([chromedriver_path, '--version'], capture_output=True, text=True, check=False)
            log_callback(f"✅ Verification: {result.stdout.strip()}")

        log_callback("🎉 ChromeDriver update completed successfully!")
        return chromedriver_path

    except Exception as e:
        log_callback(f"❌ Error: {e}")
        log_callback("\n💡 Troubleshooting tips:")
        log_callback("1. Make sure Chrome is installed")
        log_callback("2. Check your internet connection")
        log_callback("3. Run the script as administrator if needed")
        raise


def _is_chromedriver_compatible(chromedriver_path: str, expected_major_version: str,
                               log_callback: Optional[Callable[[str], None]] = print) -> bool:
    """
    Check if existing ChromeDriver is compatible with current Chrome version
    """
    if not os.path.exists(chromedriver_path):
        log_callback("📥 ChromeDriver not found, will download...")
        return False

    try:
        # Get current chromedriver version
        result = subprocess.run([chromedriver_path, '--version'], capture_output=True, text=True, check=False)
        if result.returncode != 0:
            log_callback("⚠️  Existing ChromeDriver is corrupted, will reinstall...")
            return False

        # Extract version from output
        version_output = result.stdout.strip()
        version_match = re.search(r'ChromeDriver\s+(\d+\.\d+\.\d+\.\d+)', version_output)

        if not version_match:
            log_callback("⚠️  Could not parse ChromeDriver version, will reinstall...")
            return False

        current_chromedriver_version = version_match.group(1)
        current_major = _get_major_version(current_chromedriver_version)

        if current_major == expected_major_version:
            log_callback(f"✅ ChromeDriver {current_chromedriver_version} is compatible with Chrome major version {expected_major_version}")
            return True
        else:
            log_callback(f"🔄 ChromeDriver version mismatch: {current_major} (current) vs {expected_major_version} (required)")
            return False

    except (OSError, subprocess.SubprocessError, ValueError) as e:
        log_callback(f"⚠️  Error checking ChromeDriver compatibility: {e}, will reinstall...")
        return False


def _get_chrome_version(log_callback: Optional[Callable[[str], None]] = print) -> str:
    """Get the installed Chrome version using multiple fallback methods"""

    # Method 1: Try common Chrome installation paths
    chrome_paths = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expanduser(r"~\AppData\Local\Google\Chrome\Application\chrome.exe")
    ]

    chrome_exe = None
    for path in chrome_paths:
        if os.path.exists(path):
            chrome_exe = path
            break

    if not chrome_exe:
        # Method 2: Try to find Chrome in registry
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe") as key:
                chrome_exe, _ = winreg.QueryValueEx(key, "")
        except (OSError, FileNotFoundError):
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                    r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe") as key:
                    chrome_exe, _ = winreg.QueryValueEx(key, "")
            except (OSError, FileNotFoundError):
                pass

    if not chrome_exe or not os.path.exists(chrome_exe):
        raise FileNotFoundError("Chrome not found. Please make sure Chrome is installed.")

    log_callback(f"✅ Chrome found at: {chrome_exe}")

    # Method 3: Get version using PowerShell (most reliable)
    try:
        cmd = f'(Get-Item "{chrome_exe}").VersionInfo.FileVersion'
        result = subprocess.run(
            ['powershell', '-Command', cmd],
            capture_output=True, text=True, check=False
        )
        version = result.stdout.strip()
        if version:
            return version
    except subprocess.SubprocessError:
        pass

    # Method 4: Try to extract version from chrome.exe directly
    try:
        result = subprocess.run(
            [chrome_exe, '--version'],
            capture_output=True, text=True, check=False
        )
        version_match = re.search(r'(\d+\.\d+\.\d+\.\d+)', result.stdout)
        if version_match:
            return version_match.group(1)
    except subprocess.SubprocessError:
        pass

    # Method 5: Try registry version
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Google\Chrome\BLBeacon") as key:
            version, _ = winreg.QueryValueEx(key, "version")
            return version
    except (OSError, FileNotFoundError):
        pass

    raise RuntimeError("Could not determine Chrome version")


def _get_major_version(full_version: str) -> str:
    """Extract major version from full version string"""
    match = re.search(r'^(\d+)', full_version)
    if match:
        return match.group(1)
    raise ValueError(f"Could not extract major version from: {full_version}")


def _get_chromedriver_version(major_version: str) -> str:
    """Get the latest ChromeDriver version for the given major Chrome version"""
    try:
        # Get the latest version information from ChromeDriver download page
        url = "https://googlechromelabs.github.io/chrome-for-testing/known-good-versions.json"
        response = requests.get(url, timeout=30)
        response.raise_for_status()

        data = response.json()

        # Find versions matching our major version
        matching_versions = []
        for version_info in data['versions']:
            if version_info['version'].startswith(f"{major_version}."):
                matching_versions.append(version_info['version'])

        if not matching_versions:
            raise ValueError(f"No ChromeDriver found for Chrome major version {major_version}")

        # Return the latest matching version (last in sorted list)
        latest_version = sorted(matching_versions)[-1]
        return latest_version

    except requests.RequestException as e:
        raise RuntimeError(f"Failed to fetch ChromeDriver version information: {e}")


def _download_chromedriver(version: str, install_dir: str = ".",
                          log_callback: Optional[Callable[[str], None]] = print) -> str:
    """Download and extract ChromeDriver"""
    download_url = f"https://edgedl.me.gvt1.com/edgedl/chrome/chrome-for-testing/{version}/win64/chromedriver-win64.zip"

    try:
        log_callback(f"📥 Downloading ChromeDriver {version}...")
        response = requests.get(download_url, stream=True, timeout=60)
        response.raise_for_status()

        zip_path = os.path.join(install_dir, "chromedriver.zip")
        with open(zip_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)

        log_callback("📦 Extracting ChromeDriver...")
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(install_dir)

        # Clean up
        os.remove(zip_path)

        # Move chromedriver to install directory
        extracted_dir = os.path.join(install_dir, "chromedriver-win64")
        chromedriver_exe = os.path.join(extracted_dir, "chromedriver.exe")
        final_chromedriver_path = os.path.join(install_dir, "chromedriver.exe")

        if os.path.exists(extracted_dir):
            if os.path.exists(final_chromedriver_path):
                os.remove(final_chromedriver_path)
            os.rename(chromedriver_exe, final_chromedriver_path)

            # Clean up empty directory
            try:
                os.rmdir(extracted_dir)
            except OSError:
                # Directory might not be empty, remove remaining files
                for file in os.listdir(extracted_dir):
                    file_path = os.path.join(extracted_dir, file)
                    if os.path.isfile(file_path):
                        os.remove(file_path)
                os.rmdir(extracted_dir)

        return final_chromedriver_path

    except requests.RequestException as e:
        raise RuntimeError(f"Failed to download ChromeDriver: {e}")
    except zipfile.BadZipFile:
        raise RuntimeError("Downloaded file is not a valid ZIP file")