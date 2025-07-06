import streamlit as st
import pandas as pd
import numpy as np
import base64
import os
import logging
from src.pipeline import process_job_offers_pipeline
from src.log_handler import setup_log_capture

st.set_page_config(
    page_title="SkillScope | Analyseur de Compétences",
    page_icon="assets/SkillScope.svg",
    layout="wide"
)

st.markdown("""
<style>
    .main .block-container { padding-top: 2rem; padding-bottom: 2rem; }
</style>
""", unsafe_allow_html=True)

def load_svg(svg_file: str) -> str | None:
    if not os.path.exists(svg_file): return None
    with open(svg_file, "r", encoding="utf-8") as f: svg = f.read()
    return f"data:image/svg+xml;base64,{base64.b64encode(svg.encode('utf-8')).decode('utf-8')}"

logo_svg_base64 = load_svg("assets/SkillScope.svg")
if logo_svg_base64:
    st.markdown(f'<div style="text-align: center;"><img src="{logo_svg_base64}" width="300"></div>', unsafe_allow_html=True)
else:
    st.title("SkillScope")

st.markdown("""
<div style='text-align: center;'>
Un outil pour extraire et quantifier les compétences les plus demandées sur le marché.<br>
<em>Basé sur les données de <strong>France Travail</strong>.</em>
</div>
""", unsafe_allow_html=True)
st.markdown("---")

_left_margin, content_col, _right_margin = st.columns([0.2, 0.6, 0.2])

with content_col:
    col1, col2 = st.columns([3, 1])
    with col1:
        job_to_scrape = st.text_input("Quel métier analyser ?", placeholder="Ex: Data Engineer...", label_visibility="collapsed")
    with col2:
        launch_button = st.button("Lancer l'analyse", type="primary", use_container_width=True, disabled=(not job_to_scrape))
    
    placeholder = st.empty()

    if launch_button:
        for key in ['df_results', 'error_message', 'log_messages']:
            if key in st.session_state: del st.session_state[key]
        st.session_state['job_title'] = job_to_scrape

        with setup_log_capture() as log_capture_stream:
            # --- NOUVELLE LOGIQUE D'AFFICHAGE DE LA PROGRESSION ---
            progress_bar_placeholder = placeholder.empty()

            def progress_callback(value, text):
                progress_bar_placeholder.progress(value, text=text)

            # Appel au pipeline en passant la fonction de callback
            df_results, _ = process_job_offers_pipeline(job_to_scrape, "", progress_callback=progress_callback)
            # --- FIN DE LA NOUVELLE LOGIQUE ---

            if df_results is not None and not df_results.empty:
                df_results.rename(columns={'competences_uniques': 'tags'}, inplace=True)
                st.session_state['df_results'] = df_results
            else:
                st.session_state['error_message'] = f"Aucune offre trouvée ou analysée pour '{job_to_scrape}'."

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
                st.warning("Aucune compétence n'a pu être extraite des offres analysées pour ce métier.")
        else:
            st.info("Lancez une analyse pour afficher les résultats !", icon="💡")

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