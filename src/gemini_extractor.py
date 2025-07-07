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

# --- PROMPT AMÉLIORÉ ---
PROMPT_COMPETENCES = """
TA MISSION : Tu es un système expert en analyse sémantique. Ton rôle est d'analyser une liste de descriptions de postes, d'identifier les compétences et le niveau d'études requis pour CHAQUE description, et de structurer le tout en JSON.

CONTEXTE FOURNI :
- Titre du Poste Principal : `{titre_propre}`

RÈGLES STRICTES ET IMPÉRATIVES :
1.  **FORMAT JSON FINAL** : Le résultat doit être un unique objet JSON avec une seule clé : `"extracted_data"`, contenant une liste d'objets.
2.  **STRUCTURE DE L'OBJET DE CHAQUE DESCRIPTION** : Chaque objet dans `"extracted_data"` doit avoir trois clés :
    - `"index"`: L'index numérique de la description (commence à 0).
    - `"skills"`: Une liste de chaînes de caractères (compétences uniques trouvées).
    - `"education_level"`: Une chaîne de caractères représentant le plus haut niveau d'études mentionné (ex: "Bac+2", "Bac+3", "Master", "Bac+5", "Non spécifié"). Si aucun diplôme n'est mentionné, retourne "Non spécifié".
3.  **FILTRAGE DU BRUIT (COMPÉTENCES)** :
    - **IGNORE IMPÉRATIVEMENT** le titre du poste (`{titre_propre}`), ses variantes, les diplômes ("Bac+5"), les métiers génériques ("manager"), et les termes comme "expérience", "maîtrise", "technologies". Ils ne doivent JAMAIS apparaître dans la liste `"skills"`.
4.  **EXTRACTION MULTIPLE** : Si une phrase liste plusieurs compétences (ex: "Python, Java, Scala"), sépare-les.
5.  **NORMALISATION DE LA CASSE (COMPÉTENCES)** :
    - Les compétences doivent être en minuscules, sauf les acronymes courants (ex: "SQL", "AWS", "ETL", mais "anglais").
6.  **DÉDUPLICATION PAR DESCRIPTION** : Liste chaque compétence unique une seule fois par description.
7.  **NE RÉPONDS QU'AVEC DU JSON**.

EXEMPLE DE SORTIE ATTENDUE (pour deux descriptions) :
```json
{{
  "extracted_data": [
    {{
      "index": 0,
      "skills": ["sql", "python", "aws", "gestion de projet"],
      "education_level": "Bac+5"
    }},
    {{
      "index": 1,
      "skills": ["java", "spring", "microservices", "anglais"],
      "education_level": "Bac+3"
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