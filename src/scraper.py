import requests
from bs4 import BeautifulSoup
import json
import re
import time
import random
import logging
from urllib.parse import quote_plus
from typing import List, Dict

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException

from src.config import HEADERS, APEC_BASE_URL, APEC_SEARCH_URL_PATH, APEC_JOB_CARD_SELECTOR, APEC_JOB_CARD_TITLE_SELECTOR, APEC_JOB_CARD_COMPANY_SELECTOR, APEC_JOB_CARD_URL_SELECTOR, APEC_COOKIE_BUTTON_ID

class APECScraper:
    """
    Un scraper pour APEC utilisant Selenium pour la navigation initiale sur les pages de recherche dynamiques.
    """
    def __init__(self, headless: bool = True, wait_time: int = 45):
        self.wait_time = wait_time
        self.driver = self._setup_driver(headless)
        self.cookies = None # Pour stocker les cookies après acceptation
        if self.driver:
            self.wait = WebDriverWait(self.driver, self.wait_time)

    def _setup_driver(self, headless: bool) -> webdriver.Chrome | None:
        """
        Configure et initialise l'instance du driver Chrome avec des options optimisées.
        """
        try:
            options = webdriver.ChromeOptions()
            if headless:
                options.add_argument("--headless=new")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-gpu")
            options.add_argument("--window-size=1920,1080")
            options.add_argument("--disable-notifications")
            # Ajout d'un User-Agent pour être plus crédible (si non géré par HEADERS globalement)
            options.add_argument(f"user-agent={HEADERS['User-Agent']}") 
            
            driver = webdriver.Chrome(options=options)
            logging.info("Driver Selenium initialisé avec succès pour APEC.")
            return driver
        except WebDriverException as e:
            logging.critical(f"Erreur critique lors de l'initialisation du driver Selenium pour APEC: {e}", exc_info=True)
            return None

    def _accept_cookies(self):
        """
        Trouve et clique sur le bouton d'acceptation des cookies s'il est présent.
        """
        try:
            # APEC utilise OneTrust, le bouton a souvent l'ID 'onetrust-accept-btn-handler'
            cookie_button = WebDriverWait(self.driver, 5).until( # Attendre max 5s
                EC.element_to_be_clickable((By.ID, APEC_COOKIE_BUTTON_ID))
            )
            cookie_button.click()
            logging.info("APEC : Cookies acceptés.")
            time.sleep(random.uniform(0.5, 1.0)) # Petite pause
        except TimeoutException:
            logging.info("APEC : Bannière de cookies non trouvée ou déjà acceptée (Timeout).")
        except Exception as e:
            logging.warning(f"APEC : Erreur lors de l'acceptation des cookies: {e}")

    def search_and_scrape_job_urls(self, search_term: str, num_pages: int = 2) -> list[dict]:
        """
        Navigue sur les pages de résultats de recherche APEC et extrait les URLs des offres.
        """
        if not self.driver:
            logging.error("Driver Selenium non initialisé pour APEC. Abandon de la recherche.")
            return []

        search_term_encoded = quote_plus(search_term)
        all_offers_metadata = []
        urls_seen = set()

        for page_number in range(num_pages): # APEC uses 0-indexed pages for search payload, but URL might vary
            # Construction de l'URL de recherche APEC. APEC peut ne pas avoir une simple page=X pour la pagination
            # On va tenter une URL générique et voir si le contenu est là.
            # L'API APEC utilise `startIndex` et `range`, mais si on scrape le site, il faut observer comment leur pagination fonctionne
            # En général, les sites APEC/WTTJ chargent dynamiquement. Pour simuler une pagination front-end,
            # on pourrait chercher les boutons "page suivante" ou manipuler les paramètres d'URL s'ils sont simples.
            # Pour l'instant, nous allons construire une URL simple et supposer qu'elle affiche les premiers résultats.
            # L'APEC expose aussi une pagination via des numéros de page dans les liens, ex: ...page=2
            # Cependant, l'API est souvent plus fiable pour la pagination sans headless.
            # Ici, comme on utilise Selenium, on peut naviguer sur des URLs avec param page.

            # Exemple d'URL APEC pour recherche avec pagination:
            # https://www.apec.fr/candidat/recherche-emploi.html/emploi/recherche-offres.html?motsCles=UX%20Designer&page=1
            search_url = f"{APEC_BASE_URL}{APEC_SEARCH_URL_PATH}?motsCles={search_term_encoded}&page={page_number}"
            
            logging.info(f"APEC Scraper (Selenium) : Navigation vers l'URL de recherche : {search_url}")
            self.driver.get(search_url)

            # Accepter les cookies la première fois
            if page_number == 0:
                self._accept_cookies()
                # Récupérer les cookies pour les futures requêtes requests.get
                self.cookies = self.driver.get_cookies()
            
            try:
                # Attendre que les résultats de recherche soient chargés (ex: un élément qui contient les offres)
                # Le sélecteur `apec-recherche-resultat` correspond aux cartes d'offres individuelles.
                self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, APEC_JOB_CARD_SELECTOR)))
                logging.info(f"APEC Scraper (Selenium) : Page {page_number} chargée avec des offres.")
                
                time.sleep(random.uniform(1.5, 2.5)) # Laisser le temps au contenu de se charger

                soup = BeautifulSoup(self.driver.page_source, 'html.parser')
                # Les cartes d'offres sont des liens cliquables
                job_cards = soup.select(APEC_JOB_CARD_SELECTOR)
                logging.info(f"APEC Scraper (Selenium) : {len(job_cards)} cartes d'offres trouvées sur la page {page_number}.")

                if not job_cards:
                    logging.warning("APEC Scraper (Selenium) : Aucune carte d'offre trouvée sur cette page. Arrêt de la pagination.")
                    break
                
                for card in job_cards:
                    # Le titre est souvent dans une h2 à l'intérieur de la carte
                    title_el = card.select_one(APEC_JOB_CARD_TITLE_SELECTOR)
                    # Le nom de l'entreprise est souvent dans un p.card-offer__company
                    company_el = card.select_one(APEC_JOB_CARD_COMPANY_SELECTOR)
                    # L'URL est le href du <a> direct de la carte
                    link_el = card.select_one(APEC_JOB_CARD_URL_SELECTOR) # Ou simplement card['href'] si le <a> est la carte elle-même
                    
                    if title_el and company_el and link_el and 'href' in link_el.attrs:
                        # Les URLs APEC sont souvent relatives ou commencent par /candidat/...
                        # Nous devons nous assurer qu'elles sont complètes.
                        relative_url = link_el['href']
                        if not relative_url.startswith('http'):
                            # S'assurer que l'URL de base ne se termine pas par '/' si l'URL relative commence par '/'
                            url = APEC_BASE_URL.rstrip('/') + relative_url if relative_url.startswith('/') else f"{APEC_BASE_URL}/{relative_url}"
                        else:
                            url = relative_url

                        if url not in urls_seen:
                            urls_seen.add(url)
                            all_offers_metadata.append({
                                "titre": title_el.get_text(strip=True),
                                "entreprise": company_el.get_text(strip=True),
                                "url": url
                            })
            except TimeoutException:
                logging.warning(f"APEC Scraper (Selenium) : Timeout en attendant les éléments de la page {page_number}. Pas d'offres ou page vide.")
                break # Arrêter si on ne trouve plus d'éléments de résultats
            except Exception as e:
                logging.error(f"APEC Scraper (Selenium) : Erreur lors du parsing de la page {page_number}: {e}", exc_info=True)
                break
        
        logging.info(f"APEC Scraper (Selenium) : Scraping de la liste des URLs terminé. Total d'offres collectées : {len(all_offers_metadata)}.")
        return all_offers_metadata

    def close_driver(self):
        """
        Ferme proprement le driver Selenium.
        """
        if self.driver:
            logging.info("Fermeture du driver Selenium pour APEC.")
            self.driver.quit()
            self.driver = None

def get_apec_job_details(url: str, session_cookies: List[Dict]) -> Dict:
    """
    Récupère les détails d'une seule offre APEC (description, tags) en utilisant `requests`.
    """
    time.sleep(random.uniform(0.1, 0.5))
    details = {'description': None, 'tags': []}
    
    session = requests.Session()
    session.headers.update(HEADERS)
    for cookie in session_cookies:
        # Les domaines des cookies peuvent parfois causer des problèmes, on peut les rendre plus génériques
        # ou s'assurer qu'ils correspondent au domaine de l'URL de l'offre.
        # Ici, on suppose que le domaine est correct ou peut être ignoré par requests si malformé.
        session.cookies.set(cookie['name'], cookie['value'], domain=cookie.get('domain', '').lstrip('.'))

    try:
        resp = session.get(url, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        
        # Vérifier si l'offre n'est plus disponible
        if "L'offre que vous souhaitez afficher n'est plus disponible" in soup.get_text():
            logging.warning(f"APEC Scraper (Details) : L'offre {url} n'est plus disponible.")
            return details # Retourne des détails vides si l'offre est introuvable

        # Extraction de la description (souvent dans un <p> ou <div> principal)
        # La description est dans le JSON-LD ou dans le corps du texte.
        # Pour l'APEC, elle est souvent dans <div class="details-post"><h4>Descriptif du poste</h4><p>...</p></div>
        description_el = soup.select_one('div.details-post > h4:-soup-contains("Descriptif du poste") + p')
        if description_el:
            details['description'] = description_el.get_text("\n", strip=True)
        else:
            logging.warning(f"APEC Scraper (Details) : Description non trouvée pour {url}.")

        # Extraction des compétences structurées (Langues, Savoir-être, Savoir-faire)
        # SÉLECTEUR AFFINÉ : Cibler les <p> à l'intérieur de <apec-competence-detail>
        skill_elements = soup.select('apec-competence-detail p')
        
        extracted_skills = set()
        for element in skill_elements:
            skill_text = element.get_text(strip=True)
            # Filtre pour éviter les textes vides ou des caractères isolés qui ne sont pas des compétences
            if skill_text and len(skill_text) > 1 and not skill_text.replace('.', '', 1).isdigit(): 
                extracted_skills.add(skill_text)
        
        details['tags'] = sorted(list(extracted_skills))
        logging.info(f"APEC Scraper (Details) : {len(details['tags'])} compétences structurées extraites de {url}.")

    except requests.exceptions.HTTPError as http_err:
        logging.warning(f"APEC Scraper (Details) : Erreur HTTP {http_err.response.status_code} pour {url}. Offre ignorée.")
    except Exception as e:
        logging.error(f"APEC Scraper (Details) : Erreur non gérée pour {url}: {e}", exc_info=True)

    return details