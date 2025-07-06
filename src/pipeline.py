import pandas as pd
import logging
import streamlit as st
import re
from src.france_travail_api import FranceTravailClient
from src.skill_extractor import load_all_skills, extract_skills

def get_job_offers(job_name: str) -> pd.DataFrame:
    logger = logging.getLogger(__name__)
    try:
        client_id = st.secrets["FRANCE_TRAVAIL_CLIENT_ID"]
        client_secret = st.secrets["FRANCE_TRAVAIL_CLIENT_SECRET"]
    except KeyError:
        logger.critical("Les secrets 'FRANCE_TRAVAIL_CLIENT_ID' et/ou 'FRANCE_TRAVAIL_CLIENT_SECRET' ne sont pas configurés.")
        st.error("Les clés API ne sont pas configurées dans les secrets de l'application.")
        return pd.DataFrame()

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
    return pd.DataFrame(processed_offers)


def process_job_offers_pipeline(job_name, location_code):
    logging.info(f"Début du pipeline pour le métier : '{job_name}'")
    
    df = get_job_offers(job_name)
    
    if df.empty:
        logging.warning("Aucune offre d'emploi trouvée. Le pipeline s'arrête.")
        return pd.DataFrame(), []

    logging.info(f"{len(df)} offres d'emploi récupérées.")
    
    hard_skills, soft_skills, languages = load_all_skills()
    logging.info("Chargement des bases de données de compétences terminé.")

    logging.info("Compilation des patterns Regex en cours...")
    hard_skills_pattern = re.compile(r'\b(' + '|'.join(re.escape(s) for s in hard_skills) + r')\b', re.IGNORECASE)
    soft_skills_pattern = re.compile(r'\b(' + '|'.join(re.escape(s) for s in soft_skills) + r')\b', re.IGNORECASE)
    languages_pattern = re.compile(r'\b(' + '|'.join(re.escape(s) for s in languages) + r')\b', re.IGNORECASE)
    logging.info("Compilation terminée.")
    
    def extractor_wrapper(description):
        return extract_skills(description, hard_skills_pattern, soft_skills_pattern, languages_pattern)
        
    df['skills_found'] = df['description'].apply(extractor_wrapper)
    
    df['hard_skills'] = df['skills_found'].apply(lambda x: x['hard'])
    df['soft_skills'] = df['skills_found'].apply(lambda x: x['soft'])
    df['languages'] = df['skills_found'].apply(lambda x: x['language'])
    
    total_hard_skills = df['hard_skills'].explode().nunique()
    total_soft_skills = df['soft_skills'].explode().nunique()
    total_languages = df['languages'].explode().nunique()

    logging.info(f"Extraction terminée :")
    logging.info(f"-> {total_hard_skills} compétences 'Hard Skills' uniques trouvées.")
    logging.info(f"-> {total_soft_skills} compétences 'Soft Skills' uniques trouvées.")
    logging.info(f"-> {total_languages} compétences 'Languages' uniques trouvées.")
    
    df['competences_uniques'] = df.apply(lambda row: sorted(list(set(row['hard_skills'] + row['soft_skills'] + row['languages']))), axis=1)
    
    all_skills_list = df['competences_uniques'].explode().dropna().unique().tolist()
    
    df_final = df[['id', 'intitule', 'entreprise_nom', 'type_contrat', 'url', 'competences_uniques']].copy()
    
    logging.info(f"Pipeline terminé. {len(df_final)} offres traitées. {len(all_skills_list)} compétences uniques au total identifiées.")
    
    return df_final, sorted(all_skills_list)