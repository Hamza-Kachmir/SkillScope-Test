import pandas as pd
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable
import streamlit as st

from src.scraper import WTTJScraper, get_job_details
from src.france_travail_api import FranceTravailClient

# Étape 1a: Recherche WTTJ
def _search_wttj(search_term: str) -> tuple[list[dict], list[dict] | None]:
    """Scrape les offres de Welcome to the Jungle."""
    scraper = None
    try:
        logging.info(f"Phase 1a : Lancement de la recherche d'offres WTTJ pour '{search_term}'.")
        scraper = WTTJScraper(headless=True)
        offers_metadata = scraper.search_and_scrape_jobs(search_term, num_pages=2)
        cookies = scraper.cookies
        return offers_metadata, cookies
    except Exception as e:
        logging.error(f"Erreur majeure durant la recherche d'offres WTTJ : {e}", exc_info=True)
        return [], None
    finally:
        if scraper:
            scraper.close_driver()

# Étape 1b: Recherche France Travail
def _search_ft(search_term: str, logger: logging.Logger) -> list[dict]:
    """Interroge l'API de France Travail."""
    try:
        client = FranceTravailClient(client_id=st.secrets["FT_CLIENT_ID"], client_secret=st.secrets["FT_CLIENT_SECRET"], logger=logger)
        return client.search_offers(search_term, max_offers=150)
    except Exception as e:
        logger.error(f"Échec de l'appel à l'API France Travail : {e}")
        return []

# --- Fonction pour la 1ère Étape de l'UI (Spinner) ---
def search_all_sources(search_term: str, logger: logging.Logger) -> tuple[list[dict], list[dict] | None]:
    """
    Combine les résultats de WTTJ et France Travail et les déduplique.
    """
    wttj_offers, cookies = _search_wttj(search_term)
    ft_offers = _search_ft(search_term, logger)

    if not ft_offers and not wttj_offers:
        return [], None

    # Déduplication simple
    wttj_offer_keys = {(o['entreprise'].lower().strip(), o['titre'].lower().strip()) for o in wttj_offers}
    unique_ft_offers = [offer for offer in ft_offers if (offer['entreprise'].lower().strip(), offer['titre'].lower().strip()) not in wttj_offer_keys]
    
    if len(ft_offers) > len(unique_ft_offers):
        logging.info(f"Déduplication : {len(ft_offers) - len(unique_ft_offers)} offres FT ignorées (déjà présentes dans WTTJ).")

    return wttj_offers + unique_ft_offers, cookies

# --- Fonction pour la 2ème Étape de l'UI (Barre de progression) ---
def process_offers(all_offers: list[dict], cookies: list[dict], progress_callback: Callable[[float], None]) -> pd.DataFrame | None:
    """
    Analyse en détail les offres WTTJ et combine les résultats.
    """
    if not all_offers:
        return None
    
    progress_callback(0.1)
    
    # Extraire les détails uniquement pour les offres WTTJ
    wttj_offers_meta = [o for o in all_offers if 'url' in o and 'welcometothejungle' in o['url']]
    
    with ThreadPoolExecutor(max_workers=5) as executor:
        future_to_offer = {executor.submit(get_job_details, offer['url'], cookies): offer for offer in wttj_offers_meta}
        for i, future in enumerate(as_completed(future_to_offer)):
            try:
                result_details = future.result()
                # Met à jour l'offre originale dans la liste `all_offers`
                original_offer = future_to_offer[future]
                if result_details:
                    original_offer.update(result_details)
            except Exception as exc:
                logging.error(f"L'offre {future_to_offer[future].get('url')} a généré une erreur: {exc}")
            finally:
                # La progression est basée sur l'analyse des offres WTTJ (la partie la plus longue)
                progress_callback(0.1 + (i + 1) / len(wttj_offers_meta) * 0.8) if wttj_offers_meta else progress_callback(0.9)

    df = pd.DataFrame(all_offers)

    # Déduplication finale
    count_before_dedup = len(df)
    final_df = df.drop_duplicates(subset=['entreprise', 'titre'])
    duplicate_count = count_before_dedup - len(final_df)
    if duplicate_count > 0:
        logging.info(f"Déduplication finale : {duplicate_count} offre(s) en double supprimée(s).")
    
    logging.info("Création du DataFrame final...")
    final_cols = ['titre', 'entreprise', 'url', 'tags']
    for col in final_cols:
        if col not in final_df.columns:
            final_df[col] = None
            
    progress_callback(1.0)
    return final_df[final_cols]