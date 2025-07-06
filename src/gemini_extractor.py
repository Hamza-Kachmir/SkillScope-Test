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
