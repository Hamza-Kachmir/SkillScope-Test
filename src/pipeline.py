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

# Configuration pour l'analyse des offres et les lots Gemini.
GEMINI_BATCH_SIZE = 5
TOP_SKILLS_LIMIT = 20

def _chunk_list(data: List[Any], chunk_size: int) -> List[List[Any]]:
    """
    Divise une liste en sous-listes (chunks) de taille fixe pour le traitement par lots.
    """
    return [data[i:i + chunk_size] for i in range(0, len(data), chunk_size)]

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
    recherche d'offres d'emploi, filtrage par titre, extraction via Gemini (avec normalisation intégrée)
    et agrégation des résultats.
    """
    logger.info(f"Début du processus pour '{job_title}' ({num_offers} offres initiales demandées).")

    cache_key = f"{job_title}@{num_offers}"
    cached_results = get_cached_results(cache_key)
    if cached_results:
        logger.info(f"Résultats trouvés dans le cache pour '{cache_key}'. Fin du processus.")
        return cached_results
    logger.info(f"Aucun résultat en cache pour '{cache_key}', poursuite de l'analyse.")

    if not initialize_gemini(logger):
        logger.critical("Échec de l'initialisation de Gemini; abandon du processus.")
        return None

    logger.info(f"Appel à l'API France Travail pour '{job_title}'.")
    ft_client = FranceTravailClient(logger=logger)
    # Demande plus d'offres pour avoir une base plus large avant filtrage
    all_offers_raw = await ft_client.search_offers_async(job_title, max_offers=max(num_offers, 200)) # Demande au moins 200 pour un meilleur filtrage

    if not all_offers_raw:
        logger.warning("Aucune offre France Travail trouvée; fin du processus.")
        return None

    # --- NOUVEAU : Filtrage des offres par intitulé ---
    filtered_offers = []
    # Termes à rechercher dans le titre pour considérer l'offre comme pertinente
    # Utilisez une liste de mots-clés plus ouverts pour éviter de manquer des variantes.
    # Exemple: 'data engineer', 'ingénieur data', 'data ingenieur', 'data dev' etc.
    # C'est une liste à ajuster selon la qualité des titres de France Travail.
    relevant_title_keywords = [
        _normalize_search_term(job_title), # Le terme de recherche original
        'data engineer', 'ingénieur data', 'ingénieur big data', 'architecte data',
        'data scientist', 'machine learning engineer', 'développeur data'
    ]
    # Supprimer les doublons et les vides
    relevant_title_keywords = list(set([k for k in relevant_title_keywords if k]))

    # Compteur pour s'arrêter à num_offers offres pertinentes
    offers_count_for_analysis = 0

    for offer in all_offers_raw:
        title_lower = _normalize_search_term(offer.get('titre', ''))
        description_text = offer.get('description', '')

        # Condition de pertinence basée sur le titre et la présence d'une description
        is_relevant = False
        for keyword in relevant_title_keywords:
            if keyword in title_lower:
                is_relevant = True
                break
        
        # S'assurer que la description n'est pas vide pour l'analyse
        if is_relevant and description_text:
            filtered_offers.append(offer)
            offers_count_for_analysis += 1
        
        # Arrêter si nous avons atteint le nombre d'offres désiré pour l'analyse
        if offers_count_for_analysis >= num_offers:
            break

    if not filtered_offers:
        logger.warning(f"Après filtrage par titre ({relevant_title_keywords}), aucune offre pertinente trouvée pour '{job_title}'; fin du processus.")
        return None

    # Préparer les données pour Gemini, incluant titre et description
    descriptions_for_gemini = [{'titre': offer['titre'], 'description': offer['description']} for offer in filtered_offers]
    
    logger.info(f"Initialement {len(all_offers_raw)} offres de France Travail. {len(filtered_offers)} offres retenues après filtrage par titre (cible: {num_offers}).")


    # Division des descriptions (avec titres) en lots pour un traitement parallèle par Gemini.
    description_chunks = _chunk_list(descriptions_for_gemini, GEMINI_BATCH_SIZE)
    logger.info(f"Division des offres retenues en {len(description_chunks)} lots pour analyse parallèle (Extraction & Normalisation).")

    # Exécute les appels à Gemini en parallèle.
    tasks = [extract_skills_with_gemini(job_title, chunk, logger) for chunk in description_chunks]
    extraction_batch_results = await asyncio.gather(*tasks)

    logger.info("Fusion et comptage des résultats de tous les lots Gemini (compétences déjà normalisées)...")
    aggregated_data = _aggregate_final_results(extraction_batch_results)

    if not aggregated_data.get("skills"):
        logger.error("L'analyse n'a produit aucune compétence; fin du processus.")
        return None

    final_result = {
        "skills": aggregated_data["skills"],
        "top_diploma": aggregated_data["top_diploma"],
        "actual_offers_count": len(filtered_offers) # Compte les offres réellement ANALYSÉES après filtrage
    }

    logger.info(f"Un total de {len(final_result['skills'])} compétences uniques et le diplôme le plus demandé ('{final_result['top_diploma']}') ont été agrégés.")

    logger.info(f"Mise en cache du résultat final avec la clé '{cache_key}'.")
    add_to_cache(cache_key, final_result)

    logger.info(f"Fin du processus pour '{job_title}'.")
    return final_result

# Fonction utilitaire pour normaliser les termes de recherche (réutilisée du app.py)
def _normalize_search_term(term: str) -> str:
    """
    Normalise une chaîne de caractères pour une utilisation cohérente (minuscule, sans accent).
    """
    normalized_term = unicodedata.normalize('NFKD', term)
    normalized_term = normalized_term.encode('ascii', 'ignore').decode('utf-8').lower().strip()
    return normalized_term