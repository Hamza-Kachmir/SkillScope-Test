import re
import json
import os
from unidecode import unidecode

def load_all_skills(base_path='assets/skills'):
    hard_skills = set()
    with open(os.path.join(base_path, 'HardSkills.json'), 'r', encoding='utf-8') as f:
        hard_skills_data = json.load(f)
    for skill in hard_skills_data:
        hard_skills.add(unidecode(skill.lower()))

    with open(os.path.join(base_path, 'SoftSkills.json'), 'r', encoding='utf-8') as f:
        soft_skills = {unidecode(skill.lower()) for skill in json.load(f)}

    with open(os.path.join(base_path, 'Languages.json'), 'r', encoding='utf-8') as f:
        languages = {unidecode(skill.lower()) for skill in json.load(f)}
        
    return hard_skills, soft_skills, languages

def extract_skills(text, hard_skills, soft_skills, languages):
    if not isinstance(text, str):
        return {'hard': [], 'soft': [], 'language': []}

    normalized_text = unidecode(text.lower())

    # On construit une seule expression régulière pour chaque catégorie pour plus d'efficacité
    # re.escape s'assure que les caractères spéciaux (comme dans "c++") sont bien traités
    # \b est une "limite de mot", c'est la solution à votre problème
    hard_skills_pattern = re.compile(r'\b(' + '|'.join(re.escape(s) for s in hard_skills) + r')\b')
    soft_skills_pattern = re.compile(r'\b(' + '|'.join(re.escape(s) for s in soft_skills) + r')\b')
    languages_pattern = re.compile(r'\b(' + '|'.join(re.escape(s) for s in languages) + r')\b')

    # On utilise findall pour trouver toutes les correspondances en une seule fois
    found_hard = set(hard_skills_pattern.findall(normalized_text))
    found_soft = set(soft_skills_pattern.findall(normalized_text))
    found_lang = set(languages_pattern.findall(normalized_text))
    
    return {
        'hard': list(found_hard),
        'soft': list(found_soft),
        'language': list(found_lang)
    }