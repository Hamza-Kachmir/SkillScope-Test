import pandas as pd
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable
import streamlit as st

from src.scraper import APECScraper, get_apec_job_details # Import du nouveau scraper APEC et de sa fonction de détail
from src.france_travail_api import FranceTravailClient
from src.normalization import get_canonical_form

def search_all_sources(search_term: str) -> tuple[list[dict] | None, list[dict] | None]: # Retourne offers et cookies de Selenium
    offers_apec = []
    apec_cookies = None # Initialise à None

    # On utilise un contexte pour le scraper Selenium afin de garantir sa fermeture
    scraper = None
    try:
        logging.info("--- Phase 1: Lancement des collectes en parallèle ---")
        logging.info("APEC : Démarrage du scraper Selenium.")
        scraper = APECScraper(headless=True) # Exécuter en mode headless
        offers_apec = scraper.search_and_scrape_job_urls(search_term, num_pages=2) # Scraping de 2 pages APEC
        apec_cookies = scraper.cookies # Récupérer les cookies de Selenium
        logging.info(f"APEC : Recherche terminée. {len(offers_apec)} offres trouvées via Selenium.")
        # --- Ajout pour débogage : Afficher les 3 premières URLs APEC ---
        for i, offer in enumerate(offers_apec[:3]):
            logging.info(f"APEC Offer {i+1} URL (from Selenium): {offer.get('url', 'N/A')}")
        # -------------------------------------------------------------------------------------
    except Exception as e:
        logging.error(f"Le scraper APEC (Selenium) a échoué: {e}", exc_info=True)
    finally:
        if scraper:
            scraper.close_driver() # Toujours fermer le driver

    raw_offers = offers_apec or []
    if not raw_offers: return None, None # Si aucune offre APEC, on ne renvoie rien

    logging.info(f"Début de la déduplication sur {len(raw_offers)} offres brutes (issues de APEC Selenium).")
    unique_offers = []
    seen_signatures = set()
    for offer in raw_offers:
        company = offer.get('entreprise', '').lower().strip()
        title = offer.get('titre', '').lower().strip()
        signature = f"{company}-{title}"
        if signature not in seen_signatures:
            unique_offers.append(offer)
            seen_signatures.add(signature)
    offers_metadata = unique_offers
    logging.info(f"Fin de la déduplication. {len(offers_metadata)} offres uniques conservées.")

    return offers_metadata, apec_cookies # Retourne les offres et les cookies APEC


def process_offers(
    offers_metadata: list[dict],
    apec_cookies: list[dict] | None, # Les cookies APEC passés ici
    progress_callback: Callable[[float], None]
) -> pd.DataFrame | None:
    logging.info("--- Phase 2: ANALYSE DÉTAILLÉE ET ENRICHISSEMENT ---")
    
    detailed_apec_offers = []
    if offers_metadata and apec_cookies: # Assurez-vous d'avoir des cookies pour les requêtes requests.get
        logging.info(f"APEC : Récupération des détails pour {len(offers_metadata)} offres APEC avec Requests.")
        with ThreadPoolExecutor(max_workers=5) as executor: # Utilisation de threads pour les appels Requests
            future_to_offer = {executor.submit(get_apec_job_details, offer['url'], apec_cookies): offer for offer in offers_metadata}
            for i, future in enumerate(as_completed(future_to_offer)):
                original_offer = future_to_offer[future]
                try:
                    result_details = future.result() # result_details contient description et tags extraits
                    if result_details:
                        original_offer.update(result_details) # Met à jour l'offre avec description et tags
                        detailed_apec_offers.append(original_offer)
                except Exception as exc:
                    logging.error(f"APEC : L'offre {original_offer.get('url')} a généré une erreur lors de l'extraction des détails: {exc}", exc_info=True)
                progress_callback((i + 1) / (len(offers_metadata) + 150) * 0.5) # Ajuster la progression

    # Combiner les offres APEC détaillées (potentiellement vides si le scraping échoue)
    all_detailed_offers_combined = detailed_apec_offers
    
    if not all_detailed_offers_combined: # Si aucune offre APEC valide n'a été récupérée
        logging.warning("Aucune offre APEC détaillée valide n'a pu être traitée.")
        # Le master_skill_set sera vide à moins que France Travail n'apporte des compétences
        master_skill_set = set()
    else:
        df_offers_apec_detailed = pd.DataFrame(all_detailed_offers_combined)
        # Le master_skill_set est initialisé avec les tags déjà extraits par le scraper APEC
        master_skill_set = set(df_offers_apec_detailed['tags'].explode().dropna()) 
    
    logging.info(f"Dictionnaire de compétences initialisé avec {len(master_skill_set)} compétences (issues d'APEC structurées si disponibles).")
    progress_callback(0.5) # Progression après traitement APEC

    logging.info("France Travail : Lancement de la recherche via l'API.")
    df_ft = None
    try:
        client = FranceTravailClient(client_id=st.secrets["FT_CLIENT_ID"], client_secret=st.secrets["FT_CLIENT_SECRET"], logger=logging.getLogger())
        search_term = st.session_state.get('job_title', '')
        ft_offers = client.search_offers(search_term, max_offers=150)
        if ft_offers:
            df_ft = pd.DataFrame(ft_offers)
            if 'tags' not in df_ft.columns:
                df_ft['tags'] = [[] for _ in range(len(df_ft))]
            logging.info(f"France Travail: {len(df_ft)} offres trouvées.")
            # Mettre à jour le master_skill_set avec les tags de France Travail
            master_skill_set.update(df_ft['tags'].explode().dropna()) 
            logging.info(f"Dictionnaire de compétences après France Travail: {len(master_skill_set)} compétences.")
    except Exception as e:
        logging.error(f"Échec de l'appel à l'API France Travail : {e}", exc_info=True)
    progress_callback(0.75)

    # Concaténation des offres APEC (détaillées) et France Travail
    if df_ft is not None:
        if not detailed_apec_offers: # Si aucune offre APEC n'a été récupérée, juste FT
            final_df = df_ft
        else:
            final_df = pd.concat([df_offers_apec_detailed, df_ft], ignore_index=True)
    elif detailed_apec_offers: # Si que APEC
        final_df = df_offers_apec_detailed
    else: # Si ni APEC ni FT
        return None

    logging.info(f"Début de la déduplication post-concaténation sur {len(final_df)} offres.")
    unique_final_offers = []
    seen_final_signatures = set()
    for idx, row in final_df.iterrows():
        company = row.get('entreprise', '').lower().strip()
        title = row.get('titre', '').lower().strip()
        signature = f"{company}-{title}"
        if signature not in seen_final_signatures:
            unique_final_offers.append(row.to_dict())
            seen_final_signatures.add(signature)
    final_df = pd.DataFrame(unique_final_offers)
    logging.info(f"Fin de la déduplication post-concaténation. {len(final_df)} offres uniques.")

    # Enrichir toutes les offres de final_df avec le master_skill_set construit
    final_df = enrich_offers_from_description(final_df, master_skill_set)

    if 'description' in final_df.columns:
        final_df = final_df.drop(columns=['description'])
        
    logging.info(f"--- ANALYSE TERMINÉE ---")
    progress_callback(1.0)
    return final_df

def enrich_offers_from_description(df: pd.DataFrame, skill_set: set) -> pd.DataFrame:
    """
    Enrichit les tags des offres en recherchant les compétences du skill_set dans leur description.
    """
    if df is None or df.empty or not skill_set: return df
    
    compiled_skill_patterns = {}
    for skill in skill_set:
        normalized_skill = get_canonical_form(skill) 
        pattern = r'\b' + re.escape(normalized_skill.lower()).replace(r'\ ', r'\s*') + r'\b'
        compiled_skill_patterns[skill] = re.compile(pattern)

    def find_skills(row):
        found_skills = set(row.get('tags', []))
        description = row.get('description')
        if not isinstance(description, str): return sorted(list(found_skills))
        description_lower = description.lower()
        
        for skill_name, pattern in compiled_skill_patterns.items():
            if pattern.search(description_lower):
                found_skills.add(skill_name)
        return sorted(list(found_skills))
    
    df['tags'] = df.apply(find_skills, axis=1)
    return df