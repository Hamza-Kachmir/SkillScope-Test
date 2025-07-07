import google.generativeai as genai
from google.oauth2 import service_account
import logging
import json
import os
import asyncio
import re 
from typing import Dict, Any, List
from collections import defaultdict

# --- Configuration Gemini ---
MODEL_NAME = 'gemini-1.5-flash-latest'

# --- PROMPT FORTEMENT AMÉLIORÉ ---
PROMPT_COMPETENCES = """
TA MISSION : Tu es un système expert en recrutement et en analyse sémantique pour le marché du travail français. Ton rôle est d'analyser des descriptions de postes pour en extraire les compétences techniques et le niveau d'études le plus pertinent.

CONTEXTE FOURNI :
- Titre du Poste Principal : `{titre_propre}`

RÈGLES STRICTES ET IMPÉRATIVES :
1.  **FORMAT JSON FINAL** : Le résultat doit être un unique objet JSON avec une seule clé : `"extracted_data"`, contenant une liste d'objets.
2.  **STRUCTURE PAR DESCRIPTION** : Chaque objet dans `"extracted_data"` doit avoir trois clés : `"index"`, `"skills"`, `"education_level"`.
3.  **EXTRACTION DU NIVEAU D'ÉTUDES (RÈGLE CRUCIALE)** :
    - Ton objectif est d'identifier le **niveau d'études le plus courant et réaliste** pour accéder à ce type de poste, pas nécessairement le plus élevé mentionné.
    - **Analyse comme un recruteur** : Si une annonce pour "Développeur Web" demande un "Bac+5", mais que le standard du marché est "Bac+2/Bac+3", tu dois privilégier "Bac+2 / BTS". Fais preuve de jugement.
    - **Exemples de référence** :
        - Pour "Pâtissier", "Boulanger", "Cuisinier" -> le résultat doit être "CAP / BEP".
        - Pour "Développeur Web", "Technicien supérieur" -> "Bac+2 / BTS".
        - Pour "Designer UX", "Chef de Projet junior" -> "Bac+3 / Licence".
        - Pour "Ingénieur Data", "Data Scientist" -> "Bac+5 / Master".
    - **Normalisation de la sortie** : Retourne une des valeurs suivantes : "CAP / BEP", "Bac+2 / BTS", "Bac+3 / Licence", "Bac+5 / Master", "Doctorat", "Non spécifié".
    - Si aucun diplôme n'est mentionné ou déductible, retourne "Non spécifié".
4.  **FILTRAGE DU BRUIT (COMPÉTENCES)** : Ignore le titre du poste, les diplômes, les métiers génériques et les termes comme "expérience", "maîtrise". Ils ne doivent JAMAIS apparaître dans la liste `"skills"`.
5.  **NORMALISATION DE LA CASSE (COMPÉTENCES)** : Compétences en minuscules, sauf acronymes (SQL, AWS, ETL).
6.  **NE RÉPONDS QU'AVEC DU JSON**.

EXEMPLE DE SORTIE ATTENDUE (pour "Pâtissier" et "Ingénieur Data"):
```json
{{
  "extracted_data": [
    {{
      "index": 0,
      "skills": ["pâtisserie fine", "gestion des stocks", "normes haccp"],
      "education_level": "CAP / BEP"
    }},
    {{
      "index": 1,
      "skills": ["python", "sql", "aws", "etl", "spark"],
      "education_level": "Bac+5 / Master"
    }}
  ]
}}
DESCRIPTIONS À ANALYSER (format "index: description"):
{indexed_descriptions}
"""

# Variable globale pour le modèle Gemini
model = None

def initialize_gemini():
    """
    Initialise le client Gemini en utilisant les identifiants de compte de service
    définis dans la variable d'environnement GOOGLE_CREDENTIALS.
    """
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

async def extract_skills_with_gemini(job_title: str, descriptions: List[str]) -> Dict[str, Any] | None:
    """
    Appelle l'API Gemini pour extraire les compétences et le niveau d'études
    à partir d'une liste de descriptions de postes.

    Args:
        job_title (str): Le titre principal du poste.
        descriptions (list[str]): Une liste de descriptions de postes à analyser.

    Returns:
        dict | None: Un dictionnaire JSON contenant les données extraites,
                     ou None en cas d'erreur.
    """
    if not model:
        if not initialize_gemini():
            return None

    indexed_descriptions = "\\n---\\n".join([f"{i}: {desc}" for i, desc in enumerate(descriptions)])
    prompt = PROMPT_COMPETENCES.format(titre_propre=job_title, indexed_descriptions=indexed_descriptions)

    logging.info(f"Appel à l'API Gemini pour un lot de {len(descriptions)} descriptions...")
    try:
        response = await model.generate_content_async(prompt)
        # Note: la clé principale est maintenant "extracted_data"
        skills_json = json.loads(response.text)
        logging.info("Réponse JSON de Gemini reçue et parsée avec succès pour un lot.")
        return skills_json
        
    except json.JSONDecodeError as e:
        logging.error(f"Erreur de décodage JSON de la réponse Gemini : {e}. Réponse brute: {response.text}")
        return None
    except Exception as e:
        logging.error(f"Erreur lors de l'appel à l'API Gemini : {e}")
        return None