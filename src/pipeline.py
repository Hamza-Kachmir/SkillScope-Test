import pandas as pd
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable
import streamlit as st

# from src.wttj_scraper import WTTJScraper, get_job_details # Maintenu mais non appelé activement
from src.apec_scraper import search_apec_offers, get_apec_details
from src.france_travail_api import FranceTravailClient
from src.normalization import build_normalization_map, extract_skill_candidates_from_text, process_extracted_skills # Ajout de process_extracted_skills
import json # Ajout pour charger/sauvegarder le dictionnaire

# Chargement du dictionnaire de normalisation des compétences
# Ce dictionnaire sera utilisé pour enrichir les compétences extraites des descriptions
SKILL_NORMALIZATION_MAP = {}
try:
    with open("skills_normalization_map.json", "r", encoding="utf-8") as f:
        SKILL_NORMALIZATION_MAP = json.load(f)
    logging.info(f"Dictionnaire de compétences chargé avec {len(SKILL_NORMALIZATION_MAP)} entrées.")
except FileNotFoundError:
    logging.warning("Fichier skills_normalization_map.json non trouvé. Le dictionnaire ne sera pas utilisé pour la normalisation.")
except json.JSONDecodeError:
    logging.error("Erreur de lecture du fichier skills_normalization_map.json. Vérifiez son format.")

# Le reste du fichier pipeline.py (fonctions _run_wttj_scraper, search_all_offers, analyze_all_offers, enrich_offers_from_description)
# sera fusionné ci-dessous avec les modifications.

# La fonction _run_wttj_scraper reste pour compatibilité, mais ne sera pas appelée
def _run_wttj_scraper(search_term: str):
    logging.info("WTTJ: Le scraper n'est pas utilisé activement dans ce pipeline.")
    return [], None # Retourne vide pour ne pas influencer la suite

# Nouvelle fonction de recherche combinée
def search_all_sources_combined(search_term: str) -> list[dict]:
    all_raw_offers = []
    
    with ThreadPoolExecutor(max_workers=2) as executor:
        logging.info("Lancement des collectes APEC et France Travail en parallèle.")
        
        # Lancement de la recherche APEC (on vise 10 pages, soit 200 offres si 20 par page)
        future_apec = executor.submit(search_apec_offers, search_term, max_offers_to_fetch=200)
        
        # Lancement de la recherche France Travail
        ft_client = FranceTravailClient()
        future_ft = executor.submit(ft_client.search_offers, search_term, max_offers_to_fetch=150) # Comme avant

        try:
            offers_apec = future_apec.result()
            logging.info(f"APEC : Collecte terminée. {len(offers_apec)} offres trouvées.")
            all_raw_offers.extend(offers_apec)
        except Exception as e:
            logging.error(f"La collecte APEC a échoué: {e}", exc_info=True)

        try:
            offers_ft = future_ft.result()
            logging.info(f"France Travail : Collecte terminée. {len(offers_ft)} offres trouvées.")
            # Les offres FT ont déjà des 'tags' et une 'description'
            # Nous n'avons pas besoin de récupérer les détails séparément ici pour FT car l'API les donne
            all_raw_offers.extend(offers_ft)
        except Exception as e:
            logging.error(f"La collecte France Travail a échoué: {e}", exc_info=True)
    
    if not all_raw_offers:
        return []

    logging.info(f"Début de la déduplication sur {len(all_raw_offers)} offres brutes combinées.")
    unique_offers_data = {} # Utilise un dict pour une déduplication efficace et pour conserver la meilleure version si nécessaire
    for offer in all_raw_offers:
        company = offer.get('entreprise', '').lower().strip()
        title = offer.get('titre', '').lower().strip()
        url = offer.get('url', '').lower().strip() # Inclure l'URL pour une meilleure déduplication si titres/entreprises similaires
        
        # Créer une signature unique pour l'offre
        signature = f"{company}-{title}-{url}"
        
        if signature not in unique_offers_data:
            unique_offers_data[signature] = offer
        else:
            # Si déjà vu, on peut fusionner les tags ou prendre la plus complète si nécessaire
            # Pour l'instant, on garde la première rencontre, ce qui est suffisant pour dédupliquer.
            pass
            
    final_unique_offers = list(unique_offers_data.values())
    logging.info(f"Fin de la déduplication. {len(final_unique_offers)} offres uniques conservées.")
    
    return final_unique_offers

# Fonction pour analyser et enrichir les offres avec le dictionnaire de compétences
def process_and_enrich_offers(all_offers: list[dict], progress_callback: Callable[[float], None]) -> pd.DataFrame | None:
    if not all_offers:
        return None
    
    detailed_and_enriched_offers = []
    
    # Étape 1: Récupérer les détails des offres APEC (description et tags APEC)
    # Les offres FT ont déjà leur description et tags via l'API, elles ne passent pas par get_apec_details
    offers_to_detail_apec = [o for o in all_offers if "apec.fr" in o.get('url', '') and not o.get('description')]
    
    with ThreadPoolExecutor(max_workers=5) as executor:
        future_to_offer = {executor.submit(get_apec_details, offer['url']): offer for offer in offers_to_detail_apec}
        
        for i, future in enumerate(as_completed(future_to_offer)):
            original_offer = future_to_offer[future]
            try:
                apec_details = future.result()
                if apec_details:
                    original_offer.update(apec_details) # Ajoute description et tags de APEC
            except Exception as exc:
                logging.error(f"APEC: Erreur de détail pour {original_offer.get('url')}: {exc}", exc_info=True)
            finally:
                # Progression basée sur l'analyse APEC
                progress_callback((i + 1) / len(offers_to_detail_apec) * 0.5) if offers_to_detail_apec else progress_callback(0.5)

    # Étape 2: Extraction et normalisation des compétences pour toutes les offres
    total_offers_to_process = len(all_offers)
    for i, offer in enumerate(all_offers):
        current_skills = set(offer.get('tags', [])) # Compétences déjà fournies (APEC ou FT API)
        
        # Extraction de la description (APEC ou FT)
        description = offer.get('description', '')
        if description and SKILL_NORMALIZATION_MAP: # Seulement si on a un dictionnaire chargé
            # Utilise la fonction pour extraire des candidats et les normaliser
            extracted_from_desc = extract_skill_candidates_from_text(description) # Ceci retourne des candidats bruts
            
            # Normaliser ces candidats en utilisant le dictionnaire
            normalized_extracted_skills = process_extracted_skills(extracted_from_desc)
            current_skills.update(normalized_extracted_skills)
        
        offer['tags'] = sorted(list(current_skills)) # Mettre à jour les tags avec les compétences enrichies
        detailed_and_enriched_offers.append(offer)
        
        progress_callback(0.5 + (i + 1) / total_offers_to_process * 0.5) # Progression de 50% à 100%

    df_final = pd.DataFrame(detailed_and_enriched_offers)
    
    # Supprimer la colonne description si elle n'est plus nécessaire dans le DataFrame final
    if 'description' in df_final.columns:
        df_final = df_final.drop(columns=['description'])
        
    logging.info(f"Analyse et enrichissement terminés. {len(df_final)} offres prêtes.")
    return df_final