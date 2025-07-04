import re
import logging
from src.esco_api import get_esco_skills

logging.info("Chargement de la liste de compétences ESCO...")
ALL_SKILLS = get_esco_skills()
logging.info(f"{len(ALL_SKILLS)} compétences chargées.")

def _build_regex_pattern(skills: list[str]) -> re.Pattern:
    logging.info("Construction du motif regex...")
    
    escaped_skills = [re.escape(skill) for skill in skills]
    
    pattern_string = r'\\b(' + '|'.join(escaped_skills) + r')\\b'
    
    compiled_regex = re.compile(pattern_string, re.IGNORECASE)
    
    logging.info("Motif regex construit avec succès.")
    return compiled_regex

REGEX_PATTERN = _build_regex_pattern(ALL_SKILLS)

def extract_skills_from_text(text: str) -> set[str]:
    if not text or not REGEX_PATTERN:
        return set()
    
    found_matches = re.findall(REGEX_PATTERN, text)
    
    return set(match.lower() for match in found_matches)