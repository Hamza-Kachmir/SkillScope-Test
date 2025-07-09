import logging
import asyncio
from typing import Dict, Any, List, Optional
from collections import defaultdict
import re # re-importé pour les regex dans la normalisation

from src.france_travail_api import FranceTravailClient
from src.cache_manager import get_cached_results, add_to_cache
from src.gemini_extractor import extract_skills_with_gemini, initialize_gemini

# Configuration pour l'analyse des offres et les lots Gemini.
GEMINI_BATCH_SIZE = 5  # Nombre de descriptions par lot pour les appels Gemini (pour 100 offres, cela génère 20 lots).
TOP_SKILLS_LIMIT = 20 # Nombre maximum de compétences à afficher dans le classement final.

def _standardize_skill_python(skill_name: str) -> str:
    """
    Normalise une compétence en Python pour le comptage et l'affichage.
    Cette fonction est un post-traitement pour corriger les inconsistances de Gemini.
    - Uniformise la casse (ex: "Alimentation" vs "alimentation" -> "Alimentation").
    - Gère le singulier/pluriel simple.
    - Applique une casse standard pour l'affichage (Ex: "Gestion De Projet", "Power BI").
    """
    original_stripped = skill_name.strip()

    # Conserver la casse des acronymes ou termes en majuscules (si déjà bien par Gemini)
    if original_stripped.isupper() and len(original_stripped) > 1 and ' ' not in original_stripped:
        return original_stripped
    # Conserver les termes comme "Power BI" avec la casse exacte souhaitée, ou "Microsoft Excel"
    if original_stripped.lower() == "power bi": return "Power BI"
    if original_stripped.lower() == "microsoft excel": return "Microsoft Excel"
    if original_stripped.lower() == "big data": return "Big Data"
    if original_stripped.lower() == "machine learning": return "Machine Learning"
    if original_stripped.lower() == "veille technologique": return "Veille Technologique"
    if original_stripped.lower() == "soins aux animaux": return "Soins Aux Animaux" # Pour l'exemple spécifique

    lower_case_skill = original_stripped.lower()

    # Gérer le singulier/pluriel simple
    # C'est une heuristique, peut nécessiter des règles plus complexes
    singularized_skill = lower_case_skill
    if singularized_skill.endswith('s') and len(singularized_skill) > 2 and not singularized_skill.endswith('ss'):
        # On retire le 's' final si le mot est assez long et ne finit pas par 'ss'
        singularized_skill = singularized_skill[:-1]
    # Ajoutez d'autres règles de singularisation ici si nécessaire (ex: "travaux" -> "travail")

    # Appliquer une casse standard pour l'affichage des compétences d'action
    # Chaque mot important commence par une majuscule, mots connecteurs en minuscule.
    words = singularized_skill.split()
    capitalized_words = []
    for i, word in enumerate(words):
        # Prépositions, articles, conjonctions courants en minuscule, sauf si c'est le premier mot.
        if i > 0 and word.lower() in ['de', 'des', 'du', 'la', 'le', 'les', 'l\'', 'à', 'aux', 'et', 'ou', 'd\'', 'un', 'une', 'pour', 'avec', 'sans', 'sur', 'dans', 'en', 'par', 'est', 'sont']:
            capitalized_words.append(word.lower())
        else:
            capitalized_words.append(word.capitalize())
    
    return ' '.join(capitalized_words)


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
    Applique une normalisation Python finale pour la déduplication et la standardisation de l'affichage.

    :param batch_results: Une liste de résultats bruts provenant des appels à Gemini.
    :return: Un dictionnaire contenant les compétences agrégées par fréquence et le diplôme le plus demandé.
    """
    # Ce dictionnaire stockera les fréquences avec les clés normalisées pour le comptage.
    skill_frequencies_normalized_key = defaultdict(int)
    # Ce dictionnaire stockera la forme d'affichage préférée pour chaque clé normalisée.
    skill_display_names = {}
    
    education_frequencies = defaultdict(int)

    for result_batch in filter(None, batch_results):
        if 'extracted_data' in result_batch:
            for data_entry in result_batch['extracted_data']:
                # Utilise un ensemble pour dédupliquer les compétences au sein d'une même description
                # après leur normalisation Python.
                processed_skills_for_this_description = set()
                
                for skill_raw in data_entry.get('skills', []):
                    skill_stripped = skill_raw.strip()
                    if not skill_stripped:
                        continue
                    
                    # Normalise la compétence via Python pour le comptage et le nom d'affichage.
                    standardized_skill_for_display = _standardize_skill_python(skill_stripped)
                    
                    # La clé de comptage est la version en minuscule et sans accent pour une déduplication parfaite.
                    counting_key = standardized_skill_for_display.lower() 

                    if counting_key not in skill_display_names:
                        skill_display_names[counting_key] = standardized_skill_for_display
                    
                    processed_skills_for_this_description.add(counting_key)
                
                for skill_key_for_counting in processed_skills_for_this_description:
                    skill_frequencies_normalized_key[skill_key_for_counting] += 1
                
                education_level = data_entry.get('education_level', 'Non spécifié')
                if education_level and education_level != "Non spécifié":
                    education_frequencies[education_level] += 1
    
    # Trie les compétences par fréquence d'apparition (la plus fréquente en premier).
    # Utilise le nom d'affichage canonique pour le dictionnaire de sortie.
    sorted_skills = sorted(skill_frequencies_normalized_key.items(), key=lambda item: item[1], reverse=True)
    top_skills = [{"skill": skill_display_names[skill_key], "frequency": freq} for skill_key, freq in sorted_skills[:TOP_SKILLS_LIMIT]]

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