import google.generativeai as genai 
from google.oauth2 import service_account
import logging
import json
import os
import asyncio
from typing import Dict, Any, List, Optional, AsyncIterable
import vertexai 
from vertexai.preview.generative_models import GenerativeModel, Part 

# Constantes de configuration Gemini.
MODEL_NAME = 'gemini-1.5-flash-latest'
PROMPT_FILE_PATH = os.path.join(os.path.dirname(__file__), '..', 'prompt.md')

# Variables globales pour stocker le modèle Gemini et le template de prompt.
model: Optional[GenerativeModel] = None 
prompt_template: Optional[str] = None
_current_logger: logging.Logger = logging.getLogger(__name__) 

# Constantes de configuration pour Vertex AI.
PROJECT_ID = os.getenv('GCP_PROJECT_ID') 
LOCATION = os.getenv('GCP_LOCATION', 'us-central1') 


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
    Initialise le client Gemini via Vertex AI et charge le prompt.
    Cette fonction doit être appelée avant toute tentative d'extraction.

    :param logger: L'instance de logger à utiliser pour les messages de ce module.
    :return: True si l'initialisation est réussie, sinon False.
    """
    global model, prompt_template, _current_logger
    _current_logger = logger 

    if model and prompt_template:
        return True

    if not prompt_template:
        prompt_template = _load_prompt_from_file()
        if not prompt_template:
            return False

    if not model:
        if not PROJECT_ID:
            _current_logger.critical("Gemini : La variable d'environnement GCP_PROJECT_ID n'est pas définie !")
            return False

        try:
            vertexai.init(project=PROJECT_ID, location=LOCATION)
            
            generation_config = {"temperature": 0.0}
            
            model = GenerativeModel(MODEL_NAME, generation_config=generation_config)
            _current_logger.info(f"Gemini : Client '{MODEL_NAME}' initialisé avec succès via Vertex AI (Projet: {PROJECT_ID}, Région: {LOCATION}).")
            return True
        except Exception as e:
            _current_logger.critical(f"Gemini : Échec de l'initialisation de Gemini via Vertex AI : {e}")
            return False
    
    return True

async def extract_skills_with_gemini(job_title: str, descriptions: List[str], logger: logging.Logger) -> Optional[Dict[str, Any]]:
    """
    Envoie un lot de descriptions de postes à l'API Gemini via Vertex AI pour extraction en streaming.

    :param job_title: Le titre du métier (utilisé pour le contexte des logs).
    :param descriptions: Une liste de descriptions de postes à analyser.
    :param logger: L'instance de logger à utiliser pour les messages de ce module.
    :return: Un dictionnaire contenant les données extraites au format JSON, ou None en cas d'erreur.
    """
    global _current_logger
    _current_logger = logger 

    if not model or not prompt_template:
        _current_logger.error("Gemini : Tentative d'appel à Gemini sans initialisation préalable.")
        if not initialize_gemini(logger):
            return None

    indexed_descriptions = "\n---\n".join([f"{i}: {desc}" for i, desc in enumerate(descriptions)])
    full_prompt = prompt_template.format(indexed_descriptions=indexed_descriptions)

    _current_logger.info(f"Gemini : Envoi de {len(descriptions)} descriptions au modèle via Vertex AI (lot pour '{job_title}') en mode streaming...") 
    
    full_response_content = ""
    try:
        responses = await model.generate_content_async(full_prompt, stream=True) 

        async for chunk in responses:
            if chunk and chunk.text:
                full_response_content += chunk.text
        
        cleaned_text = full_response_content.replace(r"\'", "'")
        skills_json = json.loads(cleaned_text)
        
        _current_logger.info(f"Gemini : Réponse JSON complète reçue et parsée avec succès pour ce lot ({len(descriptions)} descriptions).")
        return skills_json
        
    except json.JSONDecodeError as e:
        _current_logger.error(f"Gemini : Erreur de décodage JSON de la réponse en streaming : {e}. Réponse complète reçue : {full_response_content[:1000]}...")
        return None
    except Exception as e:
        _current_logger.error(f"Gemini : Erreur inattendue lors de l'appel à l'API via Vertex AI : {e}")
        return None