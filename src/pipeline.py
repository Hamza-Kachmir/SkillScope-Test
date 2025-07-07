# FICHIER : pipeline.py (contenu mis à jour)
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

async def get_skills_for_job(job_title: str, num_offers: int, logger: logging.Logger) -> Dict[str, Any] | None:
    """
    Orchestre le pipeline complet pour récupérer les compétences, le diplôme 
    et le nombre réel d'offres pour un métier donné.
    """
    logger.info(f"--- Début du processus pour '{job_title}' avec {num_offers} offres demandées ---")
    
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
        
    actual_offers_count = len(all_offers)
    logger.info(f"{actual_offers_count} offres France Travail réellement trouvées.")

    descriptions = [offer['description'] for offer in all_offers if offer.get('description')]
    if not descriptions:
        logger.warning("Aucune description exploitable. Fin du processus.")
        return None

    description_chunks = chunk_list(descriptions, 25)
    logger.info(f"Étape 3 : Division en {len(description_chunks)} lots pour analyse parallèle.")
    
    tasks = [extract_skills_with_gemini(job_title, chunk) for chunk in description_chunks]
    batch_results = await asyncio.gather(*tasks)
    
    logger.info("Étape 4 : Fusion et comptage des résultats...")
    skill_frequencies = defaultdict(int)
    education_frequencies = defaultdict(int)
    
    for result_batch in batch_results:
        # La clé principale du JSON de Gemini est maintenant 'extracted_data'
        if result_batch and 'extracted_data' in result_batch:
            for data_entry in result_batch['extracted_data']:
                # On utilise un set pour garantir l'unicité des compétences par description avant de compter
                unique_skills_in_description = set(data_entry.get('skills', []))
                for skill_name in unique_skills_in_description:
                    skill_frequencies[skill_name] += 1
                
                # Comptage du niveau d'études
                education_level = data_entry.get('education_level', 'Non spécifié')
                if education_level and education_level != "Non spécifié":
                    education_frequencies[education_level] += 1
    
    if not skill_frequencies:
        logger.error("La fusion des résultats n'a produit aucune compétence. Fin du processus.")
        return None

    # Tri et limitation au TOP 30 des compétences
    sorted_skills = sorted(skill_frequencies.items(), key=lambda x: x[1], reverse=True)
    top_30_skills = [{"skill": skill, "frequency": freq} for skill, freq in sorted_skills[:30]]

    # Détermination du diplôme le plus fréquent
    top_education = max(education_frequencies, key=education_frequencies.get) if education_frequencies else "Non précisé"

    # Le dictionnaire final retourné contient toutes les nouvelles informations
    final_result = {
        "skills": top_30_skills,
        "top_diploma": top_education,
        "actual_offers_count": actual_offers_count 
    }
    
    logger.info(f"Fusion terminée. {len(top_30_skills)} compétences et diplôme '{top_education}' aggrégés.")

    logger.info(f"Étape 5 : Mise en cache du résultat final avec la clé '{cache_key}'.")
    add_to_cache(cache_key, final_result)
    
    logger.info(f"--- Fin du processus pour '{job_title}' ---")
    return final_result