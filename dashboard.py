import streamlit as st
import pandas as pd
import numpy as np
import base64
import os
import logging

# Import des fonctions du pipeline maintenant séparées
from src.pipeline import search_all_sources, process_offers
from src.log_handler import setup_log_capture
# Suppression de l'import de apec_api car sa logique est maintenant dans scraper.py
# from src.apec_api import test_single_url_apec_extraction # NOUVEL IMPORT pour le test APEC
from src.scraper import APECScraper, get_apec_job_details # Ré-import de la fonction de test si besoin

# --- Configuration de la Page ---
st.set_page_config(
    page_title="SkillScope | Analyseur de Compétences",
    page_icon="assets/SkillScope.svg",
    layout="wide"
)

# --- CSS Personnalisé ---
st.markdown("""
<style>
    .main .block-container { padding-top: 2rem; padding-bottom: 2rem; }
</style>
""", unsafe_allow_html=True)

# --- Fonctions Utilitaires ---
def load_svg(svg_file: str) -> str | None:
    if not os.path.exists(svg_file): return None
    with open(svg_file, "r", encoding="utf-8") as f: svg = f.read()
    return f"data:image/svg+xml;base64,{base64.b64encode(svg.encode('utf-8')).decode('utf-8')}"

# --- Interface Statique ---
logo_svg_base64 = load_svg("assets/SkillScope.svg")
if logo_svg_base64:
    st.markdown(f'<div style="text-align: center;"><img src="{logo_svg_base64}" width="300"></div>', unsafe_allow_html=True)
else:
    st.title("SkillScope")

st.markdown("""
<div style='text-align: center;'>
Un outil pour extraire et quantifier les compétences les plus demandées sur le marché.<br>
<em>Analyse basée sur les offres de <strong>APEC</strong> et <strong>France Travail</strong>.</em>
</div>
""", unsafe_allow_html=True)
st.markdown("---")

# --- Conteneur principal ---
_left_margin, content_col, _right_margin = st.columns([0.2, 0.6, 0.2])

with content_col:
    # --- Barre de recherche ---
    col1, col2 = st.columns([3, 1])
    with col1:
        job_to_scrape = st.text_input("Quel métier analyser ?", placeholder="Ex: Data Engineer...", label_visibility="collapsed")
    with col2:
        launch_button = st.button("Lancer l'analyse", type="primary", use_container_width=True, disabled=(not job_to_scrape))
    
    placeholder = st.empty()

    # --- Bloc de test temporaire pour l'extraction APEC (À retirer après le débogage) ---
    st.markdown("---")
    st.subheader("Test d'Extraction APEC (DEBUG)")
    test_url = "https://www.apec.fr/candidat/recherche-emploi.html/emploi/detail-offre/176643425W?motsCles=ux%20d%C3%A9signer&typesConvention=143684&typesConvention=143685&typesConvention=143686&typesConvention=143687&page=0&selectedIndex=0"
    if st.button("Lancer le test sur l'URL APEC spécifique"):
        for key in ['test_log_messages', 'extracted_skills_test']: 
            if key in st.session_state: del st.session_state[key]
        with st.spinner("Extraction des compétences depuis l'URL APEC de test..."):
            with setup_log_capture() as log_capture_stream_test:
                # Appeler directement la fonction de détail APEC avec les cookies d'une session bidon si nécessaire
                # Ou la rendre testable sans cookies pour ce cas de débogage
                # Pour l'instant, on fait un appel direct sans se préoccuper des cookies ici pour le test unique
                # Si get_apec_job_details a besoin de cookies, ce test sera limité.
                # Une meilleure approche serait d'avoir APECScraper.search_and_scrape_job_urls pour un test complet.
                # Pour ce test unitaire, on peut simuler les cookies si nécessaire ou laisser la fonction les gérer en interne.
                # Pour la démonstration, on va juste appeler get_apec_job_details avec une liste de cookies vide.
                extracted_skills = get_apec_job_details(test_url, []) # Simule l'appel avec des cookies vides
                st.session_state['extracted_skills_test'] = extracted_skills['tags'] # Les tags sont dans le dictionnaire retourné
                st.session_state['test_log_messages'] = log_capture_stream_test.getvalue()
        st.rerun()

    if 'extracted_skills_test' in st.session_state:
        st.write(f"Compétences extraites de l'URL de test: {st.session_state['extracted_skills_test']}")
    if 'test_log_messages' in st.session_state:
        with st.expander("Logs du test d'extraction APEC"):
            st.code(st.session_state['test_log_messages'], language='log')
    st.markdown("---")
    # --- Fin du bloc de test temporaire ---


    # Logique exécutée au clic sur le bouton de lancement principal
    if launch_button:
        # Nettoie la session pour une nouvelle analyse.
        for key in ['df_results', 'error_message', 'log_messages', 'test_log_messages', 'extracted_skills_test']: 
            if key in st.session_state: del st.session_state[key]
        st.session_state['job_title'] = job_to_scrape

        with placeholder.container(), setup_log_capture() as log_capture_stream:
            # Spinner pour la phase de recherche.
            with st.spinner(f"Recherche des offres pour **{job_to_scrape}**..."):
                # search_all_sources retourne maintenant les offres et les cookies APEC de Selenium
                all_offers, apec_cookies = search_all_sources(job_to_scrape) 

            # Si la recherche a trouvé des offres, on lance l'analyse.
            if all_offers:
                progress_text = "Analyse des compétences en cours... Patientez."
                progress_bar = st.progress(0, text=progress_text)

                def progress_callback(progress_percentage):
                    progress_bar.progress(progress_percentage, text=f"{progress_text} ({int(progress_percentage * 100)}%)")

                # On passe les cookies APEC récupérés par Selenium à process_offers
                df_results = process_offers(all_offers, apec_cookies, progress_callback)

                if df_results is not None and not df_results.empty:
                    st.session_state['df_results'] = df_results
                else:
                    st.session_state['error_message'] = "L'analyse a échoué ou aucune compétence n'a pu être extraite."
            else:
                st.session_state['error_message'] = f"Aucune offre d'emploi n'a été trouvée pour '{job_to_scrape}'."

            st.session_state['log_messages'] = log_capture_stream.getvalue()

        st.rerun()

    with placeholder.container():
        if 'error_message' in st.session_state:
            st.error(st.session_state['error_message'], icon="🚨")
        elif 'df_results' in st.session_state:
            df = st.session_state['df_results']
            job_title = st.session_state.get('job_title', 'le métier analysé')

            st.subheader(f"📊 Résultats de l'analyse pour : {job_title}", anchor=False)

            tags_exploded = df['tags'].explode().dropna()

            if not tags_exploded.empty:
                skill_counts = tags_exploded.value_counts().reset_index()
                skill_counts.columns = ['Compétence', 'Fréquence']
                skill_counts.insert(0, 'Classement', range(1, len(skill_counts) + 1))

                col1, col2, col3 = st.columns(3)
                col1.metric("Offres Analysées", f"{len(df)}")
                col2.metric("Compétences Uniques", f"{len(skill_counts)}")
                col3.metric("Top Compétence", skill_counts.iloc[0]['Compétence'])

                st.subheader("Classement des compétences", anchor=False)
                search_skill = st.text_input("Rechercher une compétence :", placeholder="Ex: Power BI...", label_visibility="collapsed")
                if search_skill:
                    skill_counts_display = skill_counts[skill_counts['Compétence'].str.contains(search_skill, case=False, na=False)]
                else:
                    skill_counts_display = skill_counts

                st.dataframe(skill_counts_display, use_container_width=True, hide_index=True)
            else:
                st.warning("Aucune compétence n'a pu être extraite des offres analysées.")
        else:
            st.info("Lancez une analyse pour afficher les résultats.", icon="💡")

# Afficheur de logs en bas de page.
st.markdown("---")
with st.expander("Voir les logs d'exécution", expanded=False):
    logs = st.session_state.get('log_messages', '')
    if logs: st.code(logs, language='log')
    else: st.text("Aucun log à afficher pour le moment.")

# Footer.
st.markdown("---")
st.markdown("""
<div style="text-align: center; font-family: 'Source Sans Pro', sans-serif; margin-top: 40px;">
    <p style="font-size: 0.9em; margin-bottom: 10px;">Développé par <strong style="color: #2474c5;">Hamza Kachmir</strong></p>
    <p style="font-size: 1.1em;"><a href="https://portfolio-hamza-kachmir.vercel.app/" target="_blank" style="text-decoration: none; margin-right: 15px;"><strong style="color: #F9B15C;">Portfolio</strong></a><a href="https://www.linkedin.com/in/hamza-kachmir/" target="_blank" style="text-decoration: none;"><strong style="color: #F9B15C;">LinkedIn</strong></a></p>
</div>
""", unsafe_allow_html=True)