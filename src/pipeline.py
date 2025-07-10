import logging
import asyncio
from typing import Dict, Any, List, Optional
from collections import defaultdict
import re
import unicodedata

from src.france_travail_api import FranceTravailClient
from src.cache_manager import get_cached_results, add_to_cache
from src.gemini_extractor import extract_skills_with_gemini, initialize_gemini

# Configuration pour l'analyse des offres et les lots Gemini.
GEMINI_BATCH_SIZE = 10  # Définit la taille des lots de descriptions pour Gemini pour permettre un streaming visuel.
TOP_SKILLS_LIMIT = 20 # Nombre maximum de compétences à afficher dans le classement final.


def _chunk_list(data: List[Any], chunk_size: int) -> List[List[Any]]:
    """
    Divise une liste en sous-listes (chunks) de taille fixe pour le traitement par lots.
    """
    return [data[i:i + chunk_size] for i in range(0, len(data), chunk_size)]

def _aggregate_results_incremental(batch_results: List[Optional[Dict]]) -> Dict[str, Any]:
    """
    Agrège et compte les compétences et niveaux d'études extraits des différents lots Gemini.
    Cette fonction s'attend à ce que Gemini ait déjà effectué la normalisation et la déduplication
    par description. Elle est conçue pour être appelée incrémentiellement.
    """
    skill_frequencies = defaultdict(int)
    education_frequencies = defaultdict(int)

    for result_batch in filter(None, batch_results):
        if 'extracted_data' in result_batch:
            for data_entry in result_batch['extracted_data']:
                # Les compétences sont déjà normalisées et dédupliquées par Gemini.
                for skill in data_entry.get('skills', []):
                    skill_stripped = skill.strip()
                    if skill_stripped: # S'assurer que la compétence n'est pas vide après strip
                        skill_frequencies[skill_stripped] += 1

                education_level = data_entry.get('education_level', 'Non spécifié')
                if education_level and education_level != "Non spécifié":
                    education_frequencies[education_level] += 1

    # Ici, nous ne limitons pas encore les compétences, nous retournons tout pour l'agrégation externe
    return {"skills_raw": skill_frequencies, "education_raw": education_frequencies}

async def get_skills_for_job_streaming(job_title: str, num_offers: int, logger: logging.Logger, update_callback) -> Optional[Dict[str, Any]]:
    """
    Orchestre le processus complet d'extraction de compétences : vérification du cache,
    recherche d'offres d'emploi, extraction via Gemini et agrégation des résultats.
    Le `update_callback` est une fonction ou coroutine qui sera appelée après chaque lot Gemini.
    """
    logger.info(f"Début du processus streaming pour '{job_title}' ({num_offers} offres).")

    cache_key = f"{job_title}@{num_offers}"
    cached_results = get_cached_results(cache_key)
    if cached_results:
        logger.info(f"Résultats trouvés dans le cache pour '{cache_key}'. Fin du processus.")
        # Appel le callback une dernière fois avec les résultats finaux du cache
        await update_callback(cached_results, final=True)
        return cached_results
    logger.info(f"Aucun résultat en cache pour '{cache_key}', poursuite de l'analyse.")

    if not initialize_gemini(logger):
        logger.critical("Échec de l'initialisation de Gemini; abandon du processus.")
        return None

    logger.info(f"Appel à l'API France Travail pour '{job_title}'.")
    ft_client = FranceTravailClient(logger=logger)
    all_offers = await ft_client.search_offers_async(job_title, max_offers=num_offers)

    if not all_offers:
        logger.warning("Aucune offre France Travail trouvée; fin du processus.")
        return None

    descriptions = [offer['description'] for offer in all_offers if offer.get('description')]
    if not descriptions:
        logger.warning("Aucune description d'offre exploitable trouvée; fin du processus.")
        return None
    logger.info(f"{len(all_offers)} offres trouvées, dont {len(descriptions)} avec une description valide.")

    description_chunks = _chunk_list(descriptions, GEMINI_BATCH_SIZE)
    logger.info(f"Division des descriptions en {len(description_chunks)} lots pour analyse progressive.")

    overall_skill_frequencies = defaultdict(int)
    overall_education_frequencies = defaultdict(int)
    processed_offers_count = 0

    for i, chunk in enumerate(description_chunks):
        logger.info(f"Traitement du lot {i+1}/{len(description_chunks)} ({len(chunk)} descriptions)...")
        batch_result = await extract_skills_with_gemini(job_title, chunk, logger)

        if batch_result and 'extracted_data' in batch_result:
            for data_entry in batch_result['extracted_data']:
                processed_offers_count += 1
                for skill in data_entry.get('skills', []):
                    skill_stripped = skill.strip()
                    if skill_stripped:
                        overall_skill_frequencies[skill_stripped] += 1

                education_level = data_entry.get('education_level', 'Non spécifié')
                if education_level and education_level != "Non spécifié":
                    overall_education_frequencies[education_level] += 1

            # Calculer les compétences et le top diplôme à chaque itération pour la mise à jour progressive
            sorted_skills = sorted(overall_skill_frequencies.items(), key=lambda item: item[1], reverse=True)
            current_top_skills = [{"skill": skill, "frequency": freq} for skill, freq in sorted_skills[:TOP_SKILLS_LIMIT]]
            current_top_education = max(overall_education_frequencies, key=overall_education_frequencies.get) if overall_education_frequencies else "Non précisé"

            # Appeler le callback pour mettre à jour l'UI
            await update_callback({
                "skills": current_top_skills,
                "top_diploma": current_top_education,
                "actual_offers_count": processed_offers_count # Indiquer le nombre d'offres traitées
            }, final=False)
        else:
            logger.warning(f"Lot {i+1} n'a pas retourné de données valides ou d'erreurs.")


    # Finalisation des résultats
    sorted_skills_final = sorted(overall_skill_frequencies.items(), key=lambda item: item[1], reverse=True)
    final_top_skills = [{"skill": skill, "frequency": freq} for skill, freq in sorted_skills_final[:TOP_SKILLS_LIMIT]]
    final_top_education = max(overall_education_frequencies, key=overall_education_frequencies.get) if overall_education_frequencies else "Non précisé"

    final_result = {
        "skills": final_top_skills,
        "top_diploma": final_top_education,
        "actual_offers_count": len(all_offers)
    }

    logger.info(f"Un total de {len(final_result['skills'])} compétences uniques et le diplôme le plus demandé ('{final_result['top_diploma']}') ont été agrégés.")

    logger.info(f"Mise en cache du résultat final avec la clé '{cache_key}'.")
    add_to_cache(cache_key, final_result)

    logger.info(f"Fin du processus pour '{job_title}'.")
    # Appel final du callback avec le flag final=True
    await update_callback(final_result, final=True)
    return final_result