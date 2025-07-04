import requests
import logging
from bs4 import BeautifulSoup
import time
import random
from typing import List, Dict
import re # Important : Assurez-vous que 're' est toujours importé

from src.config import HEADERS

API_URL = "https://www.apec.fr/cms/webservices/rechercheOffre"
BASE_URL = "https://www.apec.fr"

def _get_apec_offer_details_from_html(offer_url: str) -> List[str]: # Type de retour remis à List[str]
    """
    Scrape une page d'offre APEC pour extraire les compétences détaillées
    des sections "Langues", "Savoir-être", "Savoir-faire".
    """
    skills_found = set()
    try:
        time.sleep(random.uniform(0.5, 1.5))
        logging.info(f"APEC HTML Scraper : Tentative de récupération des détails pour {offer_url}")
        response = requests.get(offer_url, headers=HEADERS, timeout=10)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, 'html.parser')

        if "L'offre que vous souhaitez afficher n'est plus disponible" in soup.get_text():
            logging.warning(f"APEC HTML Scraper : L'offre {offer_url} n'est plus disponible.")
            return []

        # SÉLECTEUR MIS À JOUR : Cibler directement les <p> à l'intérieur de <apec-competence-detail>
        # Cette balise personnalisée semble être un conteneur fiable pour les noms de compétences.
        skill_elements = soup.select('apec-competence-detail p')
        
        for element in skill_elements:
            skill_text = element.get_text(strip=True)
            # Ajout d'une condition pour s'assurer que la compétence n'est pas vide ou juste un chiffre
            if skill_text and len(skill_text) > 1 and not skill_text.replace('.', '', 1).isdigit(): 
                skills_found.add(skill_text)
        
        logging.info(f"APEC HTML Scraper : {len(skills_found)} compétences extraites de {offer_url}.")

    except requests.exceptions.RequestException as e:
        logging.error(f"APEC HTML Scraper : Erreur lors du scraping de {offer_url}: {e}")
    except Exception as e:
        logging.error(f"APEC HTML Scraper : Erreur inattendue lors de l'extraction des compétences de {offer_url}: {e}", exc_info=True)
    
    return sorted(list(skills_found))


def search_apec_offers(search_term: str, num_offers: int = 200) -> list[dict]:
    """
    Interroge directement l'API de l'APEC pour récupérer les offres.
    Ensuite, scrape les pages de détail pour récupérer les compétences structurées.
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
            
            # Appel de la fonction d'extraction des tags
            extracted_tags = _get_apec_offer_details_from_html(detail_url)

            all_offers_metadata.append({
                "titre": offer.get("intitule"),
                "entreprise": offer.get("nomCommercial"),
                "url": detail_url,
                "description": description_from_api,
                "tags": extracted_tags # Les tags seront maintenant peuplés si l'extraction HTML est réussie
            })
        logging.info(f"APEC : {len(all_offers_metadata)} offres traitées avec compétences structurées extraites.")
        return all_offers_metadata

    except requests.exceptions.RequestException as e:
        logging.error(f"APEC : Erreur lors de l'appel API initial ou du traitement des offres. {e}", exc_info=True)
        return []

def test_single_url_apec_extraction(url: str) -> List[str]: # Type de retour remis à List[str]
    """
    Fonction de test pour extraire les compétences d'une URL APEC spécifique.
    Utilise la même logique que _get_apec_offer_details_from_html.
    Cette fonction est destinée au débogage direct.
    """
    logging.info(f"Test APEC Extraction: Tentative d'extraction pour l'URL: {url}")
    extracted_skills = _get_apec_offer_details_from_html(url)
    logging.info(f"Test APEC Extraction: Compétences extraites: {extracted_skills}")
    return extracted_skills