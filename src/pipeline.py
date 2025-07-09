import logging
import asyncio
from typing import Dict, Any, List, Optional
from collections import defaultdict
# re n'est plus nécessaire car aucune fonction de normalisation Python n'est utilisée.

from src.france_travail_api import FranceTravailClient
from src.cache_manager import get_cached_results, add_to_cache
from src.gemini_extractor import extract_skills_with_gemini, initialize_gemini

# Configuration pour l'analyse des offres et les lots Gemini.
GEMINI_BATCH_SIZE = 100  # Nombre de descriptions par lot pour les appels Gemini (pour 100 offres, cela génère 20 lots).
TOP_SKILLS_LIMIT = 20 # Nombre maximum de compétences à afficher dans le classement final.

# Toutes les fonctions de normalisation Python spécifiques aux compétences ont été supprimées.
# La normalisation (casse, singulier/pluriel, sémantique) est entièrement gérée par Gemini via le prompt.


def _chunk_list(data: List[Any], chunk_size: int) -> List[List[Any]]:
    """
    Divise une liste en sous-listes (chunks) de taille fixe.

    :param data: La liste à diviser.
    :param chunk_size: La taille maximale de chaque sous-liste.
    :return: Une liste de listes (chunks).
    """
    return [data[i:i + chunk_size] for i in range(0, len(data), chunk_size)]

def _aggregate_results(batch_results: List[Optional[Dict]]) -> Dict[str, Any]:
    """
    Agrège et compte les compétences et niveaux d'études extraits des différents lots par Gemini.
    Les compétences sont utilisées telles que retournées par Gemini (après simple stripping).

    :param batch_results: Une liste de résultats bruts provenant des appels à Gemini.
    :return: Un dictionnaire contenant les compétences agrégées par fréquence et le diplôme le plus demandé.
    """
    skill_frequencies = defaultdict(int) # Stockera {compétence_telle_que_retournée_par_Gemini: count}
    education_frequencies = defaultdict(int)

    for result_batch in filter(None, batch_results):
        if 'extracted_data' in result_batch:
            for data_entry in result_batch['extracted_data']:
                # Utilise un ensemble pour dédupliquer les compétences au sein d'une même description.
                # Les compétences sont utilisées telles que retournées par Gemini, après stripping.
                unique_skills_in_description = set(s.strip() for s in data_entry.get('skills', []) if s.strip())
                for skill_name in unique_skills_in_description:
                    skill_frequencies[skill_name] += 1
                
                education_level = data_entry.get('education_level', 'Non spécifié')
                if education_level and education_level != "Non spécifié":
                    education_frequencies[education_level] += 1
    
    # Trie les compétences par fréquence d'apparition (la plus fréquente en premier).
    # Le nom de la compétence est celui directement retourné par Gemini et agrégé.
    sorted_skills = sorted(skill_frequencies.items(), key=lambda item: item[1], reverse=True)
    top_skills = [{"skill": skill, "frequency": freq} for skill, freq in sorted_skills[:TOP_SKILLS_LIMIT]]

    # Détermine le niveau d'études le plus fréquemment demandé.
    top_education = max(education_frequencies, key=education_frequencies.get) if education_frequencies else "Non précisé"

    return {"skills": top_skills, "top_diploma": top_education}

async def get_skills_for_job(job_title: str, num_offers: int, logger: logging.Logger) -> Optional[Dict[str, Any]]:
    """
    Orchestre le processus complet d'extraction de compétences : vérification du cache,
    recherche d'offres d'emploi, extraction via Gemini et agrégation des résultats.

    Le `job_title` passé est déjà normalisé (minuscules, sans accents) pour la recherche et le cache.

    :param job_title: Le métier à analyser (déjà normalisé).
    :param num_offers: Le nombre d'offres à viser pour l'analyse.
    :param logger: L'instance de logger à utiliser pour le suivi des opérations.
    :return: Un dictionnaire avec les résultats finaux (compétences, diplôme, nombre d'offres),
             ou None si le processus échoue.
    """
    logger.info(f"Début du processus pour '{job_title}' ({num_offers} offres).")
    
    cache_key = f"{job_title}@{num_offers}" 
    cached_results = get_cached_results(cache_key) # Tente de récupérer les résultats du cache.
    if cached_results:
        logger.info(f"Résultats trouvés dans le cache pour '{cache_key}'. Fin du processus.")
        return cached_results
    logger.info(f"Aucun résultat en cache pour '{cache_key}', poursuite de l'analyse.")

    if not initialize_gemini(logger): 
        logger.critical("Échec de l'initialisation de Gemini. Abandon du processus.")
        return None

    logger.info(f"Appel à l'API France Travail pour '{job_title}'.")
    ft_client = FranceTravailClient(logger=logger) 
    all_offers = await ft_client.search_offers_async(job_title, max_offers=num_offers) 
    
    if not all_offers:
        logger.warning("Aucune offre France Travail trouvée. Fin du processus.")
        return None
        
    descriptions = [offer['description'] for offer in all_offers if offer.get('description')]
    if not descriptions:
        logger.warning("Aucune description d'offre exploitable trouvée. Fin du processus.")
        return None
    logger.info(f"{len(all_offers)} offres trouvées, dont {len(descriptions)} avec une description valide.")

    # Division des descriptions en lots pour un traitement parallèle par Gemini.
    description_chunks = _chunk_list(descriptions, GEMINI_BATCH_SIZE)
    logger.info(f"Division des descriptions en {len(description_chunks)} lots pour analyse parallèle (taille de lot: {GEMINI_BATCH_SIZE}).") 
    
    # Exécute les appels à Gemini en parallèle.
    tasks = [extract_skills_with_gemini(job_title, chunk, logger) for chunk in description_chunks] 
    batch_results = await asyncio.gather(*tasks)
    
    logger.info("Fusion et comptage des résultats de tous les lots Gemini...")
    aggregated_data = _aggregate_results(batch_results) 
    
    if not aggregated_data.get("skills"):
        logger.error("L'analyse n'a produit aucune compétence. Fin du processus.")
        return None

    final_result = {
        "skills": aggregated_data["skills"],
        "top_diploma": aggregated_data["top_diploma"],
        "actual_offers_count": len(all_offers)
    }
    
    logger.info(f"{len(final_result['skills'])} compétences uniques et diplôme le plus demandé ('{final_result['top_diploma']}') ont été agrégés.")

    logger.info(f"Mise en cache du résultat final avec la clé '{cache_key}'.")
    add_to_cache(cache_key, final_result)
    
    logger.info(f"Fin du processus pour '{job_title}'.")
    return final_result