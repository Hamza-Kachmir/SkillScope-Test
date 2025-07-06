import pandas as pd
import logging
import os
import re
from .normalization import build_normalization_map, get_canonical_form

class SkillExtractor:
    """
    Un extracteur de compétences avancé qui utilise la normalisation
    pour trouver des variantes de compétences dans un texte.
    """
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(SkillExtractor, cls).__new__(cls)
        return cls._instance

    def __init__(self, csv_path: str = "assets/hard_skills_29.json"):
        # Le 'singleton pattern' évite de réinitialiser la classe si elle l'a déjà été.
        if hasattr(self, 'is_initialized') and self.is_initialized:
            return
            
        logging.info("Initialisation de l'extracteur de compétences avancé...")
        self.is_initialized = False
        
        if not os.path.exists(csv_path):
            logging.error(f"Fichier de compétences non trouvé : {csv_path}")
            return

        try:
            # CORRIGÉ: On lit le fichier avec read_json car c'est un format JSON.
            df = pd.read_json(csv_path)
            
            # CORRIGÉ: Pandas charge la liste JSON dans une colonne nommée '0'.
            skill_list = df[0].dropna().unique().tolist()
            
            # Étape clé : On construit la carte de normalisation à l'initialisation.
            # Cette carte sait que "reactjs" et "react.js" doivent devenir "React.js".
            self.normalization_map = build_normalization_map(skill_list)
            
            # On stocke une table de correspondance entre la forme simplifiée (ex: "reactjs")
            # et sa meilleure représentation (ex: "React.js").
            self.canonical_to_best = {
                get_canonical_form(best_representation): best_representation 
                for best_representation in set(self.normalization_map.values())
            }
            
            logging.info(f"{len(skill_list)} compétences chargées et carte de normalisation créée.")
            self.is_initialized = True
        except Exception as e:
            logging.error(f"Erreur lors de l'initialisation de SkillExtractor : {e}")

    def extract_from_text(self, text: str) -> set[str]:
        """
        Extrait les compétences d'une chaîne de caractères.
        """
        if not self.is_initialized or not isinstance(text, str):
            return set()

        found_skills = set()
        # On simplifie le texte une seule fois pour optimiser la recherche.
        text_canonical = get_canonical_form(text.lower())
        
        # On cherche chaque compétence simplifiée dans le texte simplifié.
        for canonical_form, best_representation in self.canonical_to_best.items():
            if canonical_form in text_canonical:
                found_skills.add(best_representation)
        
        return found_skills

# --- Fonctions publiques utilisées par le pipeline ---
# Ces fonctions assurent que l'on travaille toujours avec la même instance de la classe.

def initialize_extractor():
    """Crée l'instance unique de l'extracteur."""
    SkillExtractor()

def extract_skills_from_text(text: str) -> set[str]:
    """Extrait les compétences en utilisant l'instance unique de l'extracteur."""
    extractor = SkillExtractor()
    return extractor.extract_from_text(text)