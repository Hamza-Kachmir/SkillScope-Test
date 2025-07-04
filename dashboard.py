import streamlit as st
import pandas as pd
import base64
import os
from src.pipeline import search_all_sources, process_offers # Noms des fonctions corrigés pour correspondre à pipeline.py
from src.log_handler import setup_log_capture

# Configuration de la page Streamlit.
st.set_page_config(
    page_title="SkillScope | Analyseur de Compétences",
    page_icon="assets/SkillScope.svg",
    layout="wide"
)

# Injection de CSS pour les marges.
st.markdown("""
<style>
    .main .block-container { padding-top: 2rem; padding-bottom: 2rem; }
</style>
""", unsafe_allow_html=True)

# Charge une image SVG pour l'affichage.
def load_svg(svg_file: str) -> str | None:
    if not os.path.exists(svg_file): return None
    with open(svg_file, "r", encoding="utf-8") as f: svg = f.read()
    svg_base64 = base64.b64encode(svg.encode('utf-8')).decode('utf-8')
    return f"data:image/svg+xml;base64,{svg_base64}"

# Affiche le logo et le titre.
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
""", unsafe_allow_html=True) # Texte mis à jour : "Welcome to the Jungle" remplacé par "APEC"
st.markdown("---")

# Centre le contenu de la page.
_left_margin, content_col, _right_margin = st.columns([0.2, 0.6, 0.2])

with content_col:
    # Barre de recherche et bouton de lancement.
    col1, col2 = st.columns([3, 1])
    with col1:
        job_to_scrape = st.text_input("Quel métier analyser ?", placeholder="Ex: Data Engineer...", label_visibility="collapsed")
    with col2:
        launch_button = st.button("Lancer l'analyse", type="primary", use_container_width=True, disabled=(not job_to_scrape))
    
    # Conteneur dynamique pour afficher les résultats ou les indicateurs de chargement.
    placeholder = st.empty()
    
    # Logique exécutée au clic sur le bouton.
    if launch_button:
        # Nettoie la session pour une nouvelle analyse.
        for key in ['df_results', 'error_message', 'log_messages']: # Correction: Nettoyage spécifique des clés importantes
            if key in st.session_state: del st.session_state[key]
        st.session_state['job_title'] = job_to_scrape
        
        # Capture les logs et affiche les indicateurs de chargement dans le placeholder.
        with placeholder.container(), setup_log_capture() as log_capture_stream:
            # Spinner pour la phase de recherche.
            with st.spinner(f"Recherche des offres pour **{job_to_scrape}**..."):
                # Utilisation de search_all_sources (comme défini dans pipeline.py)
                offers_metadata, _ = search_all_sources(job_to_scrape) # Suppression de 'cookies' car WTTJ est retiré
            
            # Si la recherche a trouvé des offres, on lance l'analyse.
            if offers_metadata:
                progress_text = "Analyse des compétences en cours... Patientez."
                progress_bar = st.progress(0, text=progress_text)
                
                # Fonction pour mettre à jour la barre de progression depuis le pipeline.
                def progress_callback(progress_percentage):
                    progress_bar.progress(progress_percentage, text=f"{progress_text} ({int(progress_percentage * 100)}%)")
                
                # Utilisation de process_offers (comme défini dans pipeline.py), plus besoin de cookies
                df_results = process_offers(offers_metadata, None, progress_callback) 
                
                # Stocke les résultats dans la session pour les afficher après le rerun.
                if df_results is not None and not df_results.empty:
                    st.session_state['df_results'] = df_results
                else:
                    st.session_state['error_message'] = "L'analyse a échoué ou aucune compétence n'a pu être extraite."
            else:
                st.session_state['error_message'] = f"Aucune offre d'emploi n'a été trouvée pour '{job_to_scrape}'."
            
            # Sauvegarde les logs dans la session.
            st.session_state['log_messages'] = log_capture_stream.getvalue()
        
        # Ré-exécute le script pour afficher les résultats.
        st.rerun()
        
    # Affiche une erreur ou les résultats stockés en session.
    with placeholder.container():
        if 'error_message' in st.session_state:
            st.error(st.session_state['error_message'], icon="🚨")
        elif 'df_results' in st.session_state:
            df = st.session_state['df_results']
            job_title = st.session_state.get('job_title', 'le métier analysé')
            
            st.subheader(f"📊 Résultats de l'analyse pour : {job_title}", anchor=False)
            
            # On compte la fréquence de chaque compétence.
            tags_exploded = df['tags'].explode().dropna()
            
            if not tags_exploded.empty:
                skill_counts = tags_exploded.value_counts().reset_index()
                skill_counts.columns = ['Compétence', 'Fréquence']
                skill_counts.insert(0, 'Classement', range(1, len(skill_counts) + 1))
                
                # Affiche les métriques principales.
                col1, col2, col3 = st.columns(3)
                col1.metric("Offres Analysées", f"{len(df)}")
                col2.metric("Compétences Uniques", f"{len(skill_counts)}")
                col3.metric("Top Compétence", skill_counts.iloc[0]['Compétence'])
                
                # Affiche le tableau des compétences.
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
            # Message par défaut au lancement.
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
    <p style="font-size: 1.1em;">
        <a href="https://portfolio-hamza-kachmir.vercel.app/" target="_blank" style="text-decoration: none; margin-right: 15px;"><strong style="color: #F9B15C;">Portfolio</strong></a>
        <a href="https://www.linkedin.com/in/hamza-kachmir/" target="_blank" style="text-decoration: none;"><strong style="color: #F9B15C;">LinkedIn</strong></a>
    </p>
</div>
""", unsafe_allow_html=True)