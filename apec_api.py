import requests
import logging

API_URL = "https://www.apec.fr/cms/webservices/rechercheOffre"
BASE_URL = "https://www.apec.fr"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Content-Type": "application/json"
}

def search_apec_offers(search_term: str, num_offers: int = 200) -> list[dict]: # Modifié à 200 offres pour simuler 10 pages de 20
    """
    Interroge directement l'API de l'APEC pour récupérer les offres et leur description.
    Augmente le nombre d'offres pour obtenir un équivalent de plusieurs pages.
    """
    payload = {
        "motsCles": search_term,
        "pagination": { "range": num_offers, "startIndex": 0 },
        "sorts": [{ "type": "SCORE", "direction": "DESCENDING" }]
    }

    try:
        logging.info(f"APEC : Appel de l'API via requests POST sur {API_URL}")
        response = requests.post(API_URL, headers=HEADERS, json=payload, timeout=15)
        response.raise_for_status()
        data = response.json()

        all_offers = []
        for offer in data.get("resultats", []):
            offer_id = offer.get("id")
            if not offer_id: continue

            detail_url = f"{BASE_URL}/candidat/recherche-emploi.html/emploi/detail-offre/{offer_id}"
            
            all_offers.append({
                "titre": offer.get("intitule"),
                "entreprise": offer.get("nomCommercial"),
                "url": detail_url,
                "description": offer.get("texteOffre"),
                "tags": []
            })
        return all_offers

    except requests.exceptions.RequestException as e:
        logging.error(f"APEC : Erreur lors de l'appel API. {e}")
        return []