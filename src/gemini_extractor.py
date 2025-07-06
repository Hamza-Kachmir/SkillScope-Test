import google.generativeai as genai
from google.oauth2 import service_account
import logging
import json
import os

MODEL_NAME = 'gemini-1.5-flash-latest'

PROMPT_COMPETENCES = """
TA MISSION : Tu es un système expert en analyse sémantique pour une base de données de compétences. Ton rôle est d'analyser la compilation de descriptions de postes fournie ci-dessous, d'identifier TOUTES les compétences (hard skills, soft skills, langues), et de compter la fréquence d'apparition de chacune.

CONTEXTE FOURNI :
- Titre du Poste Principal (à ignorer si trouvé comme compétence) : `{titre_propre}`

RÈGLES STRICTES ET IMPÉRATIVES :
1.  **FORMAT JSON FINAL** : Le résultat doit être un unique objet JSON. Cet objet doit contenir une seule clé : `"skills"`. La valeur de cette clé doit être une **liste d'objets**.
2.  **STRUCTURE DE L'OBJET COMPÉTENCE** : Chaque objet dans la liste doit avoir exactement deux clés :
    - `"skill"`: Le nom de la compétence, normalisé et nettoyé. (ex: "Gestion de projet", "Python", "Anglais").
    - `"frequency"`: Un **nombre entier** représentant combien de fois cette compétence ou ses synonymes directs ont été détectés dans l'ensemble du texte.
3.  **COMPTAGE EXHAUSTIF** : Tu dois compter chaque mention. Si "Python" apparaît dans 30 offres différentes, sa fréquence doit être de 30.
4.  **NORMALISATION** : Regroupe les synonymes. "UI/UX Design" et "Design UX/UI" doivent être comptés ensemble sous un seul nom, par exemple "UI/UX Design".
5.  **FILTRAGE DU BRUIT** : Ignore les diplômes ("Bac+5"), les noms de métiers génériques ("technicien", "ouvrier") et le titre de poste principal (`{titre_propre}`).
6.  **TRI** : La liste finale de compétences doit être triée par fréquence, de la plus élevée à la plus basse.

EXEMPLE DE SORTIE ATTENDUE :
```json
{{
  "skills": [
    {{ "skill": "SQL", "frequency": 45 }},
    {{ "skill": "Python", "frequency": 42 }},
    {{ "skill": "Gestion de projet", "frequency": 25 }},
    {{ "skill": "Anglais", "frequency": 18 }}
  ]
}}


DESCRIPTION À ANALYSER :
---
{mega_description}
---
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