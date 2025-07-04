import requests
import logging
import os

ESCO_API_URL = "https://ec.europa.eu/esco/api/search"
VALIDATION_CACHE = {}
CACHE_FILE = "esco_skills.json"

def is_skill_valid(skill_name: str) -> bool:
    if not skill_name or len(skill_name) < 3:
        return False
        
    normalized_skill = skill_name.lower()
    if normalized_skill in VALIDATION_CACHE:
        return VALIDATION_CACHE[normalized_skill]

    params = {
        "type": "skill",
        "language": "fr",
        "text": normalized_skill
    }
    
    try:
        response = requests.get(ESCO_API_URL, params=params, timeout=5)
        response.raise_for_status()
        data = response.json()
        
        is_valid = data.get('total', 0) > 0
        VALIDATION_CACHE[normalized_skill] = is_valid
        return is_valid
        
    except requests.exceptions.RequestException:
        VALIDATION_CACHE[normalized_skill] = False
        return False

def clear_esco_cache():
    logging.warning("Effacement du cache de validation en mémoire.")
    VALIDATION_CACHE.clear()
    
    if os.path.exists(CACHE_FILE):
        logging.warning(f"Suppression de l'ancien fichier cache : {CACHE_FILE}")
        os.remove(CACHE_FILE)
        return True
    return False