# src/gemini_extractor.py

import google.generativeai as genai
from google.oauth2 import service_account
import logging
import json
import os

MODEL_NAME = 'gemini-1.5-pro-latest'

PROMPT_COMPETENCES = """
TA MISSION : Tu es un système expert en analyse sémantique pour une base de données de compétences nommée "WikiSkills". Ton rôle est d'analyser une description de poste et d'en extraire les compétences (savoir-faire, savoir-être, langues) avec une précision absolue pour garantir une donnée finale propre, normalisée et sans aucun bruit.

CONTEXTE FOURNI :
- Titre du Poste à Ignorer : `{titre_propre}`

RÈGLES STRICTES ET IMPÉRATIVES :
1. FORMAT JSON : Le résultat doit être un unique objet JSON valide avec les clés "hard_skills", "soft_skills", et "languages". Tous les guillemets dans les compétences doivent être échappés (\\").
2. CATÉGORISATION STRICTE : Les compétences manuelles pratiques (ex: 'Bricolage', 'Soudure', 'Mécanique') doivent TOUJOURS être classées en `hard_skills`.
3. FILTRAGE INTELLIGENT DU BRUIT :
    - IGNORE le titre de poste principal (`{titre_propre}`) et ses variantes.
    - IGNORE les noms de métiers génériques (ex: 'agent', 'ouvrier', 'technicien') s'ils sont utilisés seuls.
    - IGNORE tous les diplômes et niveaux d'étude (ex: "Bac+5", "DEC").
4. GESTION AVANCÉE DES ACRONYMES ET PARENTHÈSES :
    - Si un acronyme est expliqué (ex: "MCO (Maintenance en Condition Opérationnelle)"), extrais uniquement la version longue.
    - Si une parenthèse précise un outil (ex: "CRM (Salesforce)"), extrais uniquement l'outil.
    - Si une parenthèse liste des exemples (ex: "Gestion de projet (planning, budget)"), décompose-la en compétences distinctes.
5. NORMALISATION ET DÉDUPLICATION :
    - Ne produis aucun doublon.
    - Normalise les compétences synonymes ou permutées (ex: "DESIGN UI/UX" et "DESIGN UX/UI" doivent tous les deux devenir ["UI/UX Design"]).

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
        logging.critical(f"Échec de l'initialisation de Gemini à partir des variables d'environnement : {e}")
        return False

async def extract_skills_with_gemini(job_title: str, descriptions: list[str]) -> dict | None:
    if not model:
        if not initialize_gemini():
            return None

    mega_description = "\n\n---\n\n".join(descriptions)
    prompt = PROMPT_COMPETENCES.format(titre_propre=job_title, mega_description=mega_description)
    
    logging.info(f"Appel à l'API Gemini pour le métier '{job_title}'...")
    try:
        response = await model.generate_content_async(prompt)
        skills_json = json.loads(response.text)
        
        return {
            "hard_skills": skills_json.get('hard_skills', []),
            "soft_skills": skills_json.get('soft_skills', []),
            "languages": skills_json.get('languages', [])
        }
        
    except json.JSONDecodeError as e:
        logging.error(f"Erreur de décodage JSON de la réponse Gemini : {e}")
        return None
    except Exception as e:
        logging.error(f"Erreur lors de l'appel à l'API Gemini : {e}")
        return None