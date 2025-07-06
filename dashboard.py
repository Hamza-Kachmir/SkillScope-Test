import streamlit as st
import sys
import os
import pandas as pd
import base64
import logging

# LIGNES IMPORTANTES : Ajoutent la racine du projet au chemin de Python pour résoudre les imports
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

# Imports de vos modules qui vont maintenant fonctionner
from src.pipeline import search_france_travail_offers, process_offers
from src.log_handler import setup_log_capture

# --- Configuration de la page Streamlit ---
st.set_page_config(
    page_title="SkillScope | Analyseur de Compétences",
    page_icon="assets/SkillScope.svg", # Assurez-vous d'avoir ce chemin
    layout="wide"
)

# --- Styles CSS ---
st.markdown("""
<style>
    .main .block-container { padding-top: 2rem; padding-bottom: 2rem; }
    .st-emotion-cache-1y4p8pa { padding-top: 4rem; } /* Ajuste le padding du haut */
</style>
""", unsafe_allow_html=True)


# --- Fonctions Utilitaires ---
def load_svg(svg_file: str) -> str | None:
    """Charge un fichier SVG et le convertit en base64 pour l'affichage."""
    if not os.path.exists(svg_file):
        logging.warning(f"Le fichier SVG '{svg_file}' est introuvable.")
        return None
    with open(svg_file, "r", encoding="utf-8") as f:
        svg = f.read()
    b64 = base64.b64encode(svg.encode("utf-8")).decode("utf-8")
    return f"data:image/svg+xml;base64,{b64}"

def display_dataframe(df: pd.DataFrame):
    """Affiche le DataFrame avec une mise en forme spécifique."""
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "URL": st.column_config.LinkColumn(
                "Voir l'offre",
                display_text="🔗 Lien"
            ),
            "Hardskills": st.column_config.TextColumn("Hard Skills", width="large"),
            "Softskills": st.column_config.TextColumn("Soft Skills", width="large"),
            "Langues": st.column_config.TextColumn("Langues", width="medium"),
        }
    )

# --- Interface Principale ---
logo_svg = load_svg("assets/SkillScope.svg")
if logo_svg:
    st.markdown(f'<div style="text-align: center;"><img src="{logo_svg}" width="300"></div>', unsafe_allow_html=True)
else:
    st.title("SkillScope")

st.markdown("<h2 style='text-align: center;'>Analyseur de Compétences IA pour les Offres d'Emploi</h2>", unsafe_allow_html=True)

search_term = st.text_input(
    "Entrez un code ROME, un métier ou un mot-clé",
    placeholder="Ex: M1805, développeur web, data analyst...",
    label_visibility="collapsed"
)

if st.button("Analyser les compétences", use_container_width=True):
    if not search_term:
        st.warning("Veuillez saisir un terme de recherche.")
    else:
        with st.spinner("Recherche des offres en cours..."):
            # Zone pour afficher les logs
            log_container = st.expander("Afficher les journaux d'exécution")
            log_box = log_container.empty()
            log_handler, log_stream = setup_log_capture()
            
            # Phase 1: Recherche des offres
            offers = search_france_travail_offers(search_term, log_handler.logger)
            log_box.text(log_stream.getvalue()) # Met à jour les logs

        if not offers:
            st.error("Aucune offre n'a été trouvée pour ce terme. Veuillez essayer un autre mot-clé.")
        else:
            st.success(f"{len(offers)} offres trouvées ! Lancement de l'analyse des compétences...")
            progress_bar = st.progress(0, text="Analyse en cours...")

            def update_progress(percentage):
                progress_bar.progress(percentage, text=f"Analyse en cours... {int(percentage*100)}%")

            # Phase 2: Traitement des offres
            df_results = process_offers(offers, update_progress)
            log_box.text(log_stream.getvalue()) # Met à jour les logs

            progress_bar.empty() # Supprime la barre de progression

            if df_results is not None and not df_results.empty:
                st.subheader("🔥 Compétences extraites des offres d'emploi")
                display_dataframe(df_results)
            else:
                st.warning("L'analyse n'a retourné aucune compétence. Les descriptions d'offres étaient peut-être trop courtes.")