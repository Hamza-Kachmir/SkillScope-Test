# src/cache_manager.py
import redis
import json
import os
import logging

redis_client = None

def initialize_redis():
    global redis_client
    redis_url = os.getenv('REDIS_URL')
    if not redis_url:
        logging.error("La variable d'environnement REDIS_URL n'est pas définie !")
        return

    try:
        redis_client = redis.from_url(redis_url, decode_responses=True)
        redis_client.ping()
        logging.info("Connexion à Redis réussie.")
    except Exception as e:
        logging.error(f"Impossible de se connecter à Redis : {e}")
        redis_client = None

def get_cached_results(job_title: str) -> dict | None:
    if redis_client is None:
        return None

    normalized_title = job_title.lower().strip()

    try:
        cached_json = redis_client.get(normalized_title)
        if cached_json:
            return json.loads(cached_json)
        return None
    except Exception as e:
        logging.error(f"Erreur lors de la lecture du cache Redis : {e}")
        return None

def add_to_cache(job_title: str, results: dict):
    if redis_client is None:
        return

    normalized_title = job_title.lower().strip()

    try:
        value_to_store = json.dumps(results, ensure_ascii=False)
        # Expire après 30 jours
        redis_client.setex(normalized_title, 2592000, value_to_store)
    except Exception as e:
        logging.error(f"Erreur lors de l'écriture du cache Redis : {e}")

initialize_redis()