import pandas as pd
import logging
from typing import Callable
import os  # On importe 'os' pour accéder aux variables d'environnement

# On importe les composants nécessaires
from src.france_travail_api import FranceTravailClient
from src.skill_extractor import extract_skills_from_text, initialize_extractor

def search_france_travail_offers(search_term: str, logger: logging.Logger) -> list[dict]:
    """
    Interroge l'API France Travail pour trouver des offres.
    Utilise les variables d'environnement pour s'authentifier.
    """
    try:
        logger.info(f"Phase 1 : Lancement de la recherche d'offres France Travail pour '{search_term}'.")
        
        # On récupère les identifiants depuis les variables d'environnement
        client_id = os.getenv("FT_CLIENT_ID")
        client_secret = os.getenv("FT_CLIENT_SECRET")

        if not client_id or not client_secret:
            logger.critical("Les variables d'environnement FT_CLIENT_ID et FT_CLIENT_SECRET ne sont pas définies !")
            raise ValueError("Configuration de l'API manquante sur le serveur.")

        client = FranceTravailClient(
            client_id=client_id,
            client_secret=client_secret,
            logger=logger
        )
        return client.search_offers(search_term, max_offers=150)
    except Exception as e:
        logger.error(f"Échec de l'appel à l'API France Travail : {e}")
        return []

def process_offers(all_offers: list[dict], progress_callback: Callable[[float], None]) -> pd.DataFrame | None:
    """
    Traite une liste d'offres pour en extraire les compétences.
    """
    if not all_offers:
        return None
    
    # Initialise l'extracteur de compétences (la version avancée)
    initialize_extractor()
    
    logging.info(f"Début de l'extraction des compétences pour {len(all_offers)} offres...")

    offers_with_tags = []
    total_offers = len(all_offers)

    for i, offer in enumerate(all_offers):
        description = offer.get('description', '')
        # Appelle la fonction d'extraction
        tags = sorted(list(extract_skills_from_text(description)))
        
        # On ne garde que les offres où des compétences ont été trouvées
        if tags:
            offer['tags'] = tags
            offers_with_tags.append(offer)
        
        # Met à jour la barre de progression
        progress_callback((i + 1) / total_offers)
        
    logging.info(f"Extraction terminée. {len(offers_with_tags)} offres ont des compétences identifiées.")
    
    if not offers_with_tags:
        return pd.DataFrame()

    df = pd.DataFrame(offers_with_tags)
    
    # S'assure que les colonnes finales existent bien
    final_cols = ['titre', 'entreprise', 'url', 'tags']
    for col in final_cols:
        if col not in df.columns:
            df[col] = [[] for _ in range(len(df))] if col == 'tags' else None
            
    return df[final_cols]