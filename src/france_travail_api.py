import requests
import logging
import pandas as pd
import streamlit as st
from datetime import datetime, timedelta
from typing import List, Dict

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
        data = {'grant_type': 'client_credentials', 'client_id': self.client_id, 'client_secret': self.client_secret, 'scope': 'api_offresdemploiv2 o2dsoffre'}
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