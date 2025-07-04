import requests
import logging
from bs4 import BeautifulSoup
import time
import random
from typing import List, Dict
import re

from src.config import HEADERS

API_URL = "https://www.apec.fr/cms/webservices/rechercheOffre"
BASE_URL = "https://www.apec.fr"

# MODIFICATION TEMPORAIRE : Cette fonction retournera le HTML brut pour le débogage.
# Elle sera remise à jour pour extraire les compétences une fois le HTML inspecté.
def _get_apec_offer_details_from_html(offer_url: str) -> str: # Changement du type de retour à 'str'
    """
    Scrape une page d'offre APEC et retourne son contenu HTML brut pour débogage.
    """
    try:
        time.sleep(random.uniform(0.5, 1.5))
        logging.info(f"APEC HTML Scraper (DEBUG) : Tentative de récupération HTML pour {offer_url}")
        response = requests.get(offer_url, headers=HEADERS, timeout=10)
        response.raise_for_status()

        if "L'offre que vous souhaitez afficher n'est plus disponible" in response.text:
            logging.warning(f"APEC HTML Scraper (DEBUG) : L'offre {offer_url} n'est plus disponible. Retourne HTML vide.")
            return "<html><body><p>Offre non disponible.</p></body></html>" # Retourne un HTML simple pour indiquer
        
        logging.info(f"APEC HTML Scraper (DEBUG) : HTML récupéré pour {offer_url}. Taille : {len(response.text)} caractères.")
        return response.text # Retourne le texte HTML brut

    except requests.exceptions.RequestException as e:
        logging.error(f"APEC HTML Scraper (DEBUG) : Erreur lors de la récupération HTML de {offer_url}: {e}")
        return f"<html><body><p>Erreur de récupération HTML: {e}</p></body></html>"
    except Exception as e:
        logging.error(f"APEC HTML Scraper (DEBUG) : Erreur inattendue lors de la récupération HTML de {offer_url}: {e}", exc_info=True)
        return f"<html><body><p>Erreur inattendue: {e}</p></body></html>"


def search_apec_offers(search_term: str, num_offers: int = 200) -> list[dict]:
    """
    Interroge directement l'API de l'APEC pour récupérer les offres.
    Ensuite, récupère le HTML des pages de détail (pour débogage, ne pas extraire les compétences ici directement).
    """
    payload = {
        "motsCles": search_term,
        "pagination": { "range": num_offers, "startIndex": 0 },
        "sorts": [{ "type": "SCORE", "direction": "DESCENDING" }]
    }

    all_offers_metadata = []
    try:
        logging.info(f"APEC : Appel de l'API via requests POST sur {API_URL} pour '{search_term}'.")
        response = requests.post(API_URL, headers=HEADERS, json=payload, timeout=15)
        response.raise_for_status()
        data = response.json()

        for offer in data.get("resultats", []):
            offer_id = offer.get("id")
            if not offer_id: continue

            detail_url = f"{BASE_URL}/candidat/recherche-emploi.html/emploi/detail-offre/{offer_id}"
            
            description_from_api = offer.get("texteOffre", "")
            
            # MODIFICATION TEMPORAIRE : Nous ne faisons plus d'extraction de tags ici,
            # mais nous récupérons le HTML brut.
            # Cela signifie que les 'tags' resteront vides dans cette phase pour les offres APEC
            # jusqu'à ce que nous désactivions ce mode de débogage.
            raw_html_content = _get_apec_offer_details_from_html(detail_url)
            
            all_offers_metadata.append({
                "titre": offer.get("intitule"),
                "entreprise": offer.get("nomCommercial"),
                "url": detail_url,
                "description": description_from_api,
                "tags": [], # Les tags resteront vides dans ce mode de débogage
                "raw_html": raw_html_content # Ajout du HTML brut pour débogage
            })
        logging.info(f"APEC : {len(all_offers_metadata)} offres traitées (HTML brut récupéré).")
        return all_offers_metadata

    except requests.exceptions.RequestException as e:
        logging.error(f"APEC : Erreur lors de l'appel API initial ou du traitement des offres. {e}", exc_info=True)
        return []

# La fonction test_single_url_apec_extraction utilisera la version temporaire de _get_apec_offer_details_from_html
def test_single_url_apec_extraction(url: str) -> str: # Changement du type de retour à 'str'
    """
    Fonction de test pour récupérer le HTML brut d'une URL APEC spécifique.
    """
    logging.info(f"Test APEC Extraction: Tentative de récupération HTML brut pour l'URL: {url}")
    raw_html = _get_apec_offer_details_from_html(url)
    logging.info(f"Test APEC Extraction: HTML brut récupéré (taille : {len(raw_html)}).")
    return raw_html