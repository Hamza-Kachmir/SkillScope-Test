import pandas as pd
import logging
from .france_travail_api import fetch_job_offers
from .skill_extractor import load_all_skills, extract_skills
from .log_handler import setup_logging

setup_logging()

def process_job_offers_pipeline(job_name, location_code):
    logging.info(f"Début du pipeline pour le métier : '{job_name}' à la localisation : '{location_code}'")
    
    df = fetch_job_offers(job_name, location_code)
    
    if df.empty:
        logging.warning("Aucune offre d'emploi trouvée. Le pipeline s'arrête.")
        return pd.DataFrame(), []

    logging.info(f"{len(df)} offres d'emploi récupérées.")
    
    hard_skills, soft_skills, languages = load_all_skills()
    logging.info("Chargement des bases de données de compétences (Hard, Soft, Languages) terminé.")
    
    def extractor_wrapper(description):
        return extract_skills(description, hard_skills, soft_skills, languages)
        
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