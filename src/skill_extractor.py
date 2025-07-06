import pandas as pd
import logging
import os
import re
import json

# Dictionnaire pour stocker les compétences chargées
SKILLS_DATA = {
    "HardSkills": [],
    "SoftSkills": [],
    "Languages": []
}

def load_skills_from_json():
    """
    Charge les compétences à partir des fichiers JSON de compétences et les stocke dans SKILLS_DATA.
    Enregistre également le nombre de compétences chargées pour chaque catégorie.
    """
    skill_files = {
        "HardSkills": "src/skills/HardSkills.json",
        "SoftSkills": "src/skills/SoftSkills.json",
        "Languages": "src/skills/Languages.json"
    }

    for skill_type, path in skill_files.items():
        try:
            with open(path, 'r', encoding='utf-8') as f:
                skills = json.load(f)
                SKILLS_DATA[skill_type] = [skill.lower() for skill in skills]
                logging.info(f"{len(SKILLS_DATA[skill_type])} compétences récupérées pour {skill_type}.")
        except FileNotFoundError:
            logging.error(f"Le fichier de compétences {path} n'a pas été trouvé.")
        except json.JSONDecodeError:
            logging.error(f"Erreur de décodage JSON dans le fichier {path}.")
        except Exception as e:
            logging.error(f"Une erreur inattendue est survenue lors du chargement de {path}: {e}")

def extract_skills(text):
    """
    Extrait les compétences du texte fourni en utilisant les listes de compétences chargées.

    Args:
        text (str): Le texte à partir duquel extraire les compétences.

    Returns:
        dict: Un dictionnaire contenant les compétences extraites, classées par type.
    """
    if not any(SKILLS_DATA.values()):
        load_skills_from_json()

    extracted_skills = {
        "HardSkills": set(),
        "SoftSkills": set(),
        "Languages": set()
    }

    if not isinstance(text, str):
        return extracted_skills

    text_lower = text.lower()

    for skill_type, skills in SKILLS_DATA.items():
        for skill in skills:
            if re.search(r'\b' + re.escape(skill) + r'\b', text_lower):
                extracted_skills[skill_type].add(skill.capitalize())
    
    return {k: list(v) for k, v in extracted_skills.items()}

if __name__ == '__main__':
    # Initialisation du logging pour les tests
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    
    # Test de chargement des compétences
    load_skills_from_json()
    
    # Test d'extraction
    sample_text = "Nous recherchons un développeur avec des compétences en python et en gestion de projet. La maîtrise de l'anglais est un plus."
    skills_found = extract_skills(sample_text)
    
    logging.info(f"Compétences extraites : {skills_found}")