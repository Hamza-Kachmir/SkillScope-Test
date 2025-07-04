import requests
from bs4 import BeautifulSoup
import json
import re
import time
import random
import logging
from urllib.parse import quote_plus
# from datetime import datetime

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from src.config import (
    HEADERS, BASE_WTTJ_URL, SEARCH_RESULTS_SELECTOR,
    JOB_CARD_SELECTOR, COOKIE_BUTTON_ID
)

class WTTJScraper:
    def __init__(self, headless: bool = True, wait_time: int = 20):
        self.wait_time = wait_time
        self.driver = self._setup_driver(headless)
        self.cookies = None
        if self.driver:
            self.wait = WebDriverWait(self.driver, self.wait_time)

    def _setup_driver(self, headless: bool) -> webdriver.Chrome | None:
        try:
            options = webdriver.ChromeOptions()
            if headless:
                options.add_argument("--headless=new")
                options.add_argument("--window-size=1920,1080")
            
            # --- DÉBUT DES AJOUTS POUR CONTOURNER LA DÉTECTION ---
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-gpu")
            options.add_argument("--disable-notifications")
            options.add_argument("--disable-blink-features=AutomationControlled") # Empêche la détection par la propriété navigator.webdriver
            options.add_experimental_option("excludeSwitches", ["enable-automation"]) # Supprime l'infobar "Chrome est contrôlé par un logiciel de test"
            options.add_experimental_option('useAutomationExtension', False) # Désactive l'extension d'automatisation
            
            # Change le user-agent pour qu'il ressemble plus à un navigateur normal
            # Assure-toi que ce User-Agent est à jour. Tu peux le trouver en tapant "my user agent" sur Google.
            options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
            
            # Empêche d'autres détections JavaScript
            options.add_argument("--disable-extensions")
            options.add_argument("--incognito") # Mode incognito
            # --- FIN DES AJOUTS POUR CONTOURNER LA DÉTECTION ---

            driver = webdriver.Chrome(options=options)
            
            # --- DÉBUT DE L'AJUSTEMENT POST-INITIALISATION ---
            # Exécute un script JS pour cacher encore plus le mode automation
            driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
                'source': '''
                    Object.defineProperty(navigator, 'webdriver', {
                        get: () => undefined
                    })
                '''
            })
            # --- FIN DE L'AJUSTEMENT POST-INITIALISATION ---

            logging.info("Driver Selenium initialisé avec succès.")
            return driver
        except Exception as e:
            logging.critical(f"Erreur critique lors de l'initialisation du driver: {e}", exc_info=True)
            return None

    def _accept_cookies(self):
        try:
            cookie_button = WebDriverWait(self.driver, 3).until(
                EC.element_to_be_clickable((By.ID, COOKIE_BUTTON_ID))
            )
            cookie_button.click()
            logging.info("Cookies acceptés.")
            time.sleep(random.uniform(0.3, 0.8))
        except Exception:
            logging.info("Bannière de cookies non trouvée ou déjà acceptée.")

    def search_and_scrape_jobs(self, search_term: str, num_pages: int = 2) -> list[dict]:
        if not self.driver:
            return []
        search_term_encoded = quote_plus(search_term)
        all_offers = []
        urls_seen = set()
        
        for page_number in range(1, num_pages + 1):
            search_url = f"{BASE_WTTJ_URL}/fr/jobs?query={search_term_encoded}&page={page_number}"
            logging.info(f"Navigation vers l'URL de recherche : {search_url}")
            self.driver.get(search_url)

            try:
                time.sleep(2)
                logging.info(f"Début de la capture HTML de la page {page_number}.")
                
                page_html_content = self.driver.page_source
                
                max_log_chars = 5000 
                
                if len(page_html_content) > max_log_chars:
                    logging.info(f"HTML Page {page_number} (Début): {page_html_content[:max_log_chars // 2]}...")
                    logging.info(f"HTML Page {page_number} (Fin): ...{page_html_content[-max_log_chars // 2:]}")
                else:
                    logging.info(f"HTML Page {page_number} (Complet): {page_html_content}")
                
                logging.info(f"Fin de la capture HTML de la page {page_number}.")

            except Exception as html_log_e:
                logging.warning(f"Impossible d'afficher le HTML de débogage dans les logs: {html_log_e}")

            try:
                self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, SEARCH_RESULTS_SELECTOR)))
                logging.info(f"Page {page_number} chargée.")

                if page_number == 1:
                    self._accept_cookies()
                    self.cookies = self.driver.get_cookies()
                
                time.sleep(random.uniform(1.5, 2.5))
                soup = BeautifulSoup(self.driver.page_source, 'html.parser')
                cards = soup.select(JOB_CARD_SELECTOR)
                logging.info(f"{len(cards)} offres trouvées sur la page {page_number}.")

                if not cards:
                    break

                for card in cards:
                    title_el = card.find('h2')
                    company_img_el = card.find('img', alt=True)
                    link_el = card.find('a', href=True)
                    if title_el and company_img_el and link_el:
                        url = BASE_WTTJ_URL + link_el["href"]
                        if url not in urls_seen:
                            urls_seen.add(url)
                            all_offers.append({"titre": title_el.text.strip(), "entreprise": company_img_el['alt'].strip(), "url": url})
            except Exception as e:
                logging.error(f"Problème lors du parsing de la page {page_number}: {e}", exc_info=True)
                break
        
        logging.info(f"Scraping initial terminé. Total d'offres collectées : {len(all_offers)}.")
        return all_offers

    def close_driver(self):
        if self.driver:
            logging.info("Fermeture du driver Selenium."); self.driver.quit(); self.driver = None

def get_job_details(url: str, cookies: list[dict]) -> dict:
    time.sleep(random.uniform(0.1, 0.5))
    details = {'description': None, 'tags': []}
    session = requests.Session()
    session.headers.update(HEADERS)
    for cookie in cookies:
        session.cookies.set(cookie['name'], cookie['value'], domain=cookie['domain'])
    try:
        resp = session.get(url, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        job_data = None
        script_initial = soup.find("script", string=re.compile("window.__INITIAL_DATA__"))
        if script_initial:
            match = re.search(r'window\.__INITIAL_DATA__\s*=\s*(.*?)\s*window\.__FLAGS_DATA__', script_initial.string, re.DOTALL)
            if match:
                json_data_raw = match.group(1).strip().rstrip(';')
                if json_data_raw.startswith('"') and json_data_raw.endswith('"'):
                   json_data_raw = json.loads(json_data_raw)
                parsed_data = json.loads(json_data_raw) if isinstance(json_data_raw, str) else json_data_raw
                job_data = parsed_data.get('queries', [{}])[0].get('state', {}).get('data', {})
        if job_data:
            description_html = job_data.get('description', '')
            profile_html = job_data.get('profile', '')
            details['description'] = BeautifulSoup(f"{description_html}\n\n{profile_html}", 'html.parser').get_text("\n", strip=True)
            skills_fr = {s['name']['fr'].strip().title() for s in job_data.get('skills', []) if isinstance(s.get('name'), dict) and s.get('name', {}).get('fr')}
            tools = {t['name'].strip().title() for t in job_data.get('tools', []) if t.get('name')}
            details['tags'] = sorted(list(skills_fr | tools))
        else:
            main_content = soup.find('main')
            if main_content:
                details['description'] = main_content.get_text("\n", strip=True)
    except requests.exceptions.HTTPError as http_err:
        logging.warning(f"⚠️ Erreur HTTP {http_err.response.status_code} pour {url}. Offre ignorée.")
    except Exception as e:
        logging.error(f"❌ Erreur non gérée pour {url}: {e}", exc_info=True)
    return details