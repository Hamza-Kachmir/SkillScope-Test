import logging
import asyncio
from typing import Dict, Any, List, Optional
from collections import defaultdict

from src.france_travail_api import FranceTravailClient
from src.cache_manager import get_cached_results, add_to_cache, delete_from_cache
from src.gemini_extractor import extract_skills_with_gemini, initialize_gemini

# --- Constantes du Pipeline ---
GEMINI_BATCH_SIZE = 25  # Nombre de descriptions à envoyer à Gemini par appel
TOP_SKILLS_LIMIT = 30   # Nombre maximum de compétences à retourner

def _chunk_list(data: List[Any], chunk_size: int) -> List[List[Any]]:
    """Divise une liste en sous-listes (chunks) de taille fixe."""
    return [data[i:i + chunk_size] for i in range(0, len(data), chunk_size)]

def _aggregate_results(batch_results: List[Optional[Dict]]) -> Dict[str, Any]:
    """Agrège et compte les compétences et niveaux d'études des différents lots Gemini."""
    skill_frequencies = defaultdict(int)
    education_frequencies = defaultdict(int)

    for result_batch in filter(None, batch_results): # Ignorer les lots qui ont échoué (None)
        if 'extracted_data' in result_batch:
            for data_entry in result_batch['extracted_data']:
                # Utiliser un set garantit que chaque compétence n'est comptée qu'une fois par offre
                unique_skills_in_description = set(s.strip() for s in data_entry.get('skills', []) if s.strip())
                for skill_name in unique_skills_in_description:
                    skill_frequencies[skill_name] += 1
                
                education_level = data_entry.get('education_level', 'Non spécifié')
                if education_level and education_level != "Non spécifié":
                    education_frequencies[education_level] += 1
    
    # Trier les compétences par fréquence et prendre les meilleures
    sorted_skills = sorted(skill_frequencies.items(), key=lambda item: item[1], reverse=True)
    top_skills = [{"skill": skill, "frequency": freq} for skill, freq in sorted_skills[:TOP_SKILLS_LIMIT]]

    # Trouver le niveau d'études le plus fréquent
    top_education = max(education_frequencies, key=education_frequencies.get) if education_frequencies else "Non précisé"

    return {"skills": top_skills, "top_diploma": top_education}

async def get_skills_for_job(job_title: str, num_offers: int, logger: logging.Logger, force_refresh: bool = False) -> Optional[Dict[str, Any]]:
    """
    Orchestre le processus complet : cache, recherche d'offres, extraction de compétences et agrégation.

    :param job_title: Le métier à analyser.
    :param num_offers: Le nombre d'offres à viser pour l'analyse.
    :param logger: L'instance de logger pour le suivi.
    :param force_refresh: Si True, ignore le cache et effectue une nouvelle analyse.
    :return: Un dictionnaire avec les résultats finaux, ou None si le processus échoue.
    """
    logger.info(f"--- Début du processus pour '{job_title}' ({num_offers} offres) ---")
    
    # --- Étape 1: Gestion du cache ---
    cache_key = f"{job_title.lower().strip()}@{num_offers}"
    if force_refresh:
        logger.info(f"Forçage de l'actualisation pour '{cache_key}'. Suppression de l'ancienne entrée de cache.")
        delete_from_cache(cache_key)
    else:
        logger.info(f"Vérification du cache avec la clé '{cache_key}'.")
        cached_results = get_cached_results(cache_key)
        if cached_results:
            logger.info("Résultats trouvés dans le cache. Fin du processus.")
            return cached_results
        logger.info(f"Clé '{cache_key}' non trouvée dans le cache.")

    # --- Étape 2: Initialisation des services externes ---
    if not initialize_gemini():
        logger.critical("Échec de l'initialisation de Gemini. Abandon du processus.")
        return None

    # --- Étape 3: Récupération des données brutes ---
    logger.info(f"Appel à l'API France Travail pour '{job_title}'.")
    ft_client = FranceTravailClient(logger=logger)
    all_offers = await ft_client.search_offers_async(job_title, max_offers=num_offers)
    
    if not all_offers:
        logger.warning("Aucune offre France Travail trouvée. Fin du processus.")
        return None
        
    actual_offers_count = len(all_offers)
    descriptions = [offer['description'] for offer in all_offers if offer.get('description')]
    
    if not descriptions:
        logger.warning("Aucune description d'offre exploitable trouvée. Fin du processus.")
        return None
    logger.info(f"{actual_offers_count} offres avec {len(descriptions)} descriptions valides trouvées.")

    # --- Étape 4: Traitement parallèle avec Gemini ---
    description_chunks = _chunk_list(descriptions, GEMINI_BATCH_SIZE)
    logger.info(f"Division des descriptions en {len(description_chunks)} lots pour analyse parallèle.")
    
    # Création des tâches asynchrones pour chaque lot
    tasks = [extract_skills_with_gemini(job_title, chunk) for chunk in description_chunks]
    batch_results = await asyncio.gather(*tasks)
    
    # --- Étape 5: Agrégation et finalisation ---
    logger.info("Fusion et comptage des résultats de tous les lots...")
    aggregated_data = _aggregate_results(batch_results)
    
    if not aggregated_data.get("skills"):
        logger.error("L'analyse n'a produit aucune compétence. Fin du processus.")
        return None

    final_result = {
        "skills": aggregated_data["skills"],
        "top_diploma": aggregated_data["top_diploma"],
        "actual_offers_count": actual_offers_count 
    }
    
    logger.info(f"{len(final_result['skills'])} compétences uniques et diplôme le plus demandé '{final_result['top_diploma']}' agrégés.")

    # --- Étape 6: Mise en cache du résultat final ---
    logger.info(f"Mise en cache du résultat final avec la clé '{cache_key}'.")
    add_to_cache(cache_key, final_result)
    
    logger.info(f"--- Fin du processus pour '{job_title}' ---")
    return final_result