import google.generativeai as genai
from google.oauth2 import service_account
import logging
import json
import os
import asyncio
from typing import Dict, Any, List, Optional

# --- Constantes de configuration Gemini pour la normalisation ---
MODEL_NAME_NORMALIZER = 'gemini-1.5-flash-latest' # Peut être le même modèle ou un autre si nécessaire.
# MODIFICATION ICI : Remonte d'un niveau pour atteindre la racine (où est normalize_prompt.md)
PROMPT_NORMALIZER_FILE_PATH = os.path.join(os.path.dirname(__file__), '..', 'normalize_prompt.md')

# --- État global du module de normalisation ---
normalizer_model: Optional[genai.GenerativeModel] = None
normalizer_prompt_template: Optional[str] = None
_normalizer_logger: logging.Logger = logging.getLogger(__name__)

def _load_normalizer_prompt_from_file() -> Optional[str]:
    """Charge le template du prompt de normalisation depuis le fichier normalize_prompt.md."""
    try:
        with open(PROMPT_NORMALIZER_FILE_PATH, 'r', encoding='utf-8') as f:
            _normalizer_logger.info(f"Gemini (Normalizer) : Prompt chargé avec succès depuis '{PROMPT_NORMALIZER_FILE_PATH}'.")
            return f.read()
    except FileNotFoundError:
        _normalizer_logger.critical(f"Gemini (Normalizer) : Fichier de prompt non trouvé à l'emplacement '{PROMPT_NORMALIZER_FILE_PATH}' !")
        return None
    except Exception as e:
        _normalizer_logger.critical(f"Gemini (Normalizer) : Erreur lors de la lecture du fichier de prompt de normalisation : {e}")
        return None

def initialize_gemini_normalizer(logger: logging.Logger) -> bool:
    """
    Initialise le client Gemini et charge le prompt pour la normalisation/agrégation des compétences.
    """
    global normalizer_model, normalizer_prompt_template, _normalizer_logger
    _normalizer_logger = logger

    if normalizer_model and normalizer_prompt_template:
        return True

    if not normalizer_prompt_template:
        normalizer_prompt_template = _load_normalizer_prompt_from_file()
        if not normalizer_prompt_template:
            return False

    if not normalizer_model:
        google_creds_json = os.getenv('GOOGLE_CREDENTIALS')
        if not google_creds_json:
            _normalizer_logger.critical("Gemini (Normalizer) : La variable d'environnement GOOGLE_CREDENTIALS n'est pas définie !")
            return False

        try:
            credentials_info = json.loads(google_creds_json)
            credentials = service_account.Credentials.from_service_account_info(credentials_info)
            genai.configure(credentials=credentials)

            generation_config = {"temperature": 0.0, "response_mime_type": "application/json"}

            normalizer_model = genai.GenerativeModel(MODEL_NAME_NORMALIZER, generation_config=generation_config)
            _normalizer_logger.info(f"Gemini (Normalizer) : Client '{MODEL_NAME_NORMALIZER}' initialisé avec succès pour la normalisation.")
            return True
        except Exception as e:
            _normalizer_logger.critical(f"Gemini (Normalizer) : Échec de l'initialisation de Gemini pour la normalisation : {e}")
            return False
    return True

async def normalize_and_aggregate_skills(raw_skills_with_counts: Dict[str, int], logger: logging.Logger) -> Optional[Dict[str, int]]:
    """
    Envoie les compétences brutes extraites à Gemini pour normalisation et agrégation.
    Le prompt demande à Gemini de standardiser les noms de compétences et de fusionner les fréquences.
    """
    global _normalizer_logger
    _normalizer_logger = logger

    if not normalizer_model or not normalizer_prompt_template:
        _normalizer_logger.error("Gemini (Normalizer) : Tentative d'appel sans initialisation préalable.")
        if not initialize_gemini_normalizer(logger):
            return None

    # Formate les compétences brutes pour le prompt
    # Example: "Skill A: 10, Skill B: 5, Skill C: 12"
    formatted_skills_input = ", ".join([f'"{skill}": {count}' for skill, count in raw_skills_with_counts.items()])
    full_prompt = normalizer_prompt_template.format(raw_skills_json=json.dumps(raw_skills_with_counts, ensure_ascii=False))

    _normalizer_logger.info(f"Gemini (Normalizer) : Envoi de {len(raw_skills_with_counts)} compétences brutes au normaliseur.")

    try:
        response = await normalizer_model.generate_content_async(full_prompt)
        cleaned_text = response.text.replace(r"\'", "'")
        normalized_data = json.loads(cleaned_text)

        # La réponse attendue est un dictionnaire directement {compétence_normalisée: fréquence_combinée}
        if "normalized_skills" in normalized_data and isinstance(normalized_data["normalized_skills"], dict):
            _normalizer_logger.info(f"Gemini (Normalizer) : Normalisation réussie. {len(normalized_data['normalized_skills'])} compétences normalisées obtenues.")
            return normalized_data["normalized_skills"]
        else:
            _normalizer_logger.error(f"Gemini (Normalizer) : La structure de la réponse n'est pas celle attendue. Réponse: {normalized_data}")
            return None

    except json.JSONDecodeError as e:
        _normalizer_logger.error(f"Gemini (Normalizer) : Erreur de décodage JSON de la réponse : {e}. Réponse complète reçue : {response.text[:1000]}...")
        return None
    except Exception as e:
        _normalizer_logger.error(f"Gemini (Normalizer) : Erreur inattendue lors de l'appel à l'API de normalisation : {e}")
        return None