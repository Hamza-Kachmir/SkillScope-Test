import json
import os
import re
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

def extract_skills(text, hard_skills_pattern, soft_skills_pattern, languages_pattern):
    if not isinstance(text, str):
        return {'hard': [], 'soft': [], 'language': []}

    normalized_text = unidecode(text.lower())

    found_hard = set(hard_skills_pattern.findall(normalized_text))
    found_soft = set(soft_skills_pattern.findall(normalized_text))
    found_lang = set(languages_pattern.findall(normalized_text))
    
    return {
        'hard': list(found_hard),
        'soft': list(found_soft),
        'language': list(found_lang)
    }