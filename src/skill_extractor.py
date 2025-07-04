import re

# Regex pour trouver les mots/groupes de mots pertinents :
# - Mots commençant par une majuscule (comme "Python", "Gestion de projet")
# - Acronymes en majuscules (comme "AWS", "GCP")
# - Mots composés avec des tirets ou des chiffres (comme "node-js", "c++")
CANDIDATE_REGEX = re.compile(r'\b([A-Z][a-zA-Z-&+#\./]+|[A-Z]{2,})\b')

def extract_candidate_skills(text: str) -> set[str]:
    if not text:
        return set()

    # Applique la regex et nettoie les résultats
    candidates = CANDIDATE_REGEX.findall(text)
    
    # On retourne un set de candidats en minuscules pour la normalisation
    return {candidate.strip() for candidate in candidates}