import spacy
import logging

try:
    nlp = spacy.load("fr_core_news_lg")
except OSError:
    logging.error("Modèle spaCy 'fr_core_news_lg' non trouvé. Assurez-vous qu'il est dans requirements.txt.")
    nlp = None

def extract_entities(text: str) -> set[str]:
    if not nlp or not text:
        return set()

    doc = nlp(text)
    
    entities = {ent.text.strip() for ent in doc.ents if len(ent.text.strip()) > 2}
    
    return entities