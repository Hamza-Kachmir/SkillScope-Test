import pandas as pd
import logging
from typing import Callable
import streamlit as st

from src.france_travail_api import FranceTravailAPI
from src.skill_extractor import extract_skills, load_skills_from_json
from src.normalization import get_canonical_form

def search_france_travail_offers(rome_code: str, search_range: int = 30) -> pd.DataFrame:
    """
    Recherche des offres d'emploi sur l'API de France Travail pour un code ROME donné.
    """
    api = FranceTravailAPI()
    if not api.is_token_valid():
        api.authenticate()
    
    try:
        offers_data = api.search(rome_code=rome_code, range=search_range)
        if offers_data and 'resultats' in offers_data:
            return pd.DataFrame(offers_data['resultats'])
        else:
            logging.warning("Aucune offre trouvée ou erreur dans les données reçues de l'API.")
            return pd.DataFrame()
    except Exception as e:
        logging.error(f"Erreur lors de la recherche d'offres : {e}")
        return pd.DataFrame()

def process_offers(offers_df: pd.DataFrame, log_callback: Callable[[str], None]) -> pd.DataFrame:
    """
    Traite les offres d'emploi pour en extraire et normaliser les compétences.
    """
    if offers_df.empty:
        log_callback("Aucune offre à traiter.")
        return pd.DataFrame(columns=['Intitulé', 'Compétences', 'Hardskills', 'Softskills', 'Langues', 'Source', 'URL'])

    log_callback(f"Début du traitement de {len(offers_df)} offres.")

    # Charger les compétences depuis les fichiers JSON (si ce n'est pas déjà fait)
    load_skills_from_json()

    processed_data = []
    for index, offer in offers_df.iterrows():
        description = offer.get('description', '')
        title = offer.get('intitule', 'N/A')
        url = offer.get('origineOffre', {}).get('urlOrigine', 'N/A')

        # Extraire les compétences
        extracted = extract_skills(description)
        
        # Consolider toutes les compétences dans une seule liste pour la normalisation
        all_skills = extracted["HardSkills"] + extracted["SoftSkills"] + extracted["Languages"]
        
        # Normaliser les compétences (exemple de fonction, à adapter si besoin)
        normalized_skills = [get_canonical_form(skill) for skill in all_skills]
        
        processed_data.append({
            'Intitulé': title,
            'Compétences': ', '.join(sorted(list(set(normalized_skills)))),
            'Hardskills': ', '.join(sorted(list(set(extracted["HardSkills"])))),
            'Softskills': ', '.join(sorted(list(set(extracted["SoftSkills"])))),
            'Langues': ', '.join(sorted(list(set(extracted["Languages"])))),
            'Source': 'France Travail',
            'URL': url
        })

    log_callback(f"Fin du traitement de {len(offers_df)} offres.")
    
    return pd.DataFrame(processed_data)