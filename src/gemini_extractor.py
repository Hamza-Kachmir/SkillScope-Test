import google.generativeai as genai
from google.oauth2 import service_account
import logging
import json
import os

MODEL_NAME = 'gemini-1.5-flash-latest'

PROMPT_COMPETENCES_AVANCE = """
TA MISSION : Tu es un système expert en analyse sémantique pour une base de données RH. Ton rôle est d'analyser une description de poste et d'en extraire les compétences (savoir-faire, savoir-être, langues) avec une précision absolue, en respectant des règles de normalisation et de déduplication très strictes.

RÈGLES STRICTES ET IMPÉRATIVES :

1.  **DÉCOMPOSITION** :
    - Si une compétence contient un slash (/), une virgule (,) ou le mot "et", sépare-la en compétences distinctes. Exemple : "CI/CD" devient ["CI", "CD"]. "Python, Java et Scala" devient ["Python", "Java", "Scala"].
    - Si une liste de compétences se trouve entre parenthèses, extrais chaque élément comme une compétence individuelle. Exemple : "Langages (Python, Go)" devient ["Python", "Go"].

2.  **NORMALISATION ET DÉDUPLICATION (RÈGLE LA PLUS IMPORTANTE)** :
    - Au sein de cette **unique** description de poste, une même compétence ne doit apparaître **qu'une seule fois** dans la liste finale, même si elle est mentionnée plusieurs fois dans le texte.
    - Identifie la technologie de base. Pour des termes comme "Spark SQL" ou "PySpark", les compétences à extraire sont ["Spark", "SQL", "PySpark"]. Ne garde que les termes les plus pertinents et atomiques.
    - Ignore les termes génériques comme "langage objet", "bases de données", etc. quand des exemples spécifiques sont donnés.

3.  **GESTION DE LA CASSE** :
    - Les acronymes (généralement 3 lettres ou moins, ou des termes connus comme DevOps) doivent être retournés en **MAJUSCULES** (ex: "SQL", "AWS", "GCP", "CI", "CD").
    - Toutes les autres compétences doivent être en **minuscules** (ex: "python", "java", "gestion de projet").

4.  **FORMAT DE SORTIE** : Le résultat doit être un unique objet JSON valide avec les clés "hard_skills", "soft_skills", et "languages". Les listes doivent être vides si aucune compétence n'est trouvée.

EXEMPLES COMPLEXES :

- **Description 1** : "Nous cherchons un expert en langages de programmation (Python, Java, et Scala). Maîtrise de CI/CD et SQL requise. Le développeur SQL devra aussi connaître Spark, notamment PySpark et Spark SQL."
- **JSON Attendu 1** :
  ```json
  {
    "hard_skills": ["python", "java", "scala", "CI", "CD", "SQL", "spark", "pyspark"],
    "soft_skills": [],
    "languages": []
  }
Description 2 : "Bonne communication orale et écrite. Anglais courant. La connaissance d'un CRM (Salesforce) est un plus."
JSON Attendu 2 :

{
  "hard_skills": ["salesforce"],
  "soft_skills": ["communication orale", "communication écrite"],
  "languages": ["anglais"]
}
DESCRIPTION À ANALYSER :
{description_text}
"""

model = None

def initialize_gemini():
    global model
    if model:
        return True

    google_creds_json = os.getenv('GOOGLE_CREDENTIALS')
    if not google_creds_json:
        logging.critical("La variable d'environnement GOOGLE_CREDENTIALS n'est pas définie !")
        return False
        
    try:
        credentials_info = json.loads(google_creds_json)
        credentials = service_account.Credentials.from_service_account_info(credentials_info)
        genai.configure(credentials=credentials)
        generation_config = {"temperature": 0.1, "response_mime_type": "application/json"}
        model = genai.GenerativeModel(MODEL_NAME, generation_config=generation_config)
        logging.info("Client Gemini initialisé avec succès via les variables d'environnement.")
        return True
    except Exception as e:
        logging.critical(f"Échec de l'initialisation de Gemini : {e}")
        return False

async def extract_skills_for_single_offer(description: str) -> dict | None:
    """Analyse la description d'UNE SEULE offre pour en extraire les compétences uniques."""
    if not model:
        if not initialize_gemini():
            return None

    if not description or not isinstance(description, str) or len(description.strip()) < 20:
        return None

    prompt = PROMPT_COMPETENCES_AVANCE.format(description_text=description)

    try:
        response = await model.generate_content_async(prompt)
        # CORRECTION : On nettoie la réponse avant de la parser pour éviter les erreurs
        cleaned_response = response.text.strip().replace("```json", "").replace("```", "").strip()
        skills_json = json.loads(cleaned_response)
        return skills_json
    except json.JSONDecodeError as e:
        # On logue l'erreur et la réponse problématique pour le débogage
        logging.warning(f"Erreur de décodage JSON: {e}. Réponse reçue:\n---\n{response.text}\n---")
        return None
    except Exception as e:
        logging.error(f"Erreur inattendue lors de l'analyse d'une offre: {e}")
        return None