import pandas as pd
import numpy as np
import logging
from typing import List, Dict
import os

# On importe 'run_in_executor' directement
from nicegui import ui, app, run_in_executor

# Importe les fonctions de ton pipeline
from src.pipeline import search_france_travail_offers, process_offers

# --- Logique applicative (déplacée en dehors de la fonction de page) ---

class UiLogHandler(logging.Handler):
    """Un handler de logging qui écrit les messages dans un élément ui.log."""
    def __init__(self, log_element: ui.log):
        super().__init__()
        self.log_element = log_element

    def emit(self, record):
        msg = self.format(record)
        self.log_element.push(msg)

def display_results(container: ui.column, df: pd.DataFrame, job_title: str):
    """Fonction pour afficher les résultats dans un conteneur donné."""
    container.clear()
    with container:
        ui.label(f"📊 Résultats pour : {job_title}").classes('text-2xl font-bold text-gray-800')

        tags_exploded = df['tags'].explode().dropna()
        skill_counts = tags_exploded.value_counts().reset_index()
        skill_counts.columns = ['Compétence', 'Fréquence']
        skill_counts.insert(0, 'Classement', range(1, len(skill_counts) + 1))

        # Cartes de métriques
        with ui.row().classes('w-full justify-around mt-4 gap-4'):
            with ui.card().classes('items-center flex-grow'):
                ui.label('Offres avec compétences').classes('text-sm text-gray-500')
                ui.label(f"{len(df)}").classes('text-4xl font-bold text-blue-600')
            with ui.card().classes('items-center flex-grow'):
                ui.label('Compétences Uniques').classes('text-sm text-gray-500')
                ui.label(f"{len(skill_counts)}").classes('text-4xl font-bold text-blue-600')
            with ui.card().classes('items-center flex-grow p-4'):
                ui.label('Top Compétence').classes('text-sm text-gray-500')
                ui.label(skill_counts.iloc[0]['Compétence']).classes('text-2xl font-bold text-center')
        
        # Tableau des résultats
        ui.label("Classement détaillé des compétences").classes('text-xl font-bold mt-8 mb-2')
        filter_input = ui.input(placeholder="Filtrer les compétences...").props('dense outlined').classes('w-full')
        
        table = ui.table(
            columns=[
                {'name': 'Classement', 'label': '#', 'field': 'Classement', 'sortable': True, 'align': 'left'},
                {'name': 'Compétence', 'label': 'Compétence', 'field': 'Compétence', 'sortable': True, 'align': 'left'},
                {'name': 'Fréquence', 'label': 'Fréquence', 'field': 'Fréquence', 'sortable': True, 'align': 'left'},
            ],
            rows=skill_counts.to_dict('records'),
            row_key='Compétence'
        ).props('flat bordered')
        
        table.bind_filter_from(filter_input, 'value')

async def run_analysis_logic(job_input: ui.input, results_container: ui.column, log_view: ui.log):
    """Fonction principale qui orchestre l'analyse."""
    job_title = job_input.value
    if not job_title:
        return

    # 1. Préparer l'UI
    results_container.clear()
    log_view.clear()
    
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    logger.addHandler(UiLogHandler(log_view))

    with results_container:
        ui.spinner(size='lg', color='primary').classes('mx-auto')
        progress_label = ui.label("Recherche des offres...").classes('mx-auto text-gray-600')
        progress_bar = ui.linear_progress(0).props('color=primary')

    try:
        # 2. Lancer la recherche (on utilise 'run_in_executor' directement)
        all_offers = await run_in_executor(search_france_travail_offers, job_title, logger)
        if not all_offers:
            raise ValueError(f"Aucune offre n'a été trouvée pour '{job_title}' sur France Travail.")

        # 3. Lancer le traitement
        progress_label.text = "Analyse des compétences en cours..."
        def progress_callback(value: float):
            progress_bar.set_value(value)

        df_results = await run_in_executor(process_offers, all_offers, progress_callback)
        if df_results is None or df_results.empty:
            raise ValueError("L'analyse a échoué ou aucune compétence pertinente n'a pu être extraite.")
        
        # 4. Afficher les résultats
        display_results(results_container, df_results, job_title)

    except Exception as e:
        logger.error(f"Une erreur est survenue : {e}")
        results_container.clear()
        with results_container:
            with ui.card().classes('w-full bg-red-100 p-4'):
                with ui.row().classes('items-center'):
                    ui.icon('report_problem', color='negative')
                    ui.label(str(e)).classes('text-negative font-bold ml-2')

# --- Définition de la Page (UI) ---
@ui.page('/')
def main_page():
    # Configuration de la page
    app.add_static_files('/assets', 'assets')
    ui.query('body').style('background-color: #f5f5f5;')

    # Header
    with ui.header(elevated=True).classes('bg-white text-black items-center px-4 py-2'):
        with ui.row().classes('w-full items-center justify-between'):
            ui.image('/assets/SkillScope.svg').classes('w-40')
            with ui.row().classes('items-center'):
                ui.link('Portfolio', 'https://portfolio-hamza-kachmir.vercel.app/', new_tab=True).classes('text-gray-600 hover:text-blue-700')
                ui.link('LinkedIn', 'https://www.linkedin.com/in/hamza-kachmir/', new_tab=True).classes('ml-4 text-gray-600 hover:text-blue-700')

    # Conteneur principal
    with ui.column().classes('w-full max-w-4xl mx-auto p-4 items-center gap-4'):
        ui.markdown("## Analysez les compétences clés d'un métier").classes('text-3xl text-center font-light text-gray-800')
        ui.markdown("_Basé sur les données en temps réel de **France Travail** et du référentiel **ESCO**._").classes('text-center text-gray-500 mb-6')

        # Barre de recherche
        with ui.row().classes('w-full max-w-lg items-center gap-2'):
            job_input = ui.input(placeholder="Ex: Développeur Python, Chef de projet...").props('outlined dense').classes('flex-grow')
            
            # La zone pour les résultats et les logs est définie ici
            results_container = ui.column().classes('w-full mt-6')
            with ui.expansion("Voir les logs d'exécution", icon='code').classes('w-full mt-4'):
                log_view = ui.log().classes('w-full h-40 bg-gray-800 text-white font-mono text-xs')

            # Le bouton est créé en dernier, et on utilise une lambda pour connecter les éléments
            ui.button('Lancer l\'analyse', on_click=lambda: run_analysis_logic(job_input, results_container, log_view)) \
                .props('color=primary unelevated') \
                .bind_enabled_from(job_input, 'value', bool)

# --- Point d'entrée pour lancer l'application ---
port = int(os.environ.get('PORT', 10000))
ui.run(host='0.0.0.0', port=port, title='SkillScope')
