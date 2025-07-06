import redis
import json
import os
import logging

redis_client = None

def initialize_redis():
    global redis_client
    if redis_client:
        return

    redis_url = os.getenv('REDIS_URL')
    if not redis_url:
        logging.critical("La variable d'environnement REDIS_URL n'est pas définie !")
        return

    try:
        redis_client = redis.from_url(redis_url, decode_responses=True)
        redis_client.ping()
        logging.info("Connexion à Redis réussie.")
    except Exception as e:
        logging.error(f"Impossible de se connecter à Redis : {e}")
        redis_client = None

def get_cached_results(cache_key: str) -> dict | None:
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
    if redis_client is None: return
    try:
        value_to_store = json.dumps(results, ensure_ascii=False)
        redis_client.setex(cache_key, 2592000, value_to_store)
        logging.info(f"Cache WRITE for '{cache_key}'.")
    except Exception as e:
        logging.error(f"Erreur lors de l'écriture du cache Redis pour la clé '{cache_key}': {e}")

def delete_from_cache(cache_key: str):
    if redis_client is None: return
    try:
        redis_client.delete(cache_key)
        logging.info(f"CACHE DELETE for entry: '{cache_key}'.")
    except Exception as e:
        logging.error(f"Erreur lors de la suppression de la clé '{cache_key}' du cache Redis : {e}")

def flush_all_cache():
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

initialize_redis()