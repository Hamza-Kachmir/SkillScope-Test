import pandas as pd
import logging
from nicegui import ui, app, run
import os
import sys

# Ajout du chemin src pour que les imports fonctionnent
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), 'src')))

from pipeline import get_skills_for_job

class UiLogHandler(logging.Handler):
    def __init__(self, log_element: ui.log):
        super().__init__()
        self.log_element = log_element

    def emit(self, record):
        msg = self.format(record)
        self.log_element.push(msg)

def display_results(container: ui.column, results_dict: dict, job_title: str):
    container.clear()
    
    all_skills = (
        results_dict.get('hard_skills', []) + 
        results_dict.get('soft_skills', []) + 
        results_dict.get('languages', [])
    )
    
    if not all_skills:
        with container:
            ui.warning("Aucune compétence n'a pu être extraite pour ce métier.")
        return

    tags_exploded = pd.Series(all_skills).dropna()
    skill_counts = tags_exploded.value_counts().reset_index()
    skill_counts.columns = ['Compétence', 'Fréquence']
    skill_counts.insert(0, 'Classement', range(1, len(skill_counts) + 1))
    
    with container:
        ui.label(f"📊 Résultats pour : {job_title}").classes('text-2xl font-bold text-gray-800')

        with ui.row().classes('w-full justify-around mt-4 gap-4'):
            with ui.card().classes('items-center flex-grow'):
                ui.label('Hard Skills').classes('text-sm text-gray-500')
                ui.label(f"{len(results_dict.get('hard_skills', []))}").classes('text-4xl font-bold text-blue-600')
            with ui.card().classes('items-center flex-grow'):
                ui.label('Soft Skills').classes('text-sm text-gray-500')
                ui.label(f"{len(results_dict.get('soft_skills', []))}").classes('text-4xl font-bold text-green-600')
            with ui.card().classes('items-center flex-grow'):
                ui.label('Langues').classes('text-sm text-gray-500')
                ui.label(f"{len(results_dict.get('languages', []))}").classes('text-4xl font-bold text-purple-600')
        
        ui.label("Classement détaillé des compétences").classes('text-xl font-bold mt-8 mb-2')
        filter_input = ui.input(placeholder="Filtrer...").props('dense outlined').classes('w-full')
        
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
    job_title = job_input.value
    if not job_title:
        return

    results_container.clear()
    log_view.clear()
    
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    
    # Vider les anciens handlers pour éviter les logs multiples
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    log_handler = UiLogHandler(log_view)
    log_handler.setFormatter(formatter)
    logger.addHandler(log_handler)

    with results_container:
        ui.spinner(size='lg', color='primary').classes('mx-auto')
        ui.label("Analyse en cours... (peut prendre jusqu'à 30 secondes)").classes('mx-auto text-gray-600')

    try:
        results = await get_skills_for_job(job_title, logger)
        
        if results is None:
            raise ValueError(f"Impossible de récupérer les compétences pour '{job_title}'.")
        
        display_results(results_container, results, job_title)

    except Exception as e:
        logger.error(f"Une erreur est survenue : {e}")
        results_container.clear()
        with results_container:
            with ui.card().classes('w-full bg-red-100 p-4'):
                with ui.row().classes('items-center'):
                    ui.icon('report_problem', color='negative')
                    ui.label(str(e)).classes('text-negative font-bold ml-2')

@ui.page('/')
def main_page():
    app.add_static_files('/assets', 'assets')
    ui.query('body').style('background-color: #f5f5f5;')

    with ui.header(elevated=True).classes('bg-white text-black items-center px-4 py-2'):
        with ui.row().classes('w-full items-center justify-between'):
            ui.image('/assets/SkillScope.svg').classes('w-40')
            with ui.row().classes('items-center'):
                ui.link('Portfolio', 'https://portfolio-hamza-kachmir.vercel.app/', new_tab=True).classes('text-gray-600 hover:text-blue-700')
                ui.link('LinkedIn', 'https://www.linkedin.com/in/hamza-kachmir/', new_tab=True).classes('ml-4 text-gray-600 hover:text-blue-700')

    with ui.column().classes('w-full max-w-4xl mx-auto p-4 items-center gap-4'):
        ui.markdown("## Analysez les compétences clés d'un métier").classes('text-3xl text-center font-light text-gray-800')
        ui.markdown("_Basé sur les données de **France Travail** et l'analyse de **Google Gemini**._").classes('text-center text-gray-500 mb-6')

        with ui.row().classes('w-full max-w-lg items-center gap-2'):