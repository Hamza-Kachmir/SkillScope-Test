import vertexai
from vertexai.preview.generative_models import GenerativeModel, Part, Content, Tool, ToolConfig
import logging
import json
import os
import asyncio
from typing import Dict, Any, List, Optional

# --- Constantes de configuration Gemini via Vertex AI ---
MODEL_NAME = 'gemini-1.5-flash-latest' # Définit le nom du modèle Gemini à utiliser.
PROMPT_FILE_PATH = os.path.join(os.path.dirname(__file__), '..', 'prompt.md') # Chemin vers le fichier du prompt.

# --- État global du module ---
_vertex_model: Optional[GenerativeModel] = None # Variable globale pour stocker l'instance du modèle Vertex AI.
_prompt_template: Optional[str] = None # Variable globale pour stocker le contenu du prompt.
_current_logger: logging.Logger = logging.getLogger(__name__) # Logger spécifique pour ce module.

# Dictionnaire pour stocker les sessions de chat actives par terme de recherche.
# Cela permet de maintenir le contexte pour les lots d'un même métier.
_active_chat_sessions: Dict[str, Any] = {} # Key: job_title_normalized, Value: ChatSession object

def _load_prompt_from_file() -> Optional[str]:
    """Charge le template du prompt depuis le fichier prompt.md."""
    try:
        with open(PROMPT_FILE_PATH, 'r', encoding='utf-8') as f:
            _current_logger.info(f"Gemini : Prompt chargé avec succès depuis '{PROMPT_FILE_PATH}'.")
            return f.read() # Retourne le contenu du fichier.
    except FileNotFoundError:
        _current_logger.critical(f"Gemini : Fichier de prompt non trouvé à l'emplacement '{PROMPT_FILE_PATH}' !")
        return None # Retourne None si le fichier n'est pas trouvé.
    except Exception as e:
        _current_logger.critical(f"Gemini : Erreur lors de la lecture du fichier de prompt : {e}")
        return None # Gère les autres erreurs de lecture.

def initialize_gemini(logger: logging.Logger) -> bool:
    """
    Initialise le client Gemini via Vertex AI et charge le prompt pour l'extraction de données.
    Cette fonction doit être appelée avant toute utilisation du modèle Gemini.
    """
    global _vertex_model, _prompt_template, _current_logger
    _current_logger = logger # Met à jour le logger avec l'instance fournie.

    # Vérifie si le modèle et le prompt sont déjà initialisés pour éviter de les recharger.
    if _vertex_model and _prompt_template:
        return True

    # Charge le prompt si ce n'est pas déjà fait.
    if not _prompt_template:
        _prompt_template = _load_prompt_from_file()
        if not _prompt_template:
            return False # Échec si le prompt ne peut pas être chargé.

    # Initialise Vertex AI et le modèle Gemini si ce n'est pas déjà fait.
    if not _vertex_model:
        google_creds_json = os.getenv('GOOGLE_CREDENTIALS')
        google_project_id = os.getenv('GOOGLE_CLOUD_PROJECT_ID')
        google_location = os.getenv('GOOGLE_CLOUD_LOCATION', 'us-central1') # Default location for Vertex AI

        if not google_creds_json or not google_project_id:
            _current_logger.critical("Gemini : Les variables d'environnement GOOGLE_CREDENTIALS ou GOOGLE_CLOUD_PROJECT_ID ne sont pas définies !")
            return False

        try:
            # Vertex AI initialization
            vertexai.init(project=google_project_id, location=google_location)
            _current_logger.info(f"Vertex AI initialisé pour le projet '{google_project_id}' à '{google_location}'.")

            generation_config = {"temperature": 0.0, "response_mime_type": "application/json"}

            _vertex_model = GenerativeModel(MODEL_NAME, generation_config=generation_config)
            _current_logger.info(f"Gemini : Modèle '{MODEL_NAME}' initialisé avec succès via Vertex AI.")
            return True
        except Exception as e:
            _current_logger.critical(f"Gemini : Échec de l'initialisation de Vertex AI ou du modèle Gemini : {e}")
            return False

    return True

async def extract_skills_with_gemini(job_title_normalized: str, descriptions: List[str], logger: logging.Logger) -> Optional[Dict[str, Any]]:
    """
    Envoie un lot de descriptions de postes à l'API Gemini (via Vertex AI) pour extraire les compétences
    et le niveau d'éducation, en utilisant une session de chat persistante pour un même job_title.
    """
    global _current_logger, _active_chat_sessions
    _current_logger = logger

    if not _vertex_model or not _prompt_template:
        _current_logger.error("Gemini : Tentative d'appel à Gemini sans initialisation préalable.")
        if not initialize_gemini(logger):
            return None

    # Récupère ou crée une session de chat pour ce job_title normalisé.
    # Chaque nouvelle recherche de métier démarre une nouvelle session logique.
    if job_title_normalized not in _active_chat_sessions:
        _current_logger.info(f"Création d'une nouvelle session de chat Gemini pour le métier '{job_title_normalized}'.")
        # Passe directement le prompt_template comme system_instruction sous forme de chaîne.
        chat = _vertex_model.start_chat(system_instruction=_prompt_template)
        _active_chat_sessions[job_title_normalized] = chat
    else:
        chat = _active_chat_sessions[job_title_normalized]
        _current_logger.info(f"Réutilisation de la session de chat existante pour le métier '{job_title_normalized}'.")


    # Formate les descriptions pour les inclure dans le prompt.
    # Dans une session de chat, le "prompt" devient le message utilisateur envoyé après l'instruction système.
    indexed_descriptions = "\n---\n".join([f"{i}: {desc}" for i, desc in enumerate(descriptions)])
    user_message_content = f"DESCRIPTIONS À ANALYSER CI-DESSOUS (format \"index: description\"):\n{indexed_descriptions}"

    _current_logger.info(f"Gemini : Envoi de {len(descriptions)} descriptions au modèle (lot pour '{job_title_normalized}').")

    try:
        response = await chat.send_message_async(user_message_content)

        # Accès au texte de la réponse (peut varier légèrement avec le SDK Vertex AI)
        response_text = response.text
        cleaned_text = response_text.replace(r"\'", "'") # Nettoie la réponse pour corriger les échappements.
        skills_json = json.loads(cleaned_text) # Parse la réponse JSON.

        _current_logger.info(f"Gemini : Réponse JSON complète reçue et parsée avec succès pour ce lot ({len(descriptions)} descriptions).")
        return skills_json

    except json.JSONDecodeError as e:
        _current_logger.error(f"Gemini : Erreur de décodage JSON de la réponse : {e}. Réponse complète reçue : {response_text[:1000]}...")
        # En cas d'erreur de parsing, invalider la session pour ce métier pour éviter de propager l'erreur.
        if job_title_normalized in _active_chat_sessions:
            del _active_chat_sessions[job_title_normalized]
        return None
    except Exception as e:
        _current_logger.error(f"Gemini : Erreur inattendue lors de l'appel à l'API : {e}")
        # En cas d'erreur, invalider la session pour ce métier.
        if job_title_normalized in _active_chat_sessions:
            del _active_chat_sessions[job_title_normalized]
        return None

# Fonction pour effacer une session de chat spécifique, utile si une analyse est annulée ou terminée.
def clear_chat_session(job_title_normalized: str):
    """Supprime une session de chat active du stockage."""
    global _active_chat_sessions
    if job_title_normalized in _active_chat_sessions:
        del _active_chat_sessions[job_title_normalized]
        _current_logger.info(f"Session de chat pour '{job_title_normalized}' effacée.")