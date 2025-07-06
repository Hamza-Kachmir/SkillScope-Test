import logging
import asyncio
from typing import Dict, Any, List
from collections import defaultdict

from src.france_travail_api import FranceTravailClient
from src.cache_manager import get_cached_results, add_to_cache
from src.gemini_extractor import extract_skills_with_gemini, initialize_gemini

def chunk_list(data: List[Any], chunk_size: int) -> List[List[Any]]:
    """Divise une liste en sous-listes de taille chunk_size."""
    return [data[i:i + chunk_size] for i in range(0, len(data), chunk_size)]

async def get_skills_for_job(job_title: str, logger: logging.Logger) -> Dict[str, Any] | None:
    logger.info(f"--- Début du processus pour le métier : '{job_title}' ---")
    
    logger.info(f"Étape 1 : Vérification du cache pour '{job_title}'.")
    cached_results = get_cached_results(job_title)
    if cached_results:
        logger.info(f"'{job_title}' trouvé dans le cache. Fin du processus.")
        return cached_results
    
    logger.info(f"'{job_title}' non trouvé dans le cache. Poursuite du processus d'extraction.")
    
    if not initialize_gemini():
        raise ConnectionError("Impossible d'initialiser l'API Gemini. Vérifiez les logs.")

    logger.info(f"Étape 2 : Appel à l'API France Travail pour '{job_title}'.")
    ft_client = FranceTravailClient(client_id=None, client_secret=None, logger=logger)
    
    all_offers = await ft_client.search_offers_async(job_title, max_offers=200)
    if not all_offers:
        logger.warning(f"Aucune offre France Travail trouvée pour '{job_title}'. Fin du processus.")
        return None
        
    logger.info(f"{len(all_offers)} offres France Travail trouvées.")

    descriptions = [offer['description'] for offer in all_offers if offer.get('description')]
    if not descriptions:
        logger.warning("Aucune description exploitable dans les offres trouvées. Fin du processus.")
        return None

    # Étape 3 : Lancement des analyses en parallèle par lots de 25
    description_chunks = chunk_list(descriptions, 25)
    logger.info(f"Division des descriptions en {len(description_chunks)} lots de 25 pour analyse parallèle.")
    
    tasks = []
    for chunk in description_chunks:
        task = extract_skills_with_gemini(job_title, chunk)
        tasks.append(task)
    
    # Exécute toutes les tâches en parallèle
    batch_results = await asyncio.gather(*tasks)
    
    # Étape 4 : Fusion des résultats de tous les "agents"
    logger.info("Toutes les analyses parallèles sont terminées. Fusion des résultats...")
    final_frequencies = defaultdict(int)
    for result in batch_results:
        if result and 'skills' in result:
            for item in result['skills']:
                skill_name = item.get('skill')
                frequency = item.get('frequency', 0)
                if skill_name:
                    final_frequencies[skill_name] += frequency
    
    if not final_frequencies:
        logger.error("La fusion des résultats n'a produit aucune compétence. Fin du processus.")
        return None

    # Transformation du dictionnaire en liste triée, comme attendu par l'UI
    merged_skills = [{"skill": skill, "frequency": freq} for skill, freq in final_frequencies.items()]
    merged_skills.sort(key=lambda x: x['frequency'], reverse=True)
    
    final_result = {"skills": merged_skills}
    logger.info(f"Fusion terminée. {len(merged_skills)} compétences uniques aggrégées.")

    logger.info(f"Étape 5 : Mise en cache du résultat final pour '{job_title}'.")
    add_to_cache(job_title, final_result)
    
    logger.info(f"--- Fin du processus pour '{job_title}' ---")
    return final_result