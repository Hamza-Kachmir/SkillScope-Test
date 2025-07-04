# --- Configuration de l'API France Travail ---
AUTH_URL = "https://entreprise.francetravail.fr/connexion/oauth2/access_token?realm=/partenaire"
API_BASE_URL = "https://api.francetravail.io/partenaire/offresdemploi"

# --- Configuration de l'API APEC ---
# L'API APEC est appelée directement dans apec_api.py, pas besoin de BASE_URL ici
# pour le moment, car l'URL est dans le fichier apec_api.py lui-même.

# --- En-têtes HTTP pour les requêtes (utilisés par APEC API et potentiellement d'autres) ---
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
    "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7"
}