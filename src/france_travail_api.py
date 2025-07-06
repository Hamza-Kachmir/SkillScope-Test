import os
import requests
import logging
import pandas as pd
from datetime import datetime, timedelta
from typing import List, Dict

from dotenv import load_dotenv
load_dotenv()

AUTH_URL = "https://entreprise.francetravail.fr/connexion/oauth2/access_token?realm=/partenaire"
API_BASE_URL = "https://api.francetravail.io/partenaire/offresdemploi"

class FranceTravailClient:
    def __init__(self, client_id: str, client_secret: str, logger: logging.Logger):
        self.client_id = client_id
        self.client_secret = client_secret
        self.logger = logger
        self._access_token = None
        self._token_expiry_time = None

    def _get_access_token(self) -> bool:
        headers = {'Content-Type': 'application/x-www-form-urlencoded'}
        data = {
            'grant_type': 'client_credentials',
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'scope': 'api_offresdemploiv2 o2dsoffre'
        }
        try:
            self.logger.info("France Travail : Demande d'un nouveau token d'accès...")
            response = requests.post(AUTH_URL, headers=headers, data=data, timeout=10)
            response.raise_for_status()
            token_data = response.json()
            self._access_token = token_data['access_token']
            expires_in = token_data.get('expires_in', 1499)
            self._token_expiry_time = datetime.now() + timedelta(seconds=expires_in - 60)
            self.logger.info("France Travail : Token d'accès obtenu avec succès.")
            return True
        except requests.exceptions.RequestException as e:
            self.logger.critical(f"France Travail : Échec de l'obtention du token. {e}")
            return False

    def _is_token_valid(self) -> bool:
        return self._access_token and self._token_expiry_time and datetime.now() < self._token_expiry_time

    def search_offers(self, search_term: str, max_offers: int = 150) -> List[Dict]:
        if not self._is_token_valid():
            if not self._get_access_token():
                return []
        
        headers = {'Authorization': f'Bearer {self._access_token}'}
        params = {'motsCles': search_term, 'range': f'0-{max_offers - 1}', 'sort': 1}
        
        try:
            self.logger.info(f"France Travail : Exécution de la recherche pour '{search_term}'.")
            response = requests.get(f"{API_BASE_URL}/v2/offres/search", headers=headers, params=params, timeout=15)
            if response.status_code == 204:
                self.logger.info("France Travail : Aucune offre trouvée (code 204).")
                return []
            response.raise_for_status()
            api_results = response.json().get('resultats', [])
            self.logger.info(f"France Travail : {len(api_results)} offres reçues via l'API.")
            return api_results
        except requests.exceptions.RequestException as e:
            self.logger.error(f"France Travail : Erreur lors de la recherche. {e}")
            return []

def fetch_job_offers(job_name: str, location_code: str) -> pd.DataFrame:
    logger = logging.getLogger(__name__)
    
    client_id = os.getenv("FRANCE_TRAVAIL_CLIENT_ID")
    client_secret = os.getenv("FRANCE_TRAVAIL_CLIENT_SECRET")

    if not client_id or not client_secret:
        logger.critical("Variables d'environnement FRANCE_TRAVAIL_CLIENT_ID et/ou FRANCE_TRAVAIL_CLIENT_SECRET manquantes.")
        return pd.DataFrame()

    if location_code:
        logger.warning(f"Le paramètre de localisation '{location_code}' est ignoré.")

    client = FranceTravailClient(client_id=client_id, client_secret=client_secret, logger=logger)
    offers_list = client.search_offers(search_term=job_name)

    if not offers_list:
        return pd.DataFrame()

    processed_offers = []
    for offer in offers_list:
        entreprise = offer.get('entreprise', {}) if isinstance(offer.get('entreprise'), dict) else {}
        origine_offre = offer.get('origineOffre', {}) if isinstance(offer.get('origineOffre'), dict) else {}
        
        processed_offers.append({
            'id': offer.get('id', ''),
            'intitule': offer.get('intitule', 'Titre non précisé'),
            'description': offer.get('description', ''),
            'url': origine_offre.get('urlOrigine', '#'),
            'entreprise_nom': entreprise.get('nom', 'Non précisé'),
            'type_contrat': offer.get('typeContratLibelle', 'Non précisé')
        })

    df = pd.DataFrame(processed_offers)
    return df