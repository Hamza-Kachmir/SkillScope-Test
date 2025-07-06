import logging
import asyncio
from typing import Dict, Any, List
from collections import defaultdict

from src.france_travail_api import FranceTravailClient
from src.cache_manager import get_cached_results, add_to_cache
# CORRECTION : On importe le nouveau nom de la fonction
from src.gemini_extractor import extract_skills_for_single_offer, initialize_gemini

async def get_skills_for_job(job_title: str, num_offers: int, logger: logging.Logger) -> Dict[str, Any] | None:
    logger.info(f"--- Début du processus pour '{job_title}' avec {num_offers} offres ---")
    
    cache_key = f"{job_title.lower().strip()}@{num_offers}"
    
    logger.info(f"Étape 1 : Vérification du cache avec la clé '{cache_key}'.")
    cached_results = get_cached_results(cache_key)
    if cached_results:
        logger.info(f"Clé '{cache_key}' trouvée dans le cache. Fin du processus.")
        return cached_results
    
    logger.info(f"Clé '{cache_key}' non trouvée. Poursuite du processus d'extraction.")
    
    if not initialize_gemini():
        raise ConnectionError("Impossible d'initialiser l'API Gemini. Vérifiez les logs.")

    logger.info(f"Étape 2 : Appel à l'API France Travail pour '{job_title}'.")
    ft_client = FranceTravailClient(client_id=None, client_secret=None, logger=logger)
    
    all_offers = await ft_client.search_offers_async(job_title, max_offers=num_offers)
    if not all_offers:
        logger.warning(f"Aucune offre France Travail trouvée. Fin du processus.")
        return None
        
    logger.info(f"{len(all_offers)} offres France Travail trouvées.")

    descriptions = [offer['description'] for offer in all_offers if offer.get('description')]
    if not descriptions:
        logger.warning("Aucune description exploitable. Fin du processus.")
        return None

    # Étape 3 : Lancement des analyses individuelles en parallèle
    logger.info(f"Lancement de {len(descriptions)} analyses individuelles en parallèle...")
    
    # Limite le nombre d'appels simultanés pour ne pas surcharger l'API
    semaphore = asyncio.Semaphore(8)

    async def worker(description):
        async with semaphore:
            return await extract_skills_for_single_offer(description)

    tasks = [worker(desc) for desc in descriptions]
    list_of_results_per_offer = await asyncio.gather(*tasks)
    
    # Étape 4 : Agrégation et comptage de fréquence
    logger.info("Toutes les analyses sont terminées. Agrégation des résultats...")
    
    all_skills_flat_list = []
    for result in list_of_results_per_offer:
        if result:
            all_skills_flat_list.extend(result.get('hard_skills', []))
            all_skills_flat_list.extend(result.get('soft_skills', []))
            all_skills_flat_list.extend(result.get('languages', []))

    if not all_skills_flat_list:
        logger.error("L'analyse n'a produit aucune compétence. Fin du processus.")
        return None

    # Compter la fréquence de chaque compétence
    final_frequencies = defaultdict(int)
    for skill in all_skills_flat_list:
        normalized_skill = skill.strip().lower()
        if normalized_skill:
            final_frequencies[normalized_skill] += 1
            
    # Formater pour l'affichage et le cache
    merged_skills = sorted([{"skill": skill, "frequency": freq} for skill, freq in final_frequencies.items()], key=lambda x: x['frequency'], reverse=True)
    final_result = {"skills": merged_skills}
    logger.info(f"Agrégation terminée. {len(merged_skills)} compétences uniques trouvées.")

    logger.info(f"Étape 5 : Mise en cache du résultat final avec la clé '{cache_key}'.")
    add_to_cache(cache_key, final_result)
    
    logger.info(f"--- Fin du processus pour '{job_title}' ---")
    return final_result