import pandas as pd
import logging
from typing import Callable

# Imports absolus qui fonctionnent grâce au changement dans dashboard.py
from src.france_travail_api import FranceTravailAPI 
from src.skill_extractor import extract_skills
from src.normalization import get_canonical_form # Je garde la normalisation si tu veux la réutiliser

def search_france_travail_offers(rome_code: str, log_handler) -> list[dict]:
    """
    Recherche des offres d'emploi sur l'API de France Travail.
    """
    log_handler.info(f"Recherche d'offres pour le code ROME : '{rome_code}'")
    api = FranceTravailAPI()
    if not api.is_token_valid():
        api.authenticate()
    
    try:
        offers_data = api.search(rome_code=rome_code, range="0,149") # Recherche jusqu'à 150 offres
        if offers_data and 'resultats' in offers_data:
            log_handler.info(f"{len(offers_data['resultats'])} offres trouvées.")
            return offers_data['resultats']
        else:
            log_handler.warning("Aucune offre trouvée ou données invalides reçues de l'API.")
            return []
    except Exception as e:
        log_handler.error(f"Erreur critique lors de l'appel à l'API France Travail : {e}")
        return []

def process_offers(offers_df: list[dict], progress_callback: Callable[[float], None]) -> pd.DataFrame | None:
    """
    Traite une liste d'offres pour en extraire et classer les compétences.
    """
    if not offers_df:
        logging.warning("Aucune offre à traiter.")
        return None

    logging.info(f"Début du traitement et de l'extraction pour {len(offers_df)} offres.")
    
    processed_data = []
    total = len(offers_df)

    for i, offer in enumerate(offers_df):
        description = offer.get('description', '')
        
        # Le nouvel extracteur retourne un dictionnaire avec les compétences déjà classées
        extracted = extract_skills(description)

        # Si tu souhaites appliquer une normalisation (ex: mettre "Js" et "Javascript" sous la même forme)
        # Tu peux le faire ici. Pour l'instant, on utilise les compétences telles quelles.
        # hardskills_normalized = [get_canonical_form(s) for s in extracted['HardSkills']]
        
        processed_data.append({
            'Intitulé': offer.get('intitule', 'N/A'),
            'Entreprise': offer.get('entreprise', {}).get('nom', 'N/A'),
            'Hardskills': ', '.join(extracted["HardSkills"]),
            'Softskills': ', '.join(extracted["SoftSkills"]),
            'Langues': ', '.join(extracted["Languages"]),
            'URL': offer.get('origineOffre', {}).get('urlOrigine', '#')
        })
        
        # Met à jour la barre de progression dans le dashboard
        progress_callback((i + 1) / total)

    logging.info("Traitement et extraction des compétences terminés.")
    
    return pd.DataFrame(processed_data)