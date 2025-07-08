import logging
import asyncio
from typing import Dict, Any, List, Optional
from collections import defaultdict

from src.france_travail_api import FranceTravailClient
from src.cache_manager import get_cached_results, add_to_cache
from src.gemini_extractor import extract_skills_with_gemini, initialize_gemini

# --- Constantes du Pipeline ---
# Un batch size plus petit augmente le parallélisme (plus d'appels simultanés à l'API)
# ce qui peut accélérer le temps de réponse global.
GEMINI_BATCH_SIZE = 13
TOP_SKILLS_LIMIT = 30

def _chunk_list(data: List[Any], chunk_size: int) -> List[List[Any]]:
    """Divise une liste en sous-listes (chunks) de taille fixe."""
    return [data[i:i + chunk_size] for i in range(0, len(data), chunk_size)]

def _aggregate_results(batch_results: List[Optional[Dict]]) -> Dict[str, Any]:
    """
    Agrège et compte les compétences et niveaux d'études des différents lots Gemini.

    :param batch_results: Une liste de résultats bruts provenant des appels à Gemini.
    :return: Un dictionnaire contenant les compétences et le diplôme agrégés.
    """
    skill_frequencies = defaultdict(int)
    education_frequencies = defaultdict(int)

    # filter(None, ...) permet d'ignorer les lots qui auraient pu échouer et retourner None
    for result_batch in filter(None, batch_results):
        if 'extracted_data' in result_batch:
            for data_entry in result_batch['extracted_data']:
                # Utiliser un set garantit que chaque compétence n'est comptée qu'une fois par offre,
                # même si elle apparaît plusieurs fois dans la même description.
                unique_skills_in_description = set(s.strip() for s in data_entry.get('skills', []) if s.strip())
                for skill_name in unique_skills_in_description:
                    skill_frequencies[skill_name] += 1
                
                education_level = data_entry.get('education_level', 'Non spécifié')
                if education_level and education_level != "Non spécifié":
                    education_frequencies[education_level] += 1
    
    # Trier les compétences par fréquence pour ne garder que les plus pertinentes
    sorted_skills = sorted(skill_frequencies.items(), key=lambda item: item[1], reverse=True)
    top_skills = [{"skill": skill, "frequency": freq} for skill, freq in sorted_skills[:TOP_SKILLS_LIMIT]]

    # Trouver le niveau d'études le plus demandé
    top_education = max(education_frequencies, key=education_frequencies.get) if education_frequencies else "Non précisé"

    return {"skills": top_skills, "top_diploma": top_education}

async def get_skills_for_job(job_title: str, num_offers: int, logger: logging.Logger) -> Optional[Dict[str, Any]]:
    """
    Orchestre le processus complet : cache, recherche, extraction et agrégation.

    :param job_title: Le métier à analyser.
    :param num_offers: Le nombre d'offres à viser pour l'analyse.
    :param logger: L'instance de logger pour le suivi.
    :return: Un dictionnaire avec les résultats finaux, ou None si le processus échoue.
    """
    logger.info(f"--- Début du processus pour '{job_title}' ({num_offers} offres) ---")
    
    # Étape 1: Vérification du cache pour une réponse instantanée
    cache_key = f"{job_title.lower().strip()}@{num_offers}"
    cached_results = get_cached_results(cache_key)
    if cached_results:
        logger.info(f"Résultats trouvés dans le cache pour '{cache_key}'. Fin du processus.")
        return cached_results
    logger.info(f"Aucun résultat en cache pour '{cache_key}', poursuite de l'analyse.")

    # Étape 2: Initialisation des services externes (si nécessaire)
    if not initialize_gemini():
        logger.critical("Échec de l'initialisation de Gemini. Abandon du processus.")
        return None

    # Étape 3: Récupération des données brutes depuis l'API externe
    logger.info(f"Appel à l'API France Travail pour '{job_title}'.")
    ft_client = FranceTravailClient(logger=logger)
    all_offers = await ft_client.search_offers_async(job_title, max_offers=num_offers)
    
    if not all_offers:
        logger.warning("Aucune offre France Travail trouvée. Fin du processus.")
        return None
        
    # Filtrer les offres qui n'ont pas de description
    descriptions = [offer['description'] for offer in all_offers if offer.get('description')]
    if not descriptions:
        logger.warning("Aucune description d'offre exploitable trouvée. Fin du processus.")
        return None
    logger.info(f"{len(all_offers)} offres trouvées, dont {len(descriptions)} avec une description valide.")

    # Étape 4: Traitement parallèle avec Gemini
    description_chunks = _chunk_list(descriptions, GEMINI_BATCH_SIZE)
    logger.info(f"Division des descriptions en {len(description_chunks)} lots pour analyse parallèle.")
    
    tasks = [extract_skills_with_gemini(job_title, chunk) for chunk in description_chunks]
    batch_results = await asyncio.gather(*tasks)
    
    # Étape 5: Agrégation et finalisation des résultats
    logger.info("Fusion et comptage des résultats de tous les lots...")
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

    # Étape 6: Mise en cache du résultat final pour les prochaines requêtes
    logger.info(f"Mise en cache du résultat final avec la clé '{cache_key}'.")
    add_to_cache(cache_key, final_result)
    
    logger.info(f"--- Fin du processus pour '{job_title}' ---")
    return final_result