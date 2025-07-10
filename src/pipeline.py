import logging
import asyncio
from typing import Dict, Any, List, Optional, Callable
from collections import defaultdict
import re
import unicodedata

from src.france_travail_api import FranceTravailClient
from src.cache_manager import get_cached_results, add_to_cache
from src.gemini_extractor import extract_skills_with_gemini, initialize_gemini, clear_chat_session # <-- AJOUT : Import de clear_chat_session

# Configuration pour l'analyse des offres et les lots Gemini.
GEMINI_BATCH_SIZE = 5  # Définit la taille des lots de descriptions pour Gemini.
TOP_SKILLS_LIMIT = 20 # Nombre maximum de compétences à afficher dans le classement final.

def _chunk_list(data: List[Any], chunk_size: int) -> List[List[Any]]:
    """
    Divise une liste en sous-listes (chunks) de taille fixe pour le traitement par lots.
    """
    return [data[i:i + chunk_size] for i in range(0, len(data), chunk_size)]

def _aggregate_results(batch_results: List[Optional[Dict]]) -> Dict[str, Any]:
    """
    Agrège et compte les compétences et niveaux d'études extraits des différents lots Gemini.
    Cette fonction suppose que Gemini a déjà effectué la normalisation des compétences.
    Elle gère la déduplication au sein de chaque description avant le comptage global.
    """
    skill_frequencies = defaultdict(int)
    education_frequencies = defaultdict(int)

    for result_batch in filter(None, batch_results):
        if 'extracted_data' in result_batch:
            for data_entry in result_batch['extracted_data']:
                # Utilise un ensemble pour dédupliquer les compétences au sein d'une même description
                # Gemini est censé nous donner des compétences déjà normalisées.
                processed_skills_for_this_description = set()

                for skill_raw in data_entry.get('skills', []):
                    skill_stripped = skill_raw.strip()
                    if skill_stripped:
                        processed_skills_for_this_description.add(skill_stripped)

                for skill in processed_skills_for_this_description:
                    skill_frequencies[skill] += 1

                education_level = data_entry.get('education_level', 'Non spécifié')
                if education_level and education_level != "Non spécifié":
                    education_frequencies[education_level] += 1

    # Trie les compétences par fréquence d'apparition.
    sorted_skills = sorted(skill_frequencies.items(), key=lambda item: item[1], reverse=True)
    top_skills = [{"skill": skill, "frequency": freq} for skill, freq in sorted_skills[:TOP_SKILLS_LIMIT]]

    # Détermine le niveau d'études le plus fréquemment demandé.
    top_education = max(education_frequencies, key=education_frequencies.get) if education_frequencies else "Non précisé"

    return {"skills": top_skills, "top_diploma": top_education}


async def get_skills_for_job_streaming(
    job_title: str,
    num_offers: int,
    logger: logging.Logger,
    progress_callback: Optional[Callable[[Dict[str, Any], bool], None]] = None
) -> Optional[Dict[str, Any]]:
    """
    Orchestre le processus complet d'extraction de compétences : vérification du cache,
    recherche d'offres d'emploi, extraction via Gemini et agrégation des résultats.
    Permet des mises à jour progressives via un callback.
    """
    logger.info(f"Début du processus pour '{job_title}' ({num_offers} offres).")

    cache_key = f"{job_title}@{num_offers}"
    cached_results = get_cached_results(cache_key)
    if cached_results:
        logger.info(f"Résultats trouvés dans le cache pour '{cache_key}'. Fin du processus.")
        if progress_callback:
            await progress_callback(cached_results, True) # Envoyer les résultats finaux du cache.
        return cached_results
    logger.info(f"Aucun résultat en cache pour '{cache_key}', poursuite de l'analyse.")

    # La session de chat est gérée directement dans gemini_extractor, mais il faut s'assurer de l'initialisation.
    if not initialize_gemini(logger):
        logger.critical("Échec de l'initialisation de Gemini; abandon du processus.")
        return None

    all_offers_count = 0 # Initialisation du compteur d'offres réelles

    try: # Ajout d'un bloc try/finally pour garantir l'effacement de la session de chat.
        logger.info(f"Appel à l'API France Travail pour '{job_title}'.")
        ft_client = FranceTravailClient(logger=logger)
        all_offers = await ft_client.search_offers_async(job_title, max_offers=num_offers)
        all_offers_count = len(all_offers) # Mettre à jour le vrai nombre d'offres

        if not all_offers:
            logger.warning("Aucune offre France Travail trouvée; fin du processus.")
            if progress_callback:
                await progress_callback({"skills": [], "top_diploma": "Non précisé", "actual_offers_count": all_offers_count}, True)
            return None

        descriptions = [offer['description'] for offer in all_offers if offer.get('description')]
        if not descriptions:
            logger.warning("Aucune description d'offre exploitable trouvée; fin du processus.")
            if progress_callback:
                await progress_callback({"skills": [], "top_diploma": "Non précisé", "actual_offers_count": all_offers_count}, True)
            return None
        logger.info(f"{all_offers_count} offres trouvées, dont {len(descriptions)} avec une description valide.")

        # Division des descriptions en lots pour un traitement séquentiel par Gemini (via la même session de chat).
        description_chunks = _chunk_list(descriptions, GEMINI_BATCH_SIZE)
        logger.info(f"Division des descriptions en {len(description_chunks)} lots pour analyse séquentielle.")

        all_batch_results = []
        # Exécute les appels à Gemini séquentiellement pour permettre un traitement progressif
        # et bénéficier de la persistance de la session de chat.
        for i, chunk in enumerate(description_chunks):
            logger.info(f"Traitement du lot {i+1}/{len(description_chunks)} pour '{job_title}'...")
            batch_result = await extract_skills_with_gemini(job_title, chunk, logger) # job_title est utilisé comme clé de session
            if batch_result:
                all_batch_results.append(batch_result)
                # Agrège les résultats après chaque lot pour une mise à jour progressive
                current_aggregated_data = _aggregate_results(all_batch_results)
                if progress_callback:
                    await progress_callback({
                        "skills": current_aggregated_data["skills"],
                        "top_diploma": current_aggregated_data["top_diploma"],
                        "actual_offers_count": all_offers_count # Utiliser le nombre total d'offres
                    }, False) # Indiquer que ce ne sont pas les résultats finaux.


        logger.info("Fusion et comptage des résultats de tous les lots Gemini...")
        aggregated_data = _aggregate_results(all_batch_results)

        if not aggregated_data.get("skills"):
            logger.error("L'analyse n'a produit aucune compétence; fin du processus.")
            if progress_callback:
                await progress_callback({"skills": [], "top_diploma": "Non précisé", "actual_offers_count": all_offers_count}, True)
            return None

        final_result = {
            "skills": aggregated_data["skills"],
            "top_diploma": aggregated_data["top_diploma"],
            "actual_offers_count": all_offers_count
        }

        logger.info(f"Un total de {len(final_result['skills'])} compétences uniques et le diplôme le plus demandé ('{final_result['top_diploma']}') ont été agrégés.")

        logger.info(f"Mise en cache du résultat final avec la clé '{cache_key}'.")
        add_to_cache(cache_key, final_result)

        logger.info(f"Fin du processus pour '{job_title}'.")
        if progress_callback:
            await progress_callback(final_result, True) # Envoyer les résultats finaux.
        return final_result

    finally:
        # Assurez-vous de vider la session de chat une fois l'analyse terminée (succès ou échec).
        clear_chat_session(job_title)