import pandas as pd
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable
import streamlit as st

from src.apec_api import search_apec_offers
from src.france_travail_api import FranceTravailClient
from src.normalization import get_canonical_form # Importer pour normaliser les compétences

def search_all_sources(search_term: str) -> tuple[list[dict] | None, None]:
    offers_apec = []
    
    with ThreadPoolExecutor(max_workers=2) as executor:
        logging.info("--- Phase 1: Lancement des collectes en parallèle ---")
        future_apec = executor.submit(search_apec_offers, search_term)
        
        try:
            offers_apec = future_apec.result()
            logging.info(f"APEC : Recherche terminée. {len(offers_apec)} offres trouvées.")
            # --- Ajout pour débogage : Afficher les 3 premières URLs, début de description et TAGS APEC ---
            for i, offer in enumerate(offers_apec[:3]):
                logging.info(f"APEC Offer {i+1} URL: {offer.get('url', 'N/A')}")
                logging.info(f"APEC Offer {i+1} Description (partial): {offer.get('description', 'N/A')[:200]}...")
                logging.info(f"APEC Offer {i+1} Tags (structurés): {offer.get('tags', 'N/A')}") # Afficher les tags extraits
            # -------------------------------------------------------------------------------------
        except Exception as e:
            logging.error(f"Le scraper APEC a échoué: {e}", exc_info=True)
            
    raw_offers = offers_apec or []
    if not raw_offers: return None, None
    
    logging.info(f"Début de la déduplication sur {len(raw_offers)} offres brutes.")
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
    
    return offers_metadata, None

def process_offers(
    offers_metadata: list[dict],
    cookies: None, # Maintenu pour la compatibilité, mais non utilisé
    progress_callback: Callable[[float], None]
) -> pd.DataFrame | None:
    logging.info("--- Phase 2: ANALYSE DÉTAILLÉE ET ENRICHISSEMENT ---")
    
    all_detailed_offers = offers_metadata
    
    if not all_detailed_offers: return None
    
    df_offers = pd.DataFrame(all_detailed_offers)
    # S'assurer que la colonne 'tags' existe et est une liste, même si vide
    if 'tags' not in df_offers.columns:
        df_offers['tags'] = [[] for _ in range(len(df_offers))]
    
    # Initialisation du master_skill_set avec les tags déjà extraits (APEC structuré)
    master_skill_set = set(df_offers['tags'].explode().dropna()) 
    
    logging.info(f"Dictionnaire de compétences initialisé avec {len(master_skill_set)} compétences (issues d'APEC structurées).")
    progress_callback(0.2)

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
            # --- Ajout pour débogage : Afficher les 3 premières URLs, début de description et TAGS FT ---
            for i, offer in enumerate(ft_offers[:3]):
                logging.info(f"France Travail Offer {i+1} URL: {offer.get('url', 'N/A')}")
                logging.info(f"France Travail Offer {i+1} Description (partial): {offer.get('description', 'N/A')[:200]}...")
                logging.info(f"France Travail Offer {i+1} Tags (structurés): {offer.get('tags', 'N/A')}") # Afficher les tags extraits
            # ------------------------------------------------------------------------------------
            
            # Mise à jour du master_skill_set avec les tags de France Travail
            master_skill_set.update(df_ft['tags'].explode().dropna()) 
            logging.info(f"Dictionnaire de compétences après France Travail: {len(master_skill_set)} compétences.")
    except Exception as e:
        logging.error(f"Échec de l'appel à l'API France Travail : {e}")
    progress_callback(0.5)

    # Maintenant que master_skill_set est potentiellement rempli (par APEC structuré et FT), on peut enrichir
    # les offres APEC (df_offers) et France Travail (df_ft) en cherchant ces compétences dans les descriptions.
    df_offers = enrich_offers_from_description(df_offers, master_skill_set)
    if df_ft is not None:
        df_ft = enrich_offers_from_description(df_ft, master_skill_set)
        
        final_df = pd.concat([df_offers, df_ft], ignore_index=True)
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
    else:
        final_df = df_offers

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
        # Créer une regex plus flexible pour les compétences multi-mots
        # Utilisation de get_canonical_form pour normaliser les compétences et améliorer la correspondance
        normalized_skill = get_canonical_form(skill) # Normalise la compétence pour le pattern
        # Le pattern doit chercher la forme normalisée ou une variante proche dans le texte
        # Pour l'instant, on cherche la compétence telle quelle, en ignorant la casse et les espaces multiples.
        # Si get_canonical_form modifie "Python" en "python", la regex cherchera "python".
        pattern = r'\b' + re.escape(normalized_skill.lower()).replace(r'\ ', r'\s*') + r'\b'
        compiled_skill_patterns[skill] = re.compile(pattern)

    def find_skills(row):
        found_skills = set(row.get('tags', [])) # Conserve les tags déjà trouvés (structurés)
        description = row.get('description')
        if not isinstance(description, str): return sorted(list(found_skills))
        description_lower = description.lower()
        
        for skill_name, pattern in compiled_skill_patterns.items():
            if pattern.search(description_lower):
                found_skills.add(skill_name) # Ajoute la compétence si trouvée dans la description
        return sorted(list(found_skills))
    
    df['tags'] = df.apply(find_skills, axis=1)
    return df