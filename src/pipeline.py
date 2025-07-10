import logging
import asyncio
from typing import Dict, Any, List, Optional
from collections import defaultdict
import re
import unicodedata

# Les imports sont directs car 'src' est dans le sys.path de app.py
from france_travail_api import FranceTravailClient
from cache_manager import get_cached_results, add_to_cache
from gemini_extractor import extract_skills_with_gemini, initialize_gemini

# --- REMOVED: plus besoin de gemini_normalizer ---
# from gemini_normalizer import normalize_and_aggregate_skills, initialize_gemini_normalizer

# Configuration pour l'analyse des offres et les lots Gemini.
GEMINI_BATCH_SIZE = 5  # Définit la taille des lots de descriptions pour Gemini.
TOP_SKILLS_LIMIT = 20 # Nombre maximum de compétences à afficher dans le classement final.

# NOUVEAU : Suppression de _LOWERCASE_WORDS et _standardize_skill_python car la normalisation est déléguée à Gemini.


def _chunk_list(data: List[Any], chunk_size: int) -> List[List[Any]]:
    """
    Divise une liste en sous-listes (chunks) de taille fixe pour le traitement par lots.
    """
    return [data[i:i + chunk_size] for i in range(0, len(data), chunk_size)]

# MODIFICATION : Cette fonction agrégera directement les compétences PRÉ-NORMALISÉES par Gemini.
def _aggregate_final_results(batch_results: List[Optional[Dict]]) -> Dict[str, Any]:
    """
    Agrège et compte les compétences et niveaux d'études extraits des différents lots Gemini.
    Les compétences sont déjà normalisées et dédupliquées par Gemini pour chaque description.
    """
    skill_frequencies = defaultdict(int)
    education_frequencies = defaultdict(int)

    for result_batch in filter(None, batch_results):
        if 'extracted_data' in result_batch:
            for data_entry in result_batch['extracted_data']:
                # Les compétences sont déjà normalisées et dédupliquées par le prompt Gemini.
                for skill_normalized in data_entry.get('skills', []):
                    skill_frequencies[skill_normalized] += 1

                education_level = data_entry.get('education_level', 'Non spécifié')
                if education_level and education_level != "Non spécifié":
                    education_frequencies[education_level] += 1

    # Trie les compétences par fréquence d'apparition.
    sorted_skills = sorted(skill_frequencies.items(), key=lambda item: item[1], reverse=True)
    top_skills = [{"skill": skill_name, "frequency": freq} for skill_name, freq in sorted_skills[:TOP_SKILLS_LIMIT]]

    # Détermine le niveau d'études le plus fréquemment demandé.
    top_education = max(education_frequencies, key=education_frequencies.get) if education_frequencies else "Non précisé"

    return {"skills": top_skills, "top_diploma": top_education}

async def get_skills_for_job(job_title: str, num_offers: int, logger: logging.Logger) -> Optional[Dict[str, Any]]:
    """
    Orchestre le processus complet d'extraction de compétences : vérification du cache,
    recherche d'offres d'emploi, extraction via Gemini (avec normalisation intégrée) et agrégation des résultats.
    """
    logger.info(f"Début du processus pour '{job_title}' ({num_offers} offres).")

    cache_key = f"{job_title}@{num_offers}"
    cached_results = get_cached_results(cache_key)
    if cached_results:
        logger.info(f"Résultats trouvés dans le cache pour '{cache_key}'. Fin du processus.")
        return cached_results
    logger.info(f"Aucun résultat en cache pour '{cache_key}', poursuite de l'analyse.")

    # Initialisation de Gemini (maintenant responsable de l'extraction ET de la normalisation)
    if not initialize_gemini(logger):
        logger.critical("Échec de l'initialisation de Gemini; abandon du processus.")
        return None
    
    # REMOVED : plus besoin d'initialiser un second normalisateur Gemini


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

    # Division des descriptions en lots pour un traitement parallèle par Gemini.
    description_chunks = _chunk_list(descriptions, GEMINI_BATCH_SIZE)
    logger.info(f"Division des descriptions en {len(description_chunks)} lots pour analyse parallèle (Extraction & Normalisation).")

    # Exécute les appels à Gemini en parallèle.
    # Chaque réponse de Gemini contiendra déjà des compétences normalisées et dédupliquées.
    tasks = [extract_skills_with_gemini(job_title, chunk, logger) for chunk in description_chunks]
    extraction_batch_results = await asyncio.gather(*tasks)

    logger.info("Fusion et comptage des résultats de tous les lots Gemini (compétences déjà normalisées)...")
    # MODIFICATION : Appel à la nouvelle fonction d'agrégation
    aggregated_data = _aggregate_final_results(extraction_batch_results)

    if not aggregated_data.get("skills"):
        logger.error("L'analyse n'a produit aucune compétence; fin du processus.")
        return None

    final_result = {
        "skills": aggregated_data["skills"],
        "top_diploma": aggregated_data["top_diploma"],
        "actual_offers_count": len(all_offers)
    }

    logger.info(f"Un total de {len(final_result['skills'])} compétences uniques et le diplôme le plus demandé ('{final_result['top_diploma']}') ont été agrégés.")

    logger.info(f"Mise en cache du résultat final avec la clé '{cache_key}'.")
    add_to_cache(cache_key, final_result)

    logger.info(f"Fin du processus pour '{job_title}'.")
    return final_result