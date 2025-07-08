import redis
import json
import os
import logging

# Durée de vie du cache en secondes (30 jours)
CACHE_TTL_SECONDS = 30 * 24 * 60 * 60

redis_client = None

def initialize_redis():
    """
    Initialise la connexion au client Redis en utilisant l'URL fournie
    dans les variables d'environnement.
    """
    global redis_client
    if redis_client:
        return

    redis_url = os.getenv('REDIS_URL')
    if not redis_url:
        logging.critical("La variable d'environnement REDIS_URL n'est pas définie !")
        return

    try:
        # decode_responses=True pour obtenir des chaînes (str) au lieu de bytes
        redis_client = redis.from_url(redis_url, decode_responses=True)
        redis_client.ping()
        logging.info("Connexion à Redis réussie.")
    except Exception as e:
        logging.error(f"Impossible de se connecter à Redis : {e}")
        redis_client = None

def get_cached_results(cache_key: str) -> dict | None:
    """
    Récupère un résultat depuis le cache Redis.

    :param cache_key: La clé unique pour la recherche en cache.
    :return: Le dictionnaire de résultats si trouvé, sinon None.
    """
    if redis_client is None: return None
    try:
        cached_json = redis_client.get(cache_key)
        if cached_json:
            logging.info(f"Cache HIT for '{cache_key}'.")
            return json.loads(cached_json)
        logging.info(f"Cache MISS for '{cache_key}'.")
        return None
    except Exception as e:
        logging.error(f"Erreur lors de la lecture du cache Redis pour la clé '{cache_key}': {e}")
        return None

def add_to_cache(cache_key: str, results: dict):
    """
    Ajoute un dictionnaire de résultats au cache Redis avec une durée d'expiration.

    :param cache_key: La clé sous laquelle stocker les résultats.
    :param results: Le dictionnaire de résultats à stocker.
    """
    if redis_client is None: return
    try:
        # `ensure_ascii=False` pour gérer correctement les caractères accentués
        value_to_store = json.dumps(results, ensure_ascii=False)
        redis_client.setex(cache_key, CACHE_TTL_SECONDS, value_to_store)
        logging.info(f"Cache WRITE for '{cache_key}'.")
    except Exception as e:
        logging.error(f"Erreur lors de l'écriture du cache Redis pour la clé '{cache_key}': {e}")

def delete_from_cache(cache_key: str):
    """
    Supprime une entrée spécifique du cache.

    :param cache_key: La clé à supprimer.
    """
    if redis_client is None: return
    try:
        redis_client.delete(cache_key)
        logging.info(f"CACHE DELETE for entry: '{cache_key}'.")
    except Exception as e:
        logging.error(f"Erreur lors de la suppression de la clé '{cache_key}' du cache Redis : {e}")

def flush_all_cache() -> bool:
    """
    Vide complètement la base de données Redis connectée.

    :return: True si le vidage a réussi, sinon False.
    """
    if redis_client is None:
        logging.error("Impossible de vider le cache: client Redis non initialisé.")
        return False
    try:
        redis_client.flushall()
        logging.info("CACHE FLUSH: Toutes les données ont été supprimées.")
        return True
    except Exception as e:
        logging.error(f"Erreur lors du vidage complet du cache Redis : {e}")
        return False

# Initialiser la connexion au démarrage de l'application
initialize_redis()