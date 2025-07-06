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
    # CHEMINS CORRIGÉS : Le dossier "skills" est à la racine
    skill_files = {
        "HardSkills": "skills/HardSkills.json",
        "SoftSkills": "skills/SoftSkills.json",
        "Languages": "skills/Languages.json"
    }

    # Vérifie si les compétences sont déjà chargées pour éviter de le faire plusieurs fois
    if any(SKILLS_DATA.values()):
        return

    for skill_type, path in skill_files.items():
        try:
            with open(path, 'r', encoding='utf-8') as f:
                skills = json.load(f)
                # On s'assure que toutes les compétences sont en minuscules pour la recherche
                SKILLS_DATA[skill_type] = [str(skill).lower() for skill in skills if skill]
                logging.info(f"{len(SKILLS_DATA[skill_type])} compétences récupérées pour {skill_type}.")
        except FileNotFoundError:
            logging.error(f"Fichier de compétences INTROUVABLE : {path}. Vérifiez que le fichier existe bien à la racine du projet.")
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
        return {k: list(v) for k, v in extracted_skills.items()}

    text_lower = text.lower()

    for skill_type, skills in SKILLS_DATA.items():
        for skill in skills:
            # Utilise des expressions régulières pour trouver le mot/phrase exact(e)
            if re.search(r'\b' + re.escape(skill) + r'\b', text_lower):
                # On remet la première lettre en majuscule pour l'affichage
                extracted_skills[skill_type].add(skill.capitalize())
    
    return {k: list(v) for k, v in extracted_skills.items()}