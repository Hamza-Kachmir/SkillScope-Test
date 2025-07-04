import pandas as pd
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable
import streamlit as st

# Suppression de WTTJScraper et get_job_details
from src.apec_api import search_apec_offers # Import mis à jour vers apec_api
from src.france_travail_api import FranceTravailClient

# La fonction _run_wttj_scraper est supprimée car WTTJ est retiré

def search_all_sources(search_term: str) -> tuple[list[dict] | None, None]: # Plus de cookies WTTJ
    offers_apec = []
    
    with ThreadPoolExecutor(max_workers=2) as executor:
        logging.info("--- Phase 1: Lancement des collectes en parallèle ---")
        future_apec = executor.submit(search_apec_offers, search_term) # Appel direct à apec_api
        
        try:
            offers_apec = future_apec.result()
            logging.info(f"APEC : Recherche terminée. {len(offers_apec)} offres trouvées.")
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
    
    return offers_metadata, None # Retourne None pour les cookies car WTTJ est supprimé

def process_offers(
    offers_metadata: list[dict],
    cookies: None, # Les cookies ne sont plus nécessaires
    progress_callback: Callable[[float], None]
) -> pd.DataFrame | None:
    logging.info("--- Phase 2: ANALYSE DÉTAILLÉE ET ENRICHISSEMENT ---")
    
    # Toutes les offres proviennent maintenant de l'APEC, et leur description est déjà présente.
    # Il n'y a plus besoin de logique spécifique pour WTTJ ou de ThreadPoolExecutor pour les détails.
    all_detailed_offers = offers_metadata # Les offres APEC ont déjà description et tags initialisés
    
    if not all_detailed_offers: return None
    
    df_offers = pd.DataFrame(all_detailed_offers)
    # Assurez-vous que la colonne 'tags' existe et est une liste, même si vide au départ.
    if 'tags' not in df_offers.columns:
        df_offers['tags'] = [[] for _ in range(len(df_offers))]
    
    # Construction du master_skill_set à partir des tags existants (APEC)
    # et potentiellement des descriptions. Pour l'APEC, les tags sont vides initialement,
    # donc le master_skill_set sera vide à moins d'être créé à partir d'autres sources
    # ou d'une liste de compétences pré-définie.
    # Pour l'instant, on se base sur les tags enrichis par la description plus tard.
    master_skill_set = set() # Initialiser vide car APEC n'a pas de tags pré-existants

    logging.info(f"Dictionnaire de compétences créé : {len(master_skill_set)} compétences (sera enrichi plus tard).")
    progress_callback(0.2) # Ajustement de la progression car moins d'étapes de scraping de détails

    # Le reste de la fonction (France Travail, enrichissement) reste similaire
    logging.info("France Travail : Lancement de la recherche via l'API.")
    df_ft = None
    try:
        client = FranceTravailClient(client_id=st.secrets["FT_CLIENT_ID"], client_secret=st.secrets["FT_CLIENT_SECRET"], logger=logging.getLogger()) # Ajout du logger
        search_term = st.session_state.get('job_title', '')
        ft_offers = client.search_offers(search_term, max_offers=150)
        if ft_offers:
            df_ft = pd.DataFrame(ft_offers)
            # S'assurer que les tags des offres FT sont bien des listes
            if 'tags' not in df_ft.columns:
                df_ft['tags'] = [[] for _ in range(len(df_ft))]
            logging.info(f"France Travail: {len(df_ft)} offres trouvées.")
            
            # Mettre à jour le master_skill_set avec les tags de France Travail
            master_skill_set.update(df_ft['tags'].explode().dropna())

    except Exception as e:
        logging.error(f"Échec de l'appel à l'API France Travail : {e}")
    progress_callback(0.5) # Ajustement de la progression

    # Avant d'enrichir les offres APEC, il faut que le master_skill_set contienne des compétences.
    # Pour l'instant, il ne contient que celles de FT si FT a retourné des offres.
    # Si France Travail n'a rien trouvé, master_skill_set sera vide, et enrich_offers_from_description ne trouvera rien.
    
    df_offers = enrich_offers_from_description(df_offers, master_skill_set) # Enrichissement des offres APEC
    if df_ft is not None:
        # Assurez-vous que df_ft est aussi enrichi avec le master_skill_set combiné
        df_ft = enrich_offers_from_description(df_ft, master_skill_set)
        
        # Concaténation et nouvelle déduplication post-enrichissement pour s'assurer de l'unicité
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
    
    # Créer un dictionnaire de regex pré-compilées pour une meilleure performance
    # et manipuler les noms de compétences pour une meilleure correspondance.
    compiled_skill_patterns = {}
    for skill in skill_set:
        # Créer une regex plus flexible pour les compétences multi-mots
        # Ex: "Data Science" -> r'\bdata\s*science\b'
        # Ou pour des mots simples : "Python" -> r'\bpython\b'
        pattern = r'\b' + re.escape(skill.lower()).replace(r'\ ', r'\s*') + r'\b'
        compiled_skill_patterns[skill] = re.compile(pattern)

    def find_skills(row):
        found_skills = set(row.get('tags', [])) # Commence avec les tags déjà présents
        description = row.get('description')
        if not isinstance(description, str): return sorted(list(found_skills))
        description_lower = description.lower()
        
        for skill_name, pattern in compiled_skill_patterns.items():
            if pattern.search(description_lower):
                found_skills.add(skill_name)
        return sorted(list(found_skills))
    
    df['tags'] = df.apply(find_skills, axis=1)
    return df