import logging
import asyncio
from typing import Dict, Any, List, Optional, Callable, Awaitable
from collections import defaultdict

from src.france_travail_api import FranceTravailClient
from src.cache_manager import get_cached_results, add_to_cache
from src.gemini_extractor import extract_skills_with_gemini, initialize_gemini

# --- Constantes du Pipeline ---
GEMINI_BATCH_SIZE = 25
TOP_SKILLS_LIMIT = 30
TOTAL_STEPS = 6 # Nombre total d'étapes pour la barre de progression

def _chunk_list(data: List[Any], chunk_size: int) -> List[List[Any]]:
    """Divise une liste en sous-listes (chunks) de taille fixe."""
    return [data[i:i + chunk_size] for i in range(0, len(data), chunk_size)]

def _aggregate_results(batch_results: List[Optional[Dict]]) -> Dict[str, Any]:
    """Agrège et compte les compétences et niveaux d'études des différents lots Gemini."""
    skill_frequencies = defaultdict(int)
    education_frequencies = defaultdict(int)

    for result_batch in filter(None, batch_results):
        if 'extracted_data' in result_batch:
            for data_entry in result_batch['extracted_data']:
                unique_skills_in_description = set(s.strip() for s in data_entry.get('skills', []) if s.strip())
                for skill_name in unique_skills_in_description:
                    skill_frequencies[skill_name] += 1
                
                education_level = data_entry.get('education_level', 'Non spécifié')
                if education_level and education_level != "Non spécifié":
                    education_frequencies[education_level] += 1
    
    sorted_skills = sorted(skill_frequencies.items(), key=lambda item: item[1], reverse=True)
    top_skills = [{"skill": skill, "frequency": freq} for skill, freq in sorted_skills[:TOP_SKILLS_LIMIT]]
    top_education = max(education_frequencies, key=education_frequencies.get) if education_frequencies else "Non précisé"

    return {"skills": top_skills, "top_diploma": top_education}

async def get_skills_for_job(
    job_title: str, 
    num_offers: int, 
    logger: logging.Logger,
    progress_callback: Callable[[Dict], Awaitable[None]]
) -> Optional[Dict[str, Any]]:
    """
    Orchestre le processus complet et rapporte sa progression via un callback.
    """
    logger.info(f"--- Début du processus pour '{job_title}' ---")
    
    # --- Étape 1: Gestion du cache ---
    step_num = 1
    await progress_callback({'step': step_num, 'total': TOTAL_STEPS, 'message': 'Vérification du cache...', 'progress': step_num/TOTAL_STEPS})
    cache_key = f"{job_title.lower().strip()}@{num_offers}"
    cached_results = get_cached_results(cache_key)
    if cached_results:
        logger.info("Résultats trouvés dans le cache. Fin du processus.")
        # Simuler une progression rapide si le cache est trouvé
        await progress_callback({'step': TOTAL_STEPS, 'total': TOTAL_STEPS, 'message': 'Résultats trouvés dans le cache !', 'progress': 1.0})
        await asyncio.sleep(0.5) # Petite pause pour que l'utilisateur voie le message
        return cached_results
    logger.info("Aucun résultat en cache, poursuite de l'analyse.")

    # --- Étape 2: Initialisation des services externes ---
    step_num += 1
    await progress_callback({'step': step_num, 'total': TOTAL_STEPS, 'message': 'Initialisation de Gemini...', 'progress': step_num/TOTAL_STEPS})
    if not initialize_gemini():
        logger.critical("Échec de l'initialisation de Gemini.")
        return None

    # --- Étape 3: Récupération des données brutes ---
    step_num += 1
    await progress_callback({'step': step_num, 'total': TOTAL_STEPS, 'message': 'Recherche des offres sur France Travail...', 'progress': step_num/TOTAL_STEPS})
    ft_client = FranceTravailClient(logger=logger)
    all_offers = await ft_client.search_offers_async(job_title, max_offers=num_offers)
    
    if not all_offers:
        logger.warning("Aucune offre France Travail trouvée.")
        return None
    
    descriptions = [offer['description'] for offer in all_offers if offer.get('description')]
    if not descriptions:
        logger.warning("Aucune description d'offre exploitable trouvée.")
        return None

    # --- Étape 4: Traitement parallèle avec Gemini ---
    step_num += 1
    await progress_callback({'step': step_num, 'total': TOTAL_STEPS, 'message': f'Analyse de {len(descriptions)} descriptions...', 'progress': step_num/TOTAL_STEPS})
    description_chunks = _chunk_list(descriptions, GEMINI_BATCH_SIZE)
    tasks = [extract_skills_with_gemini(job_title, chunk) for chunk in description_chunks]
    batch_results = await asyncio.gather(*tasks)
    
    # --- Étape 5: Agrégation ---
    step_num += 1
    await progress_callback({'step': step_num, 'total': TOTAL_STEPS, 'message': 'Synthèse des compétences...', 'progress': step_num/TOTAL_STEPS})
    aggregated_data = _aggregate_results(batch_results)
    
    if not aggregated_data.get("skills"):
        logger.error("L'analyse n'a produit aucune compétence.")
        return None

    final_result = {
        "skills": aggregated_data["skills"],
        "top_diploma": aggregated_data["top_diploma"],
        "actual_offers_count": len(all_offers)
    }
    
    # --- Étape 6: Mise en cache et finalisation ---
    step_num += 1
    await progress_callback({'step': step_num, 'total': TOTAL_STEPS, 'message': 'Finalisation...', 'progress': step_num/TOTAL_STEPS})
    add_to_cache(cache_key, final_result)
    
    logger.info(f"--- Fin du processus pour '{job_title}' ---")
    return final_result