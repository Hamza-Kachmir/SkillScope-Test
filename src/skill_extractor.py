import logging
import os
import re
import json

# Dictionnaire pour garder en mémoire les compétences chargées et éviter de les relire
SKILLS_DATA = {}

def load_skills_from_json():
    """
    Charge les compétences depuis les 3 fichiers JSON.
    Cette fonction ne s'exécute qu'une seule fois.
    """
    global SKILLS_DATA
    # Si les données sont déjà chargées, on ne fait rien
    if SKILLS_DATA:
        return

    logging.info("Début du chargement des compétences depuis les fichiers JSON...")
    
    # Chemins relatifs depuis la racine du projet
    skill_files = {
        "HardSkills": "skills/HardSkills.json",
        "SoftSkills": "skills/SoftSkills.json",
        "Languages": "skills/Languages.json"
    }

    temp_skills = {}
    for skill_type, path in skill_files.items():
        try:
            with open(path, 'r', encoding='utf-8') as f:
                skills = json.load(f)
                # On nettoie et on met en minuscule pour une recherche fiable
                temp_skills[skill_type] = {str(skill).lower() for skill in skills if skill}
                # C'est ici que le log affiche le compte par fichier
                logging.info(f"-> {len(temp_skills[skill_type])} compétences récupérées dans {skill_type}.")
        except FileNotFoundError:
            logging.error(f"Fichier de compétences INTROUVABLE : '{path}'. Assurez-vous qu'il est bien à la racine du projet dans le dossier 'skills'.")
            temp_skills[skill_type] = set()
        except json.JSONDecodeError:
            logging.error(f"Erreur de format dans le fichier JSON : {path}.")
            temp_skills[skill_type] = set()
        except Exception as e:
            logging.error(f"Erreur inattendue lors du chargement de {path}: {e}")
            temp_skills[skill_type] = set()
    
    SKILLS_DATA = temp_skills
    logging.info("Chargement des compétences terminé.")

def extract_skills(text: str) -> dict:
    """
    Extrait les compétences d'une chaîne de texte en se basant sur les listes JSON.
    Retourne un dictionnaire avec les compétences classées par catégorie.
    """
    # Charge les compétences depuis les fichiers si ce n'est pas déjà fait
    load_skills_from_json()

    extracted = {
        "HardSkills": set(),
        "SoftSkills": set(),
        "Languages": set()
    }

    # Si le texte est vide ou non valide, on retourne un résultat vide
    if not isinstance(text, str) or not text:
        return {k: [] for k, v in extracted.items()}

    text_lower = text.lower()

    for skill_type, skills_set in SKILLS_DATA.items():
        for skill in skills_set:
            # On utilise une expression régulière pour trouver le mot/la phrase exacte (word boundary)
            if re.search(r'\b' + re.escape(skill) + r'\b', text_lower):
                # On capitalise pour un affichage plus propre
                extracted[skill_type].add(skill.capitalize())

    # On convertit les ensembles (sets) en listes triées
    return {k: sorted(list(v)) for k, v in extracted.items()}