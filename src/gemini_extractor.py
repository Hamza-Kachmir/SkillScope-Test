import google.generativeai as genai
from google.oauth2 import service_account
import logging
import json
import os
import asyncio
from typing import Dict, Any, List, Optional

# --- Constantes de configuration Gemini ---
MODEL_NAME = 'gemini-1.5-flash-latest'
# Le prompt est maintenant à la racine du projet, un seul '..' suffit
PROMPT_FILE_PATH = os.path.join(os.path.dirname(__file__), '..', 'prompt.md')

# --- État global du module ---
model: Optional[genai.GenerativeModel] = None
prompt_template: Optional[str] = None
_current_logger: logging.Logger = logging.getLogger(__name__)


def _load_prompt_from_file() -> Optional[str]:
    """Charge le template du prompt depuis le fichier prompt.md."""
    try:
        with open(PROMPT_FILE_PATH, 'r', encoding='utf-8') as f:
            _current_logger.info(f"Gemini (Extractor) : Prompt chargé avec succès depuis '{PROMPT_FILE_PATH}'.")
            return f.read()
    except FileNotFoundError:
        _current_logger.critical(f"Gemini (Extractor) : Fichier de prompt non trouvé à l'emplacement '{PROMPT_FILE_PATH}' !")
        return None
    except Exception as e:
        _current_logger.critical(f"Gemini (Extractor) : Erreur lors de la lecture du fichier de prompt : {e}")
        return None

def initialize_gemini(logger: logging.Logger) -> bool:
    """
    Initialise le client Gemini et charge le prompt pour l'extraction de données.
    Cette fonction doit être appelée avant toute utilisation du modèle Gemini.
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
        google_creds_json = os.getenv('GOOGLE_CREDENTIALS')
        if not google_creds_json:
            _current_logger.critical("Gemini (Extractor) : La variable d'environnement GOOGLE_CREDENTIALS n'est pas définie !")
            return False

        try:
            credentials_info = json.loads(google_creds_json)
            credentials = service_account.Credentials.from_service_account_info(credentials_info)
            genai.configure(credentials=credentials)

            generation_config = {"temperature": 0.0, "response_mime_type": "application/json"}

            model = genai.GenerativeModel(MODEL_NAME, generation_config=generation_config)
            _current_logger.info(f"Gemini (Extractor) : Client '{MODEL_NAME}' initialisé avec succès.")
            return True
        except Exception as e:
            _current_logger.critical(f"Gemini (Extractor) : Échec de l'initialisation de Gemini : {e}")
            return False

    return True

async def extract_skills_with_gemini(job_title: str, descriptions_with_titles: List[Dict], logger: logging.Logger) -> Optional[Dict[str, Any]]:
    """
    Envoie un lot de descriptions de postes (incluant titres) à l'API Gemini pour extraire les compétences et le niveau d'éducation.
    Le prompt modifié demandera à Gemini de normaliser les compétences directement.
    """
    global _current_logger
    _current_logger = logger

    if not model or not prompt_template:
        _current_logger.error("Gemini (Extractor) : Tentative d'appel à Gemini sans initialisation préalable.")
        if not initialize_gemini(logger):
            return None

    # Formate les descriptions et titres pour le prompt
    indexed_content = []
    for i, entry in enumerate(descriptions_with_titles):
        title = entry.get('titre', 'Titre non spécifié')
        description = entry.get('description', '')
        # Inclure le titre et la description dans le format attendu par le prompt
        indexed_content.append(f"{i}: Titre: {title}\nDescription: {description}")
    
    formatted_content_for_prompt = "\n---\n".join(indexed_content)
    # Utilise le nouveau placeholder dans le prompt
    full_prompt = prompt_template.format(indexed_descriptions_and_titles=formatted_content_for_prompt)

    _current_logger.info(f"Gemini (Extractor) : Envoi de {len(descriptions_with_titles)} descriptions (avec titres) au modèle (lot pour '{job_title}').")

    try:
        response = await model.generate_content_async(full_prompt)

        cleaned_text = response.text.replace(r"\'", "'")
        skills_json = json.loads(cleaned_text)
        
        _current_logger.info(f"Gemini (Extractor) : Réponse JSON complète reçue et parsée avec succès pour ce lot ({len(descriptions_with_titles)} descriptions).")
        return skills_json

    except json.JSONDecodeError as e:
        _current_logger.error(f"Gemini (Extractor) : Erreur de décodage JSON de la réponse : {e}. Réponse complète reçue : {response.text[:1000]}...")
        return None
    except Exception as e:
        _current_logger.error(f"Gemini (Extractor) : Erreur inattendue lors de l'appel à l'API : {e}")
        return None