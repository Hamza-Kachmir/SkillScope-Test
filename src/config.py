# --- Configuration de l'API France Travail ---
AUTH_URL = "https://entreprise.francetravail.fr/connexion/oauth2/access_token?realm=/partenaire"
API_BASE_URL = "https://api.francetravail.io/partenaire/offresdemploi"

# --- Configuration du Scraper APEC (utilisant Selenium + Requests) ---
APEC_BASE_URL = "https://www.apec.fr"
# Chemin pour la page de recherche APEC (où Selenium naviguera)
APEC_SEARCH_URL_PATH = "/candidat/recherche-emploi.html/emploi/recherche-offres.html" 

# Sélecteurs CSS pour le scraping de la liste des offres APEC (avec Selenium)
APEC_JOB_CARD_SELECTOR = 'apec-recherche-resultat a[queryparamshandling="merge"]' # Lien global de la carte
APEC_JOB_CARD_TITLE_SELECTOR = 'h2.card-title' # Titre de l'offre
APEC_JOB_CARD_COMPANY_SELECTOR = 'p.card-offer__company' # Nom de l'entreprise
APEC_JOB_CARD_URL_SELECTOR = 'a[queryparamshandling="merge"]' # Le lien principal de la carte d'offre
APEC_COOKIE_BUTTON_ID = "onetrust-accept-btn-handler" # ID du bouton d'acceptation des cookies (OneTrust)

# --- En-têtes HTTP pour les requêtes (utilisés par Requests et Selenium) ---
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
    "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7"
}