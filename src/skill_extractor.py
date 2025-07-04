import re
import logging
from src.esco_api import get_esco_skills

REGEX_PATTERN = None

def initialize_extractor():
    global REGEX_PATTERN
    if REGEX_PATTERN is not None:
        logging.info("Extracteur de compétences déjà initialisé.")
        return

    logging.info("Initialisation de l'extracteur de compétences...")
    
    ALL_SKILLS = get_esco_skills()
    
    logging.info(f"Construction du motif regex à partir de {len(ALL_SKILLS)} compétences...")
    valid_skills = [skill for skill in ALL_SKILLS if isinstance(skill, str) and skill.strip()]
    if not valid_skills:
        logging.error("Aucune compétence valide trouvée pour construire le motif regex.")
        REGEX_PATTERN = re.compile(r'a^') # Un regex qui ne matche jamais rien
        return
        
    logging.info(f"{len(valid_skills)} compétences valides utilisées pour la regex.")
    
    escaped_skills = [re.escape(skill) for skill in valid_skills]
    
    pattern_string = r'\b(' + '|'.join(escaped_skills) + r')\b'
    
    REGEX_PATTERN = re.compile(pattern_string, re.IGNORECASE)
    logging.info("Motif regex construit et initialisé avec succès.")


def extract_skills_from_text(text: str) -> set[str]:
    if not text or not REGEX_PATTERN:
        return set()
    
    found_matches = re.findall(REGEX_PATTERN, text)
    
    return set(match.lower() for match in found_matches)