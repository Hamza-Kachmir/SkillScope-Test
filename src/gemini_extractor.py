import google.generativeai as genai
from google.oauth2 import service_account
import logging
import json
import os
import asyncio
from typing import Dict, Any, List

MODEL_NAME = 'gemini-1.5-flash-latest'

PROMPT_COMPETENCES = """
## MISSION
Tu es un système expert en extraction de données pour le marché du travail. Ta mission est d'analyser des descriptions de postes avec une précision chirurgicale pour en extraire les compétences techniques (`skills`) et le niveau d'études (`education_level`). Tu dois te comporter comme un analyseur sémantique déterministe qui suit les règles à la lettre.

## RÈGLES IMPÉRATIVES DE FORMATAGE DE SORTIE
1.  **Format JSON Unique** : La sortie doit être un unique objet JSON valide contenant une seule clé principale : `"extracted_data"`.
2.  **Liste d'Objets** : La valeur de `"extracted_data"` doit être une liste d'objets. Chaque objet représente une des descriptions de poste analysées.
3.  **Structure de l'Objet** : Chaque objet dans la liste doit impérativement contenir trois clés : `"index"` (l'index de la description originale), `"skills"` (une liste de chaînes de caractères), et `"education_level"` (une unique chaîne de caractères).

## RÈGLES D'EXTRACTION DES COMPÉTENCES (skills)
1.  **Filtre Strict** : Ignore et exclus systématiquement les soft skills (ex: rigueur, autonomie, communication), les termes génériques (ex: expérience, maîtrise, connaissance), les titres de postes et les diplômes.
2.  **Normalisation et Consolidation** :
    * Regroupe toutes les variations d'une même compétence sous un seul nom standard.
    * Exemples : ["power bi", "PowerBI", "power-bi"] -> "Power BI"; ["js", "javascript"] -> "JavaScript"; ["a.w.s", "amazon web services"] -> "AWS".
3.  **Gestion de la Casse (Capitalisation)** :
    * **Acronymes** : Toujours en majuscules (ex: SQL, AWS, GCP, API, SDK, CRM, ERP).
    * **Noms Propres de Technologies** : Utilise la casse standard de l'industrie (ex: Python, JavaScript, React, Docker, Power BI, TensorFlow).
    * **Compétences Générales** : Met une majuscule au premier mot (ex: "Gestion de projet", "Comptabilité analytique", "Pâtisserie fine").

## RÈGLES D'EXTRACTION DU NIVEAU D'ÉTUDES (education_level)
1.  **Priorité Absolue au Texte** : Ton analyse doit se baser **exclusivement et uniquement** sur le texte de la description fournie.
2.  **Aucune Inférence** : N'infère, ne devine, ou n'utilise JAMAIS tes connaissances externes sur le marché du travail pour déterminer le niveau d'études. Si le texte ne mentionne aucun diplôme ou niveau d'études, tu DOIS retourner la valeur "Non spécifié".
3.  **Agrégation Logique** : Si plusieurs niveaux sont mentionnés, retourne celui qui semble le plus exigé ou le plus fréquent. En cas d'ambiguïté, une fourchette est acceptable (ex: "Bac+3 à Bac+5").
4.  **Catégories de Sortie Autorisées** : Tu dois retourner **OBLIGATOIREMENT** l'une des valeurs suivantes, et aucune autre :
    * "CAP / BEP"
    * "Bac"
    * "Bac+2 / BTS"
    * "Bac+3 / Licence"
    * "Bac+5 / Master"
    * "Doctorat"
    * "Formation spécifique"
    * "Non spécifié"

## EXEMPLE COMPLET DE SORTIE ATTENDUE
```json
{{
  "extracted_data": [
    {{
      "index": 0,
      "skills": ["Python", "SQL", "AWS", "ETL", "Spark", "Power BI"],
      "education_level": "Bac+5 / Master"
    }},
    {{
      "index": 1,
      "skills": ["Vente B2B", "Négociation commerciale", "CRM"],
      "education_level": "Bac+2 / BTS"
    }},
    {{
      "index": 2,
      "skills": ["Pâtisserie fine", "Gestion des stocks", "Normes HACCP"],
      "education_level": "Non spécifié"
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
        generation_config = {"temperature": 0.0, "response_mime_type": "application/json"}
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
    prompt = PROMPT_COMPETENCES.format(indexed_descriptions=indexed_descriptions)

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