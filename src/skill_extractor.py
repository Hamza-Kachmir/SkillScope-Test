import pandas as pd
import logging
import os
import re

SKILLS_SET = set()
CSV_PATH = "assets/skills_fr.csv"

def initialize_extractor():
    global SKILLS_SET
    if SKILLS_SET:
        logging.info("Extracteur de compétences (local) déjà initialisé.")
        return

    logging.info("Initialisation de l'extracteur via le fichier CSV local...")
    if not os.path.exists(CSV_PATH):
        logging.error(f"Fichier de compétences non trouvé : {CSV_PATH}")
        return
        
    try:
        df = pd.read_csv(CSV_PATH)
        SKILLS_SET = set(df['preferredLabel'].str.lower().dropna())
        logging.info(f"{len(SKILLS_SET)} compétences uniques chargées depuis le fichier local.")
    except Exception as e:
        logging.error(f"Erreur lors de la lecture du fichier CSV : {e}")

def extract_skills_from_text(text: str) -> set[str]:
    if not text or not SKILLS_SET:
        return set()

    text_lower = text.lower()
    
    # On normalise le texte pour ne garder que les mots et espaces
    # et on s'assure qu'il est entouré d'espaces pour bien trouver les mots au début/fin.
    normalized_text = ' ' + re.sub(r'[^a-z0-9\s-]', ' ', text_lower) + ' '
    
    found_skills = {
        skill for skill in SKILLS_SET 
        if len(skill) > 2 and f' {skill} ' in normalized_text
    }
    
    return found_skills