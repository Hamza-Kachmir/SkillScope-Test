import google.generativeai as genai
from google.oauth2 import service_account
import logging
import json
import os
import asyncio
from typing import Dict, Any, List

MODEL_NAME = 'gemini-1.5-flash-latest'

PROMPT_COMPETENCES = """
## MISSION
Tu es un système expert en extraction de données pour le marché du travail. Ta mission est d'analyser des descriptions de postes avec une précision chirurgicale pour en extraire les compétences (`skills`) et le niveau d'études (`education_level`). Tu dois te comporter comme un analyseur sémantique déterministe qui suit les règles à la lettre.

## FORMAT DE SORTIE IMPÉRATIF
1.  **Format JSON Unique** : La sortie doit être un unique objet JSON valide contenant une seule clé principale : `"extracted_data"`.
2.  **Liste d'Objets** : La valeur de `"extracted_data"` doit être une liste d'objets. Chaque objet représente une des descriptions de poste analysées.
3.  **Structure de l'Objet** : Chaque objet dans la liste doit impérativement contenir trois clés : `"index"` (l'index de la description originale), `"skills"` (une liste de chaînes de caractères), et `"education_level"` (une unique chaîne de caractères).

## DÉFINITION FONDAMENTALE D'UNE COMPÉTENCE (RÈGLE D'OR)
1.  **Une compétence implique une action ou une expertise.** Elle doit décrire un savoir-faire. Des noms de concepts ou d'objets seuls ne sont pas des compétences.
    * **Exemple Clé :** "Construction de mur" est une compétence. "Mur" seul ne l'est pas. De la même manière, "Gestion de la paie" est une compétence, mais "Paie" seul ne l'est pas. Tu ne dois donc extraire que la compétence complète qui inclut l'action.
2.  **Exception pour les Technologies :** La seule exception concerne les noms propres désignant sans ambiguïté une technologie, un logiciel, un langage de programmation ou une méthodologie reconnue. Ceux-ci sont considérés comme des compétences à part entière.
    * **Exemples à extraire :** `Python`, `React`, `Docker`, `Microsoft Excel`, `SAP`, `Agile`, `Silae`.

## RÈGLES D'EXTRACTION SPÉCIFIQUES
1.  **Filtre** : Ignore les termes génériques (ex: expérience, maîtrise, connaissance), les titres de postes et les diplômes.
2.  **Normalisation** : Regroupe toutes les variations d'une même compétence sous un seul nom standard (ex: ["power bi", "PowerBI"] -> "Power BI").
3.  **Gestion de la Casse** :
    * **Acronymes** : Toujours en majuscules (ex: SQL, AWS, API, CRM).
    * **Noms Propres (Technologies, etc.)** : Casse standard de l'industrie (ex: Python, JavaScript, Power BI).
    * **Compétences Générales et Soft Skills** : Majuscule au premier mot (ex: "Gestion de projet", "Esprit d'équipe").

## RÈGLES D'EXTRACTION DU NIVEAU D'ÉTUDES
1.  **Priorité Absolue au Texte** : Ton analyse doit se baser **exclusivement** sur le texte de la description.
2.  **Aucune Inférence** : Si aucun diplôme n'est mentionné, tu DOIS retourner "Non spécifié".
3.  **Analyse de la Répartition** :
    * Si tu observes une **forte dispersion** des niveaux demandés (ex: de nombreuses offres à Bac+2/3 ET de nombreuses offres à Bac+5), tu **dois** retourner une **fourchette réaliste** pour refléter fidèlement le marché (ex: "Bac+2 à Bac+5").
    * Si une **majorité écrasante** des offres pointe vers un niveau unique, retourne ce niveau.
4.  **Catégories de Sortie Autorisées** : La valeur doit **obligatoirement** être l'une des suivantes : "CAP / BEP", "Bac", "Bac+2 / BTS", "Bac+3 / Licence", "Bac+5 / Master", "Doctorat", "Formation spécifique", "Non spécifié", ou une fourchette logique comme "Bac+2 à Bac+5".

## EXEMPLE COMPLET DE SORTIE ATTENDUE
```json
{{
  "extracted_data": [
    {{
      "index": 0,
      "skills": ["Java", "Spring Boot", "API REST", "SQL", "Travail en équipe"],
      "education_level": "Bac+5 / Master"
    }},
    {{
      "index": 1,
      "skills": ["JavaScript", "React", "HTML5", "CSS3"],
      "education_level": "Bac+2 à Bac+5"
    }},
    {{
      "index": 2,
      "skills": ["Gestion de la paie", "Droit social", "Silae", "Rigueur"],
      "education_level": "Bac+3 / Licence"
    }}
  ]
}}
DESCRIPTIONS À ANALYSER CI-DESSOUS (format "index: description"):
{indexed_descriptions}
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
        generation_config = {"temperature": 0.0, "response_mime_type": "application/json"}
        model = genai.GenerativeModel(MODEL_NAME, generation_config=generation_config)
        logging.info("Client Gemini initialisé avec succès via les variables d'environnement.")
        return True
    except Exception as e:
        logging.critical(f"Échec de l'initialisation de Gemini : {e}")
        return False
async def extract_skills_with_gemini(job_title: str, descriptions: List[str]) -> Dict[str, Any] | None:
    if not model:
        if not initialize_gemini():
            return None

    indexed_descriptions = "\\n---\\n".join([f"{i}: {desc}" for i, desc in enumerate(descriptions)])
    prompt = PROMPT_COMPETENCES.format(indexed_descriptions=indexed_descriptions)

    logging.info(f"Appel à l'API Gemini pour un lot de {len(descriptions)} descriptions...")
    try:
        response = await model.generate_content_async(prompt)
        
        # --- DÉBUT DE LA CORRECTION ---
        # On corrige l'erreur d'échappement de l'apostrophe avant de parser le JSON
        cleaned_text = response.text.replace(r"\'", "'")
        skills_json = json.loads(cleaned_text)
        # --- FIN DE LA CORRECTION ---

        logging.info("Réponse JSON de Gemini reçue et parsée avec succès pour un lot.")
        return skills_json
        
    except json.JSONDecodeError as e:
        # On utilise le texte nettoyé dans le message d'erreur pour un meilleur diagnostic
        logging.error(f"Erreur de décodage JSON de la réponse Gemini : {e}. Réponse brute: {cleaned_text}")
        return None
    except Exception as e:
        logging.error(f"Erreur lors de l'appel à l'API Gemini : {e}")
        return None