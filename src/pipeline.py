import pandas as pd
import logging
from typing import Callable
import streamlit as st
from concurrent.futures import ThreadPoolExecutor

from src.france_travail_api import FranceTravailClient
from src.skill_extractor import extract_candidate_skills
from src.esco_api import is_skill_valid

def search_france_travail_offers(search_term: str, logger: logging.Logger) -> list[dict]:
    try:
        logger.info(f"Phase 1 : Lancement de la recherche d'offres France Travail pour '{search_term}'.")
        client = FranceTravailClient(
            client_id=st.secrets["FT_CLIENT_ID"], 
            client_secret=st.secrets["FT_CLIENT_SECRET"], 
            logger=logger
        )
        return client.search_offers(search_term, max_offers=150)
    except Exception as e:
        logger.error(f"Échec de l'appel à l'API France Travail : {e}")
        return []

def process_offers(all_offers: list[dict], progress_callback: Callable[[float], None]) -> pd.DataFrame | None:
    if not all_offers:
        return None
    
    full_text = " ".join([offer.get('description', '') for offer in all_offers])
    
    logging.info("Phase 2 : Extraction des compétences candidates avec Regex...")
    candidate_skills = extract_candidate_skills(full_text)
    logging.info(f"{len(candidate_skills)} compétences candidates uniques trouvées.")

    logging.info("Phase 3 : Validation des compétences candidates via l'API ESCO...")
    valid_skills = set()
    with ThreadPoolExecutor(max_workers=10) as executor:
        # On passe la liste des candidats au validateur
        results = executor.map(is_skill_valid, candidate_skills)
        # On récupère les compétences valides
        for skill, is_valid in zip(candidate_skills, results):
            if is_valid:
                valid_skills.add(skill.lower())

    logging.info(f"{len(valid_skills)} compétences validées par ESCO.")

    logging.info("Phase 4 : Association des compétences validées aux offres.")
    for offer in all_offers:
        description_lower = offer.get('description', '').lower()
        
        offer['tags'] = sorted([skill for skill in valid_skills if skill in description_lower])
        
    progress_callback(1.0)

    df = pd.DataFrame(all_offers)
    
    final_cols = ['titre', 'entreprise', 'url', 'tags']
    for col in final_cols:
        if col not in df.columns:
            df[col] = [[] for _ in range(len(df))] if col == 'tags' else None
            
    return df[final_cols]