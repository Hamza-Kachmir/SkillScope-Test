import json
import os
import re
from unidecode import unidecode

def load_all_skills(base_path='assets/skills'):
    # Cette fonction ne change pas, on charge toujours les compétences dans des sets
    hard_skills = set()
    with open(os.path.join(base_path, 'HardSkills.json'), 'r', encoding='utf-8') as f:
        hard_skills_data = json.load(f)
    for skill in hard_skills_data:
        # Important: on normalise les compétences ici pour la comparaison
        hard_skills.add(unidecode(skill.lower()))

    with open(os.path.join(base_path, 'SoftSkills.json'), 'r', encoding='utf-8') as f:
        soft_skills = {unidecode(skill.lower()) for skill in json.load(f)}

    with open(os.path.join(base_path, 'Languages.json'), 'r', encoding='utf-8') as f:
        languages = {unidecode(skill.lower()) for skill in json.load(f)}
        
    return hard_skills, soft_skills, languages

def extract_skills(text, hard_skills_set, soft_skills_set, languages_set):
    """
    Nouvelle version ultra-rapide utilisant l'intersection d'ensembles.
    """
    if not isinstance(text, str):
        return {'hard': [], 'soft': [], 'language': []}

    # 1. Normaliser le texte de l'offre et le découper en un "sac de mots" uniques
    normalized_text = unidecode(text.lower())
    # On utilise une regex simple pour extraire tous les mots
    text_words = set(re.findall(r'\b\w+\b', normalized_text))

    # 2. Comparer les "sacs de mots" avec l'opérateur d'intersection (&)
    found_hard = hard_skills_set & text_words
    found_soft = soft_skills_set & text_words
    found_lang = languages_set & text_words
    
    return {
        'hard': list(found_hard),
        'soft': list(found_soft),
        'language': list(found_lang)
    }