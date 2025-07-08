import aiohttp
import logging
import os
from datetime import datetime, timedelta
from typing import List, Dict, Optional

# Constantes de l'API France Travail.
AUTH_URL = "https://entreprise.francetravail.fr/connexion/oauth2/access_token?realm=/partenaire"
API_BASE_URL = "https://api.francetravail.io/partenaire/offresdemploi"

class FranceTravailClient:
    """
    Un client asynchrone pour interagir avec l'API Offres d'Emploi v2 de France Travail.
    Gère l'authentification et la recherche d'offres.
    """

    def __init__(self, client_id: Optional[str] = None, client_secret: Optional[str] = None, logger: logging.Logger = logging.getLogger()):
        """
        Initialise le client. Les identifiants sont lus depuis les variables d'environnement si non fournis.

        :param client_id: L'ID client de l'API.
        :param client_secret: Le secret client de l'API.
        :param logger: L'instance de logger à utiliser pour les messages.
        """
        self.client_id = client_id or os.getenv("FT_CLIENT_ID")
        self.client_secret = client_secret or os.getenv("FT_CLIENT_SECRET")
        self.logger = logger
        self._access_token: Optional[str] = None
        self._token_expiry_time: Optional[datetime] = None

        if not self.client_id or not self.client_secret:
            self.logger.critical("Les variables d'environnement FT_CLIENT_ID et FT_CLIENT_SECRET ne sont pas définies !")
            raise ValueError("Configuration de l'API France Travail manquante.")

    async def _get_access_token(self) -> bool:
        """
        Obtient un nouveau token d'accès auprès du serveur d'authentification de France Travail.

        :return: True si le token a été obtenu avec succès, sinon False.
        """
        headers = {'Content-Type': 'application/x-www-form-urlencoded'}
        data = {
            'grant_type': 'client_credentials',
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'scope': 'api_offresdemploiv2 o2dsoffre'
        }
        try:
            self.logger.info("France Travail : Demande d'un nouveau token d'accès...")
            async with aiohttp.ClientSession() as session:
                async with session.post(AUTH_URL, headers=headers, data=data, timeout=10) as response:
                    response.raise_for_status() # Lève une exception pour les codes d'état HTTP 4xx/5xx.
                    token_data = await response.json()
                    self._access_token = token_data['access_token']
                    # Définit le temps d'expiration en laissant une marge de 60 secondes.
                    expires_in = token_data.get('expires_in', 3600)
                    self._token_expiry_time = datetime.now() + timedelta(seconds=expires_in - 60)
                    self.logger.info("France Travail : Token d'accès obtenu avec succès.")
                    return True
        except aiohttp.ClientError as e:
            self.logger.critical(f"France Travail : Échec de l'obtention du token. Erreur: {e}")
            return False

    def _is_token_valid(self) -> bool:
        """Vérifie si le token d'accès actuel est encore valide et n'a pas expiré."""
        return self._access_token and self._token_expiry_time and datetime.now() < self._token_expiry_time

    async def search_offers_async(self, search_term: str, max_offers: int = 150) -> List[Dict]:
        """
        Recherche des offres d'emploi de manière asynchrone auprès de l'API France Travail.

        :param search_term: Le mot-clé pour la recherche (ex: "développeur python").
        :param max_offers: Le nombre maximum d'offres à récupérer.
        :return: Une liste de dictionnaires, chaque dictionnaire représentant une offre formatée.
        """
        if not self._is_token_valid():
            if not await self._get_access_token():
                return [] # Impossible de procéder sans token valide.
        
        headers = {'Authorization': f'Bearer {self._access_token}'}
        # sort=1 pour trier les résultats par pertinence.
        params = {'motsCles': search_term, 'range': f'0-{max_offers - 1}', 'sort': 1}
        url = f"{API_BASE_URL}/v2/offres/search"
        
        self.logger.info(f"France Travail : Recherche de {max_offers} offres pour '{search_term}'.")
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, params=params, timeout=20) as response:
                    if response.status == 204: # 204 No Content signifie aucune offre trouvée.
                        self.logger.warning(f"France Travail : Aucune offre trouvée pour '{search_term}' (code 204).")
                        return []
                    
                    response.raise_for_status() # Lève une exception pour les codes d'état HTTP 4xx/5xx.
                    api_response = await response.json()
                    api_results = api_response.get('resultats', [])
                    self.logger.info(f"France Travail : {len(api_results)} offres reçues via l'API.")

                    # Formatte les offres dans un format simple et unifié.
                    return [{
                        'titre': offer.get('intitule', 'Titre non précisé'),
                        'entreprise': offer.get('entreprise', {}).get('nom', 'Non précisé'),
                        'url': offer.get('origineOffre', {}).get('urlOrigine', '#'),
                        'description': offer.get('description', '')
                    } for offer in api_results]
        except aiohttp.ClientError as e:
            self.logger.error(f"France Travail : Erreur lors de la recherche asynchrone. Erreur: {e}")
            return []