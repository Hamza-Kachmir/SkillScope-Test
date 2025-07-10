# pipeline.py
import logging
import asyncio
from typing import Dict, Any, List, Optional
from collections import defaultdict
import re
import unicodedata

from france_travail_api import FranceTravailClient # Change here
from cache_manager import get_cached_results, add_to_cache # Change here
from gemini_extractor import extract_skills_with_gemini, initialize_gemini # Change here
from gemini_normalizer import normalize_and_aggregate_skills, initialize_gemini_normalizer # NOUVEAU : Import du normaliseur Gemini

# Configuration pour l'analyse des offres et les lots Gemini.
GEMINI_BATCH_SIZE = 5  # Définit la taille des lots de descriptions pour Gemini.
TOP_SKILLS_LIMIT = 20 # Nombre maximum de compétences à afficher dans le classement final.

# NOUVEAU : Suppression de _LOWERCASE_WORDS et _standardize_skill_python car la normalisation est déléguée à Gemini.


def _chunk_list(data: List[Any], chunk_size: int) -> List[List[Any]]:
    """
    Divise une liste en sous-listes (chunks) de taille fixe pour le traitement par lots.
    """
    return [data[i:i + chunk_size] for i in range(0, len(data), chunk_size)]

def _aggregate_raw_results_for_normalization(batch_results: List[Optional[Dict]]) -> Dict[str, Any]:
    """
    Agrège les compétences brutes et les niveaux d'études extraits des différents lots Gemini
    avant de les envoyer au normaliseur Gemini.
    """
    all_raw_skills = defaultdict(int)
    education_frequencies = defaultdict(int)

    for result_batch in filter(None, batch_results):
        if 'extracted_data' in result_batch:
            for data_entry in result_batch['extracted_data']:
                # Utilise un ensemble pour dédupliquer les compétences au sein d'une même description.
                processed_skills_for_this_description = set()

                for skill_raw in data_entry.get('skills', []):
                    skill_stripped = skill_raw.strip()
                    if skill_stripped:
                        processed_skills_for_this_description.add(skill_stripped) # Ajoute la compétence brute

                for skill_key in processed_skills_for_this_description:
                    all_raw_skills[skill_key] += 1 # Compte les occurrences brutes

                education_level = data_entry.get('education_level', 'Non spécifié')
                if education_level and education_level != "Non spécifié":
                    education_frequencies[education_level] += 1

    return {
        "raw_skills_with_counts": dict(all_raw_skills),
        "education_frequencies": dict(education_frequencies)
    }

async def get_skills_for_job(job_title: str, num_offers: int, logger: logging.Logger) -> Optional[Dict[str, Any]]:
    """
    Orchestre le processus complet d'extraction de compétences : vérification du cache,
    recherche d'offres d'emploi, extraction via Gemini et agrégation des résultats.
    """
    logger.info(f"Début du processus pour '{job_title}' ({num_offers} offres).")

    cache_key = f"{job_title}@{num_offers}"
    cached_results = get_cached_results(cache_key)
    if cached_results:
        logger.info(f"Résultats trouvés dans le cache pour '{cache_key}'. Fin du processus.")
        return cached_results
    logger.info(f"Aucun résultat en cache pour '{cache_key}', poursuite de l'analyse.")

    # Initialisation du premier modèle Gemini (extraction)
    if not initialize_gemini(logger):
        logger.critical("Échec de l'initialisation de Gemini pour l'extraction; abandon du processus.")
        return None

    # Initialisation du second modèle Gemini (normalisation)
    if not initialize_gemini_normalizer(logger):
        logger.critical("Échec de l'initialisation de Gemini pour la normalisation; abandon du processus.")
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

    # Division des descriptions en lots pour un traitement parallèle par Gemini.
    description_chunks = _chunk_list(descriptions, GEMINI_BATCH_SIZE)
    logger.info(f"Division des descriptions en {len(description_chunks)} lots pour analyse parallèle (Extraction).")

    # Exécute les appels à Gemini pour l'extraction en parallèle.
    tasks = [extract_skills_with_gemini(job_title, chunk, logger) for chunk in description_chunks]
    extraction_batch_results = await asyncio.gather(*tasks)

    logger.info("Agrégation des résultats bruts pour envoi au normalisateur Gemini...")
    aggregated_raw_data = _aggregate_raw_results_for_normalization(extraction_batch_results)

    raw_skills_with_counts = aggregated_raw_data["raw_skills_with_counts"]
    education_frequencies = aggregated_raw_data["education_frequencies"]

    if not raw_skills_with_counts:
        logger.error("L'extraction n'a produit aucune compétence brute; fin du processus.")
        return None

    logger.info(f"Envoi des compétences brutes au normalisateur Gemini pour consolidation et nettoyage ({len(raw_skills_with_counts)} compétences uniques brutes).")
    normalized_skills_data = await normalize_and_aggregate_skills(dict(raw_skills_with_counts), logger)

    if not normalized_skills_data:
        logger.error("La normalisation Gemini n'a produit aucune compétence; fin du processus.")
        return None

    # Trie les compétences normalisées par fréquence d'apparition.
    # Les données reçues de normalize_and_aggregate_skills sont déjà agrégées.
    sorted_skills = sorted(normalized_skills_data.items(), key=lambda item: item[1], reverse=True)
    top_skills = [{"skill": skill_name, "frequency": freq} for skill_name, freq in sorted_skills[:TOP_SKILLS_LIMIT]]

    # Détermine le niveau d'études le plus fréquemment demandé.
    top_education = max(education_frequencies, key=education_frequencies.get) if education_frequencies else "Non précisé"


    final_result = {
        "skills": top_skills,
        "top_diploma": top_education,
        "actual_offers_count": len(all_offers)
    }

    logger.info(f"Un total de {len(final_result['skills'])} compétences uniques (normalisées) et le diplôme le plus demandé ('{final_result['top_diploma']}') ont été agrégés.")

    logger.info(f"Mise en cache du résultat final avec la clé '{cache_key}'.")
    add_to_cache(cache_key, final_result)

    logger.info(f"Fin du processus pour '{job_title}'.")
    return final_result