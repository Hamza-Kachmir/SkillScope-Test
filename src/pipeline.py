import logging
from typing import Dict, Any

from src.france_travail_api import FranceTravailClient
from src.cache_manager import get_cached_results, add_to_cache
from src.gemini_extractor import extract_skills_with_gemini, initialize_gemini

async def get_skills_for_job(job_title: str, logger: logging.Logger) -> Dict[str, Any] | None:
    logger.info(f"Début de l'analyse pour le métier : '{job_title}'")
    
    cached_results = get_cached_results(job_title)
    if cached_results:
        logger.info(f"'{job_title}' trouvé dans le cache. Utilisation des données existantes.")
        return cached_results
    
    logger.info(f"'{job_title}' non trouvé dans le cache. Lancement du processus d'extraction.")
    
    if not initialize_gemini():
        raise ConnectionError("Impossible d'initialiser l'API Gemini. Vérifiez les logs.")

    ft_client = FranceTravailClient(client_id=None, client_secret=None, logger=logger)
    
    all_offers = await ft_client.search_offers_async(job_title, max_offers=50)
    if not all_offers:
        logger.warning(f"Aucune offre France Travail trouvée pour '{job_title}'.")
        return None
        
    logger.info(f"{len(all_offers)} offres France Travail trouvées. Préparation pour l'analyse Gemini.")

    descriptions = [offer['description'] for offer in all_offers if offer.get('description')]
    if not descriptions:
        logger.warning("Aucune description exploitable dans les offres trouvées.")
        return None

    gemini_results = await extract_skills_with_gemini(job_title, descriptions)
    
    if not gemini_results:
        logger.error("L'extraction de compétences avec Gemini a échoué.")
        return None

    logger.info(f"Compétences extraites avec succès. Mise en cache pour '{job_title}'.")
    add_to_cache(job_title, gemini_results)
    
    return gemini_results