import re
import logging
from src.esco_api import get_esco_skills

logging.info("Tentative de chargement de la liste de compétences ESCO...")
ALL_SKILLS = get_esco_skills()
logging.info(f"Chargement terminé. {len(ALL_SKILLS)} compétences brutes récupérées.")

def _build_regex_pattern(skills: list[str]) -> re.Pattern:
    logging.info("Construction du motif regex...")
    
    # On filtre les compétences vides ou invalides
    valid_skills = [skill for skill in skills if isinstance(skill, str) and skill.strip()]
    if not valid_skills:
        logging.error("Aucune compétence valide trouvée pour construire le motif regex.")
        return None
        
    logging.info(f"{len(valid_skills)} compétences valides utilisées pour la regex.")
    
    escaped_skills = [re.escape(skill) for skill in valid_skills]
    
    pattern_string = r'\b(' + '|'.join(escaped_skills) + r')\b'
    
    compiled_regex = re.compile(pattern_string, re.IGNORECASE)
    
    logging.info("Motif regex construit avec succès.")
    return compiled_regex

REGEX_PATTERN = _build_regex_pattern(ALL_SKILLS)

def extract_skills_from_text(text: str) -> set[str]:
    if not text or not REGEX_PATTERN:
        return set()
    
    found_matches = re.findall(REGEX_PATTERN, text)
    
    return set(match.lower() for match in found_matches)