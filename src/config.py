# --- Configuration de l'API France Travail ---
AUTH_URL = "https://entreprise.francetravail.fr/connexion/oauth2/access_token?realm=/partenaire"
API_BASE_URL = "https://api.francetravail.io/partenaire/offresdemploi"

# --- Configuration du Scraper Welcome to the Jungle ---
BASE_WTTJ_URL = "https://www.welcometothejungle.com"

# --- Sélecteurs CSS pour le scraping ---
SEARCH_RESULTS_SELECTOR = 'ol[data-testid="search-results"]'
JOB_CARD_SELECTOR = 'li[data-testid="search-results-list-item-wrapper"]'
COOKIE_BUTTON_ID = "onetrust-accept-btn-handler"

# --- En-têtes HTTP pour les requêtes ---
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
    "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7"
}