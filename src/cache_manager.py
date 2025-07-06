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

def get_cached_results(job_title: str) -> dict | None:
    if redis_client is None:
        return None
            
    normalized_title = job_title.lower().strip()
    
    try:
        cached_json = redis_client.get(normalized_title)
        if cached_json:
            logging.info(f"Cache HIT for '{normalized_title}'.")
            return json.loads(cached_json)
        logging.info(f"Cache MISS for '{normalized_title}'.")
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
        redis_client.setex(normalized_title, 2592000, value_to_store) # Expire après 30 jours
        logging.info(f"Cache WRITE for '{normalized_title}'.")
    except Exception as e:
        logging.error(f"Erreur lors de l'écriture du cache Redis : {e}")

def delete_from_cache(job_title: str):
    if redis_client is None:
        return
    
    normalized_title = job_title.lower().strip()
    try:
        redis_client.delete(normalized_title)
        logging.info(f"CACHE DELETE for entry: '{normalized_title}'.")
    except Exception as e:
        logging.error(f"Erreur lors de la suppression de la clé '{normalized_title}' du cache Redis : {e}")

def flush_all_cache():
    if redis_client is None:
        return
        
    try:
        redis_client.flushall()
        logging.info("CACHE FLUSH: Toutes les données ont été supprimées.")
        ui.notify('Le cache a été entièrement vidé !', color='positive')
    except Exception as e:
        logging.error(f"Erreur lors du vidage complet du cache Redis : {e}")
        ui.notify('Erreur lors du vidage du cache.', color='negative')

initialize_redis()