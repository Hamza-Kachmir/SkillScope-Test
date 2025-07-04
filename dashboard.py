import streamlit as st
import pandas as pd
import numpy as np
import base64
import os
import logging

# Import des fonctions du pipeline maintenant séparées
from src.pipeline import search_all_sources, process_offers
from src.log_handler import setup_log_capture

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
<em>Basé sur <strong>Welcome to the Jungle</strong> et enrichi avec <strong>France Travail</strong>.</em>
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

    # --- Logique de Lancement ---
    if launch_button:
        for key in ['df_results', 'error_message', 'log_messages']:
            if key in st.session_state: del st.session_state[key]
        st.session_state['job_title'] = job_to_scrape

        with setup_log_capture() as log_capture_stream:
            logger = logging.getLogger()
            
            # --- Étape 1 : Spinner pour la recherche ---
            with placeholder.container():
                with st.spinner(f"Recherche des offres pour **{job_to_scrape}**..."):
                    all_offers, cookies = search_all_sources(job_to_scrape, logger)

            # --- Étape 2 : Barre de progression pour l'analyse ---
            if all_offers:
                with placeholder.container():
                    progress_bar = st.progress(0, text="Analyse des compétences en cours... Patientez.")
                    def progress_callback(value):
                        text = f"Analyse des compétences en cours... Patientez. ({int(value * 100)}%)"
                        progress_bar.progress(value, text=text)
                    
                    df_results = process_offers(all_offers, cookies, progress_callback)
                    
                    if df_results is not None and not df_results.empty:
                        st.session_state['df_results'] = df_results
                    else:
                        st.session_state['error_message'] = "L'analyse a échoué ou aucune compétence n'a pu être extraite."
            else:
                st.session_state['error_message'] = f"Aucune offre trouvée pour '{job_to_scrape}'."

            st.session_state['log_messages'] = log_capture_stream.getvalue()
        st.rerun()

    # --- Logique d'Affichage ---
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
                c1, c2, c3 = st.columns(3)
                c1.metric("Offres Analysées", f"{len(df)}")
                c2.metric("Compétences Uniques", f"{len(skill_counts)}")
                c3.metric("Top Compétence", skill_counts.iloc[0]['Compétence'])
                st.subheader("Classement des compétences", anchor=False)
                search_skill = st.text_input("Rechercher une compétence :", placeholder="Ex: Python...", label_visibility="collapsed")
                if search_skill:
                    skill_counts_display = skill_counts[skill_counts['Compétence'].str.contains(search_skill, case=False, na=False)]
                else:
                    skill_counts_display = skill_counts
                st.dataframe(skill_counts_display, use_container_width=True, hide_index=True)
            else:
                st.warning("Aucune compétence n'a pu être extraite des offres analysées.")
        else:
            st.info("Lancez une analyse pour afficher les résultats !", icon="💡")

# --- Logs et Footer ---
st.markdown("---")
with st.expander("Voir les logs d'exécution", expanded=False):
    st.code(st.session_state.get('log_messages', "Aucun log pour le moment."), language='log')

st.markdown("---")
st.markdown("""
<div style="text-align: center; font-family: 'Source Sans Pro', sans-serif;">
    <p style="font-size: 0.9em;">Développé par <strong style="color: #2474c5;">Hamza Kachmir</strong></p>
    <p style="font-size: 1.1em;"><a href="https://portfolio-hamza-kachmir.vercel.app/" target="_blank" style="text-decoration: none; margin-right: 15px;"><strong style="color: #F9B15C;">Portfolio</strong></a><a href="https://www.linkedin.com/in/hamza-kachmir/" target="_blank" style="text-decoration: none;"><strong style="color: #F9B15C;">LinkedIn</strong></a></p>
</div>
""", unsafe_allow_html=True)