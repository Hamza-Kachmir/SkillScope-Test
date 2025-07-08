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
_current_logger: logging.Logger = logging.getLogger(__name__) 


def _load_prompt_from_file() -> Optional[str]:
    """Charge le template du prompt depuis le fichier prompt.md."""
    try:
        with open(PROMPT_FILE_PATH, 'r', encoding='utf-8') as f:
            _current_logger.info(f"Gemini : Prompt chargé avec succès depuis '{PROMPT_FILE_PATH}'.") 
            return f.read()
    except FileNotFoundError:
        _current_logger.critical(f"Gemini : Fichier de prompt non trouvé à l'emplacement '{PROMPT_FILE_PATH}' !")
        return None
    except Exception as e:
        _current_logger.critical(f"Gemini : Erreur lors de la lecture du fichier de prompt : {e}")
        return None

def initialize_gemini(logger: logging.Logger) -> bool: 
    """
    Initialise le client Gemini et charge le prompt.
    Doit être appelée avant toute tentative d'extraction.

    :param logger: L'instance de logger à utiliser pour les messages.
    :return: True si l'initialisation est réussie, sinon False.
    """
    global model, prompt_template, _current_logger
    _current_logger = logger # Définit le logger à utiliser pour ce module

    if model and prompt_template:
        return True

    if not prompt_template:
        prompt_template = _load_prompt_from_file()
        if not prompt_template:
            return False

    if not model:
        google_creds_json = os.getenv('GOOGLE_CREDENTIALS')
        if not google_creds_json:
            _current_logger.critical("Gemini : La variable d'environnement GOOGLE_CREDENTIALS n'est pas définie !")
            return False
            
        try:
            credentials_info = json.loads(google_creds_json)
            credentials = service_account.Credentials.from_service_account_info(credentials_info)
            genai.configure(credentials=credentials)
            
            generation_config = {"temperature": 0.0, "response_mime_type": "application/json"}
            model = genai.GenerativeModel(MODEL_NAME, generation_config=generation_config)
            _current_logger.info(f"Gemini : Client '{MODEL_NAME}' initialisé avec succès.")
        except Exception as e:
            _current_logger.critical(f"Gemini : Échec de l'initialisation : {e}")
            return False
    
    return True

async def extract_skills_with_gemini(job_title: str, descriptions: List[str], logger: logging.Logger) -> Optional[Dict[str, Any]]:
    """
    Envoie un lot de descriptions de postes à l'API Gemini pour extraction.

    :param job_title: Le titre du métier (utilisé pour le contexte, mais pas dans le prompt actuel).
    :param descriptions: Une liste de descriptions de postes à analyser.
    :param logger: L'instance de logger à utiliser pour les messages.
    :return: Un dictionnaire contenant les données extraites, ou None en cas d'erreur.
    """
    global _current_logger
    _current_logger = logger # S'assure que ce logger est utilisé pour les appels de log suivants

    if not model or not prompt_template:
        _current_logger.error("Gemini : Tentative d'appel à Gemini sans initialisation préalable.")
        if not initialize_gemini(logger):
            return None

    indexed_descriptions = "\n---\n".join([f"{i}: {desc}" for i, desc in enumerate(descriptions)])
    full_prompt = prompt_template.format(indexed_descriptions=indexed_descriptions)

    _current_logger.info(f"Gemini : Envoi de {len(descriptions)} descriptions au modèle (lot pour '{job_title}')...") 
    try:
        response = await model.generate_content_async(full_prompt)
        
        cleaned_text = response.text.replace(r"\'", "'")
        skills_json = json.loads(cleaned_text)
        
        _current_logger.info(f"Gemini : Réponse JSON reçue et parsée avec succès pour ce lot ({len(descriptions)} descriptions).")
        return skills_json
        
    except json.JSONDecodeError as e:
        _current_logger.error(f"Gemini : Erreur de décodage JSON de la réponse. Erreur: {e}. Réponse brute reçue : {response.text[:500]}...")
        return None
    except Exception as e:
        _current_logger.error(f"Gemini : Erreur inattendue lors de l'appel à l'API : {e}")
        return None