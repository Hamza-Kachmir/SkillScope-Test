import pandas as pd
import logging
from typing import Callable
import streamlit as st

from src.france_travail_api import FranceTravailClient
from src.skill_extractor import extract_skills_from_text

def search_france_travail_offers(search_term: str, logger: logging.Logger) -> list[dict]:
    try:
        logger.info(f"Phase 1 : Lancement de la recherche d'offres France Travail pour '{search_term}'.")
        client = FranceTravailClient(
            client_id=st.secrets["FT_CLIENT_ID"], 
            client_secret=st.secrets["FT_CLIENT_SECRET"], 
            logger=logger
        )
        return client.search_offers(search_term, max_offers=250)
    except Exception as e:
        logger.error(f"Échec de l'appel à l'API France Travail : {e}")
        return []

def process_offers(all_offers: list[dict], progress_callback: Callable[[float], None]) -> pd.DataFrame | None:
    if not all_offers:
        return None
    
    total_offers = len(all_offers)
    processed_offers = []

    logging.info(f"Début de l'extraction des compétences pour {total_offers} offres.")

    for i, offer in enumerate(all_offers):
        description = offer.get('description', '')
        
        found_skills = extract_skills_from_text(description)
        
        offer['tags'] = sorted(list(found_skills))
        processed_offers.append(offer)
        
        progress_callback((i + 1) / total_offers)

    logging.info("Extraction des compétences terminée.")
    
    df = pd.DataFrame(processed_offers)
    
    final_cols = ['titre', 'entreprise', 'url', 'tags']
    for col in final_cols:
        if col not in df.columns:
            df[col] = [[] for _ in range(len(df))] if col == 'tags' else None
            
    return df[final_cols]