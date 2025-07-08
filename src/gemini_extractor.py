import google.generativeai as genai
from google.oauth2 import service_account
import logging
import json
import os
import asyncio
from typing import Dict, Any, List, Optional

# --- Constantes de configuration Gemini ---
MODEL_NAME = 'gemini-1.5-flash-latest'
PROMPT_FILE_PATH = os.path.join(os.path.dirname(__file__), '..', 'prompt.md')

# --- État global du module ---
model: Optional[genai.GenerativeModel] = None
prompt_template: Optional[str] = None

def _load_prompt_from_file() -> Optional[str]:
    """Charge le template du prompt depuis le fichier prompt.md."""
    try:
        with open(PROMPT_FILE_PATH, 'r', encoding='utf-8') as f:
            logging.info(f"Prompt chargé avec succès depuis '{PROMPT_FILE_PATH}'.")
            return f.read()
    except FileNotFoundError:
        logging.critical(f"Fichier de prompt non trouvé à l'emplacement '{PROMPT_FILE_PATH}' !")
        return None
    except Exception as e:
        logging.critical(f"Erreur lors de la lecture du fichier de prompt : {e}")
        return None

def initialize_gemini() -> bool:
    """
    Initialise le client Gemini et charge le prompt.
    Doit être appelée avant toute tentative d'extraction.

    :return: True si l'initialisation est réussie, sinon False.
    """
    global model, prompt_template
    if model and prompt_template:
        return True

    # Charger le prompt une seule fois
    if not prompt_template:
        prompt_template = _load_prompt_from_file()
        if not prompt_template:
            return False

    # Initialiser le modèle si ce n'est pas déjà fait
    if not model:
        google_creds_json = os.getenv('GOOGLE_CREDENTIALS')
        if not google_creds_json:
            logging.critical("La variable d'environnement GOOGLE_CREDENTIALS n'est pas définie !")
            return False
            
        try:
            credentials_info = json.loads(google_creds_json)
            credentials = service_account.Credentials.from_service_account_info(credentials_info)
            genai.configure(credentials=credentials)
            
            # La température à 0.0 rend les réponses déterministes et moins "créatives"
            generation_config = {"temperature": 0.0, "response_mime_type": "application/json"}
            model = genai.GenerativeModel(MODEL_NAME, generation_config=generation_config)
            logging.info(f"Client Gemini '{MODEL_NAME}' initialisé avec succès.")
        except Exception as e:
            logging.critical(f"Échec de l'initialisation de Gemini : {e}")
            return False
    
    return True

async def extract_skills_with_gemini(job_title: str, descriptions: List[str]) -> Optional[Dict[str, Any]]:
    """
    Envoie un lot de descriptions de postes à l'API Gemini pour extraction.

    :param job_title: Le titre du métier (utilisé pour le contexte, mais pas dans le prompt actuel).
    :param descriptions: Une liste de descriptions de postes à analyser.
    :return: Un dictionnaire contenant les données extraites, ou None en cas d'erreur.
    """
    if not model or not prompt_template:
        logging.error("Tentative d'appel à Gemini sans initialisation préalable.")
        if not initialize_gemini():
            return None

    # Formater les descriptions pour les inclure dans le prompt
    indexed_descriptions = "\n---\n".join([f"{i}: {desc}" for i, desc in enumerate(descriptions)])
    full_prompt = prompt_template.format(indexed_descriptions=indexed_descriptions)

    logging.info(f"Appel à l'API Gemini pour un lot de {len(descriptions)} descriptions...")
    try:
        # L'appel asynchrone est crucial pour la performance
        response = await model.generate_content_async(full_prompt)
        
        # Le nettoyage simple des backslashes peut aider à corriger des JSON malformés
        cleaned_text = response.text.replace(r"\'", "'")
        skills_json = json.loads(cleaned_text)
        
        logging.info(f"Réponse JSON de Gemini reçue et parsée avec succès pour un lot de {len(descriptions)} offres.")
        return skills_json
        
    except json.JSONDecodeError as e:
        logging.error(f"Erreur de décodage JSON de la réponse Gemini. Erreur: {e}. Réponse brute reçue : {response.text[:500]}...")
        return None
    except Exception as e:
        logging.error(f"Erreur inattendue lors de l'appel à l'API Gemini : {e}")
        return None