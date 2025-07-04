import requests
import json
import logging
import os

CACHE_FILE = "esco_skills.json"
ESCO_API_URL = "https://ec.europa.eu/esco/api/search"

def _fetch_all_esco_skills() -> list[str]:
    skills = set()
    offset = 0
    limit = 1000 
    
    logging.info("Début du téléchargement des compétences depuis l'API ESCO...")
    
    while True:
        params = {
            "type": "skill",
            "language": "fr",
            "limit": limit,
            "offset": offset
        }
        try:
            response = requests.get(ESCO_API_URL, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            results = data.get('_embedded', {}).get('results', [])
            if not results:
                break
            
            for skill in results:
                skills.add(skill['preferredLabel'])
            
            logging.info(f"{len(skills)} compétences téléchargées...")
            
            if len(results) < limit:
                break
            
            offset += limit
            
        except requests.exceptions.RequestException as e:
            logging.error(f"Erreur lors de l'appel à l'API ESCO : {e}")
            break
            
    logging.info(f"Téléchargement terminé. Total de {len(skills)} compétences uniques.")
    return sorted(list(skills))

def get_esco_skills() -> list[str]:
    if os.path.exists(CACHE_FILE):
        logging.info(f"Chargement des compétences depuis le fichier cache : {CACHE_FILE}")
        with open(CACHE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    else:
        logging.info("Le fichier cache n'existe pas. Appel à l'API ESCO.")
        skills = _fetch_all_esco_skills()
        if skills:
            logging.info(f"Sauvegarde de {len(skills)} compétences dans {CACHE_FILE}.")
            with open(CACHE_FILE, 'w', encoding='utf-8') as f:
                json.dump(skills, f, ensure_ascii=False, indent=2)
        return skills