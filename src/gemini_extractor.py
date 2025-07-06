import google.generativeai as genai
from google.oauth2 import service_account
import logging
import json
import os
import asyncio
from typing import Dict, Any, List
from collections import defaultdict

# --- Start of src/gemini_extractor.py content ---

MODEL_NAME = 'gemini-1.5-flash-latest'

PROMPT_COMPETENCES = """
TA MISSION : Tu es un système expert en analyse sémantique. Ton rôle est d'analyser la compilation de descriptions de postes fournie, d'identifier TOUTES les compétences, et de compter leur fréquence.

CONTEXTE FOURNI :
- Titre du Poste Principal : `{titre_propre}`

RÈGLES STRICTES ET IMPÉRATIVES :
1.  **FORMAT JSON FINAL** : Le résultat doit être un unique objet JSON avec une seule clé : `"skills"`, contenant une liste d'objets.
2.  **STRUCTURE DE L'OBJET COMPÉTENCE** : Chaque objet doit avoir deux clés :
    - `"skill"`: Le nom de la compétence.
    - `"frequency"`: Un nombre entier représentant sa fréquence.
3.  **FILTRAGE DU BRUIT (RÈGLE CRUCIALE)** :
    - **IGNORE IMPÉRATIVEMENT** le titre du poste principal (`{titre_propre}`) ainsi ainsi que ses variantes directes (ex: "Ingénieur de données", "Data Engineering"). Ils ne doivent JAMAIS apparaître dans la liste finale des compétences.
    - IGNORE les diplômes ("Bac+5"), les noms de métiers génériques ("technicien", "ouvrier").
4.  **NORMALISATION DE LA CASSE (RÈGLE CRUCIALE)** :
    - **Toutes les compétences retournées doivent être en minuscules**, sauf les acronymes qui doivent rester en majuscules (ex: "sql", "python", "aws", "etl", mais "anglais", "gestion de projet").
    - Regroupe les synonymes. "UI/UX Design" et "Design UX/UI" doivent être comptés ensemble sous un seul nom.
5.  **COMPTAGE EXHAUSTIF** : Tu dois compter chaque mention. Si "Python" apparaît dans 30 offres, sa fréquence doit être de 30.
6.  **TRI** : La liste finale doit être triée par fréquence, de la plus élevée à la plus basse.

EXEMPLE DE SORTIE ATTENDUE :
```json
{{
  "skills": [
    {{ "skill": "sql", "frequency": 45 }},
    {{ "skill": "python", "frequency": 42 }},
    {{ "skill": "gestion de projet", "frequency": 25 }},
    {{ "skill": "anglais", "frequency": 18 }}
  ]
}}
DESCRIPTIONS À ANALYSER :
{mega_description}
"""

model = None

def initialize_gemini():
    global model
    if model:
        return True

    google_creds_json = os.getenv('GOOGLE_CREDENTIALS')
    if not google_creds_json:
        logging.critical("La variable d'environnement GOOGLE_CREDENTIALS n'est pas définie !")
        return False
        
    try:
        credentials_info = json.loads(google_creds_json)
        credentials = service_account.Credentials.from_service_account_info(credentials_info)
        genai.configure(credentials=credentials)
        generation_config = {"temperature": 0.1, "response_mime_type": "application/json"}
        model = genai.GenerativeModel(MODEL_NAME, generation_config=generation_config)
        logging.info("Client Gemini initialisé avec succès via les variables d'environnement.")
        return True
    except Exception as e:
        logging.critical(f"Échec de l'initialisation de Gemini : {e}")
        return False

async def extract_skills_with_gemini(job_title: str, descriptions: list[str]) -> dict | None:
    if not model:
        if not initialize_gemini():
            return None

    mega_description = "\n\n---\n\n".join(descriptions)
    prompt = PROMPT_COMPETENCES.format(titre_propre=job_title, mega_description=mega_description)

    logging.info(f"Appel à l'API Gemini pour un lot de {len(descriptions)} descriptions...")
    try:
        response = await model.generate_content_async(prompt)
        skills_json = json.loads(response.text)
        logging.info("Réponse JSON de Gemini reçue et parsée avec succès pour un lot.")
        return skills_json
        
    except json.JSONDecodeError as e:
        logging.error(f"Erreur de décodage JSON de la réponse Gemini : {e}")
        return None
    except Exception as e:
        logging.error(f"Erreur lors de l'appel à l'API Gemini : {e}")
        return None

# --- End of src/gemini_extractor.py content ---

# --- Start of src/pipeline.py content (assuming FranceTravailClient and cache_manager are available) ---

# Mocking external dependencies for the purpose of consolidation.
# In a real scenario, these would be imported from their actual files.
class FranceTravailClient:
    def __init__(self, client_id, client_secret, logger):
        self.logger = logger
        self.logger.warning("FranceTravailClient is a mock in this consolidated file. It will not fetch real data.")

    async def search_offers_async(self, job_title, max_offers):
        self.logger.info(f"Mocking search for {max_offers} offers for '{job_title}'.")
        # Return some dummy data for demonstration
        return [{"description": "Description 1 for " + job_title}, {"description": "Description 2 for " + job_title}] * (max_offers // 2 if max_offers > 0 else 1)

_cache = {} # Simple in-memory mock cache
def get_cached_results(key):
    logging.info(f"Mock Cache: Getting results for key '{key}'")
    return _cache.get(key)

def add_to_cache(key, value):
    logging.info(f"Mock Cache: Adding results for key '{key}'")
    _cache[key] = value

def chunk_list(data: List[Any], chunk_size: int) -> List[List[Any]]:
    """Divise une liste en sous-listes de taille chunk_size."""
    return [data[i:i + chunk_size] for i in range(0, len(data), chunk_size)]

async def get_skills_for_job(job_title: str, num_offers: int, logger: logging.Logger) -> Dict[str, Any] | None:
    logger.info(f"--- Début du processus pour '{job_title}' avec {num_offers} offres ---")
    
    cache_key = f"{job_title.lower().strip()}@{num_offers}"
    
    logger.info(f"Étape 1 : Vérification du cache avec la clé '{cache_key}'.")
    cached_results = get_cached_results(cache_key)
    if cached_results:
        logger.info(f"Clé '{cache_key}' trouvée dans le cache. Fin du processus.")
        return cached_results
    
    logger.info(f"Clé '{cache_key}' non trouvée. Poursuite du processus d'extraction.")
    
    if not initialize_gemini():
        raise ConnectionError("Impossible d'initialiser l'API Gemini. Vérifiez les logs.")

    logger.info(f"Étape 2 : Appel à l'API France Travail pour '{job_title}'.")
    # client_id and client_secret should be passed from environment variables or a config file in a real app
    ft_client = FranceTravailClient(client_id=None, client_secret=None, logger=logger) 
    
    all_offers = await ft_client.search_offers_async(job_title, max_offers=num_offers)
    if not all_offers:
        logger.warning(f"Aucune offre France Travail trouvée. Fin du processus.")
        return None
        
    logger.info(f"{len(all_offers)} offres France Travail trouvées.")

    descriptions = [offer['description'] for offer in all_offers if offer.get('description')]
    if not descriptions:
        logger.warning("Aucune description exploitable. Fin du processus.")
        return None

    description_chunks = chunk_list(descriptions, 25)
    logger.info(f"Étape 3 : Division en {len(description_chunks)} lots pour analyse parallèle.")
    
    tasks = [extract_skills_with_gemini(job_title, chunk) for chunk in description_chunks]
    batch_results = await asyncio.gather(*tasks)
    
    logger.info("Étape 4 : Fusion des résultats...")
    final_frequencies = defaultdict(int)
    for result in batch_results:
        if result and 'skills' in result:
            for item in result['skills']:
                skill_name = item.get('skill')
                frequency = item.get('frequency', 0)
                if skill_name:
                    # CORRECTION : On normalise la clé en minuscules pour la fusion
                    normalized_skill = skill_name.strip().lower()
                    final_frequencies[normalized_skill] += frequency
    
    if not final_frequencies:
        logger.error("La fusion des résultats n'a produit aucune compétence. Fin du processus.")
        return None

    # On garde les clés en minuscules pour le stockage, on gèrera l'affichage dans app.py
    merged_skills = sorted([{"skill": skill, "frequency": freq} for skill, freq in final_frequencies.items()], key=lambda x: x['frequency'], reverse=True)
    final_result = {"skills": merged_skills}
    logger.info(f"Fusion terminée. {len(merged_skills)} compétences uniques aggrégées.")

    logger.info(f"Étape 5 : Mise en cache du résultat final avec la clé '{cache_key}'.")
    add_to_cache(cache_key, final_result)
    
    logger.info(f"--- Fin du processus pour '{job_title}' ---")
    return final_result

# --- End of src/pipeline.py content ---