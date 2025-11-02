import re
import time

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as ec
from selenium.common.exceptions import StaleElementReferenceException, TimeoutException

def scrape_tmdb_info(query, content_type="tv"):
    options = webdriver.ChromeOptions()
    options.add_argument("--headless")
    options.add_argument("--window-size=1400,900")
    driver = webdriver.Chrome(options=options)
    wait = WebDriverWait(driver, 10)

    try:
        if content_type == "tv":
            search_url = f"https://www.themoviedb.org/search/tv?query={query.replace(' ', '+')}"
            id_pattern = r"/tv/(\d+)"
            year_pattern = r"^(.*?)\s*\(TV Series (\d{4})"
        else:
            search_url = f"https://www.themoviedb.org/search/movie?query={query.replace(' ', '+')}"
            id_pattern = r"/movie/(\d+)"
            year_pattern = r"^(.*?)\s*\((\d{4})"

        driver.get(search_url)

        try:
            if content_type == "tv":
                cards = wait.until(ec.presence_of_all_elements_located((By.CSS_SELECTOR, "div.card a[href*='/tv/']")))
            else:
                cards = wait.until(ec.presence_of_all_elements_located((By.CSS_SELECTOR, "div.card a[href*='/movie/']")))
        except TimeoutException:
            # No results found
            print(f"[WARN] No TMDB results for query: {query}")
            return query, "0000", "unknown"

        # Extract the first result
        first_link = cards[0].get_attribute("href")
        driver.get(first_link)

        WebDriverWait(driver, 10).until(lambda d: d.title != "")

        full_title = driver.title

        match = re.search(year_pattern, full_title)
        title = match.group(1).strip() if match else query
        year = match.group(2) if match else "0000"

        tmdb_id_match = re.search(id_pattern, first_link)
        tmdb_id = tmdb_id_match.group(1) if tmdb_id_match else "unknown"

        return title, year, tmdb_id

    except Exception as e:
        print(f"[ERROR] TMDB scrape failed for '{query}': {e}")
        return query, "0000", "unknown"

    finally:
        driver.quit()


def scrape_drive_links(query):
    options = webdriver.ChromeOptions()
    options.add_argument("--window-size=1400,900")
    driver = webdriver.Chrome(options=options)
    wait = WebDriverWait(driver, 15)
    results = []

    try:
        driver.get("https://kayoanime.com/")

        search_box = wait.until(ec.element_to_be_clickable((By.CSS_SELECTOR, "input[name='s']")))
        search_box.clear()
        search_box.send_keys(query)
        search_box.send_keys(Keys.RETURN)

        for _ in range(3):
            try:
                first_result = wait.until(ec.presence_of_element_located((By.CSS_SELECTOR, ".post-title a")))
                driver.execute_script("arguments[0].scrollIntoView(true);", first_result)
                first_result.click()
                break
            except StaleElementReferenceException:
                time.sleep(1)

        time.sleep(3)

        links = driver.find_elements(By.TAG_NAME, "a")
        for link in links:
            href = link.get_attribute("href")
            if href and "drive.google.com" in href:
                text = link.text.strip() or "(no text)"
                results.append([text, href])

    finally:
        driver.quit()
        return results