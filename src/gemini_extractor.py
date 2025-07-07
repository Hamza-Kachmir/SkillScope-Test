import google.generativeai as genai
from google.oauth2 import service_account
import logging
import json
import os
import asyncio
import re # Import re for splitting
from typing import Dict, Any, List
from collections import defaultdict

MODEL_NAME = 'gemini-1.5-flash-latest'

# MODIFIED PROMPT
PROMPT_COMPETENCES = """
TA MISSION : Tu es un système expert en analyse sémantique. Ton rôle est d'analyser la liste de descriptions de postes fournie, d'identifier TOUTES les compétences pertinentes pour CHAQUE DESCRIPTION, et de les lister.

CONTEXTE FOURNI :
- Titre du Poste Principal : `{titre_propre}`

RÈGLES STRICTES ET IMPÉRATIVES :
1.  **FORMAT JSON FINAL** : Le résultat doit être un unique objet JSON avec une seule clé : `"extracted_skills"`, contenant une liste d'objets. Chaque objet de cette liste représente une description analysée.
2.  **STRUCTURE DE L'OBJET DE CHAQUE DESCRIPTION** : Chaque objet dans `"extracted_skills"` doit avoir deux clés :
    - `"index"`: L'index numérique de la description dans la liste fournie (commence à 0).
    - `"skills"`: Une liste de chaînes de caractères, où chaque chaîne est une compétence unique trouvée dans cette description.
3.  **FILTRAGE DU BRUIT (RÈGLE CRUCIALE)** :
    - **IGNORE IMPÉRATIVEMENT** le titre du poste principal (`{titre_propre}`) ainsi que ses variantes directes (ex: "Ingénieur de données", "Data Engineering"). Ils ne doivent JAMAIS apparaître dans la liste finale des compétences.
    - IGNORE les diplômes ("Bac+5", "Master"), les noms de métiers génériques ("technicien", "ouvrier", "manager"), et les termes génériques comme "expérience", "connaissance", "maîtrise", "compétences", "technologies".
4.  **EXTRACTION MULTIPLE D'UNE SEULE PHRASE** : Si une phrase liste plusieurs compétences (ex: "Python, Java, Scala" ou "Adobe (Photoshop, Illustrator)"), **sépare-les en compétences individuelles distinctes**. Pour "Adobe (Photoshop, Illustrator)", extrait "Photoshop" et "Illustrator".
5.  **NORMALISATION DE LA CASSE** :
    - **Toutes les compétences retournées doivent être en minuscules**, sauf les acronymes qui doivent rester en majuscules (ex: "SQL", "Python", "AWS", "ETL", mais "anglais", "gestion de projet"). C'est à toi de reconnaître les acronymes courants.
6.  **DÉDUPLICATION PAR DESCRIPTION** : Pour chaque description, liste chaque compétence trouvée **une seule fois**, même si elle est mentionnée plusieurs fois dans cette description.
7.  **NE RÉPONDS QU'AVEC DU JSON**.

EXEMPLE DE SORTIE ATTENDUE (pour deux descriptions) :
```json
{{
  "extracted_skills": [
    {{
      "index": 0,
      "skills": ["sql", "python", "aws", "gestion de projet"]
    }},
    {{
      "index": 1,
      "skills": ["java", "spring", "microservices", "anglais"]
    }}
  ]
}}
DESCRIPTIONS À ANALYSER (format "index: description"):
{indexed_descriptions}
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

    # We need to send indexed descriptions for Gemini to return indexed skills
    indexed_descriptions = "\n---\n".join([f"{i}: {desc}" for i, desc in enumerate(descriptions)])
    prompt = PROMPT_COMPETENCES.format(titre_propre=job_title, indexed_descriptions=indexed_descriptions)

    logging.info(f"Appel à l'API Gemini pour un lot de {len(descriptions)} descriptions...")
    try:
        response = await model.generate_content_async(prompt)
        skills_json = json.loads(response.text)
        logging.info("Réponse JSON de Gemini reçue et parsée avec succès pour un lot.")
        return skills_json
        
    except json.JSONDecodeError as e:
        logging.error(f"Erreur de décodage JSON de la réponse Gemini : {e}. Réponse brute: {response.text}")
        return None
    except Exception as e:
        logging.error(f"Erreur lors de l'appel à l'API Gemini : {e}")
        return None