import google.generativeai as genai
from google.oauth2 import service_account
import logging
import json
import os
import asyncio
from typing import Dict, Any, List

MODEL_NAME = 'gemini-1.5-flash-latest'

PROMPT_COMPETENCES = """
MISSION : Tu es un système expert en recrutement et en analyse sémantique pour le marché du travail français. Ton rôle est d'analyser méticuleusement des descriptions de postes pour en extraire les compétences techniques et le niveau d'études requis le plus pertinent.

## RÈGLES D'EXTRACTION (STRICTES ET IMPÉRATIVES)

1.  **FORMAT DE SORTIE** : Tu dois retourner un unique objet JSON avec une seule clé : `"extracted_data"`, qui contient une liste d'objets. Chaque objet représente une description de poste.

2.  **STRUCTURE PAR DESCRIPTION** : Chaque objet dans la liste `"extracted_data"` doit contenir trois clés : `"index"`, `"skills"`, `"education_level"`.

3.  **EXTRACTION DES COMPÉTENCES ("skills")** :
    * **NORMALISATION LOGIQUE** : Chaque compétence doit être retournée sous sa forme canonique et la plus correcte possible. Fais preuve de jugement pour la casse.
    * **FILTRAGE DU BRUIT** : Ignore les termes génériques ("expérience", "maîtrise", "rigueur"), les soft skills, les diplômes et les titres de postes. Ils ne doivent JAMAIS apparaître dans la liste `skills`.

4.  **EXTRACTION DU NIVEAU D'ÉTUDES ("education_level")** :
    * **PRIORITÉ AU TEXTE** : Ta réponse DOIT se baser **en priorité absolue** sur les diplômes mentionnés dans les descriptions fournies.
    * **LOGIQUE D'AGRÉGATION** : S'il y a plusieurs niveaux mentionnés (ex: Bac+2 et Bac+5), retourne le plus fréquent. S'il n'y a pas de majorité claire, retourne une fourchette réaliste (ex: "Bac+2 à Bac+5").
    * **INFERENCE LIMITÉE** : N'infère un niveau standard du marché que si **AUCUN DIPLÔME** n'est mentionné dans le texte.
    * **CATÉGORIES DE SORTIE** : Retourne **uniquement** une des valeurs suivantes : "CAP / BEP", "Bac", "Bac+2 / BTS", "Bac+3 / Licence", "Bac+5 / Master", "Doctorat", "Concours / Formation spécifique", "Non spécifié".

## EXEMPLES DE NORMALISATION (À APPLIQUER SYSTÉMATIQUEMENT)
- "power bi", "powerbi", "PowerBI" -> "Power BI"
- "piton", "phyton" -> "Python"
- "js", "javascript" -> "JavaScript"
- "amazon web services", "a.w.s" -> "AWS"
- "react js", "react.js" -> "React"
- "sql server", "ssms" -> "SQL Server"
- "csharp", "c#" -> "C#"

## EXEMPLE DE SORTIE ATTENDUE
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
      "skills": ["Python", "SQL", "AWS", "ETL", "Spark", "Power BI"],
      "education_level": "Bac+5 / Master"
    }},
    {{
      "index": 2,
      "skills": ["secourisme", "gestion du stress", "permis poids lourd"],
      "education_level": "Concours / Formation spécifique"
    }}
  ]
}}
DESCRIPTIONS À ANALYSER CI-DESSOUS (format "index: description"):
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
async def extract_skills_with_gemini(job_title: str, descriptions: List[str]) -> Dict[str, Any] | None:
    if not model:
        if not initialize_gemini():
            return None

    indexed_descriptions = "\\n---\\n".join([f"{i}: {desc}" for i, desc in enumerate(descriptions)])
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