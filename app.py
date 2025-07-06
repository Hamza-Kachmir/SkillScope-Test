import pandas as pd
import logging
from nicegui import ui, app, run
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), 'src')))

from pipeline import get_skills_for_job
from src.cache_manager import delete_from_cache, flush_all_cache

job_input = None
offers_select = None
results_container = None
log_view = None

class UiLogHandler(logging.Handler):
    def __init__(self, log_element: ui.log):
        super().__init__()
        self.log_element = log_element

    def emit(self, record):
        msg = self.format(record)
        self.log_element.push(msg)

def format_skill_name(skill: str) -> str:
    known_acronyms = {'aws', 'gcp', 'sql', 'etl', 'api', 'rest', 'erp', 'crm', 'devops', 'qa', 'ux', 'ui', 'saas', 'cicd', 'kpi', 'sap'}
    if skill.lower() in known_acronyms:
        return skill.upper()
    return skill.capitalize()

def display_results(container: ui.column, results_dict: dict, job_title: str, num_offers: int):
    container.clear()
    
    skills_data = results_dict.get('skills', [])
    
    if not skills_data:
        with container:
            with ui.card().classes('w-full bg-yellow-100 p-4'):
                with ui.row().classes('items-center'):
                    ui.icon('warning', color='warning')
                    ui.label("Aucune compétence pertinente n'a pu être extraite.").classes('text-yellow-800 ml-2')
        return

    for item in skills_data:
        item['skill'] = format_skill_name(item['skill'])

    df_skills = pd.DataFrame(skills_data)
    df_skills.rename(columns={'skill': 'Compétence', 'frequency': 'Fréquence'}, inplace=True)
    df_skills.insert(0, 'Classement', range(1, len(df_skills) + 1))
    
    with container:
        with ui.row().classes('w-full items-center justify-between'):
            with ui.row(wrap=False).classes('items-center'):
                ui.label(f"📊 Résultats pour '{job_title}'").classes('text-2xl font-bold text-gray-800')
                ui.label(f"({num_offers} offres analysées)").classes('text-sm text-gray-500 ml-2')
            refresh_button = ui.button('Rafraîchir', icon='refresh', on_click=lambda: start_analysis(force_refresh=True))
            refresh_button.props('color=grey-6 flat dense')
            with ui.tooltip('Supprime les données du cache pour cette recherche et relance une nouvelle analyse.'):
                ui.icon('info', color='grey')

        with ui.row().classes('w-full justify-around mt-4 gap-4'):
            with ui.card().classes('items-center flex-grow'):
                ui.label('Compétences Uniques').classes('text-sm text-gray-500')
                ui.label(f"{len(df_skills)}").classes('text-4xl font-bold text-blue-600')
            with ui.card().classes('items-center flex-grow'):
                ui.label('Top Compétence').classes('text-sm text-gray-500')
                ui.label(df_skills.iloc[0]['Compétence']).classes('text-2xl font-bold text-center')
            with ui.card().classes('items-center flex-grow p-4'):
                ui.label('Fréquence Max').classes('text-sm text-gray-500')
                ui.label(f"{df_skills.iloc[0]['Fréquence']}").classes('text-2xl font-bold')
        
        ui.label("Classement détaillé des compétences").classes('text-xl font-bold mt-8 mb-2')
        filter_input = ui.input(placeholder="Filtrer...").props('dense outlined').classes('w-full')
        
        table = ui.table(
            columns=[
                {'name': 'Classement', 'label': '#', 'field': 'Classement', 'sortable': True, 'align': 'left'},
                {'name': 'Compétence', 'label': 'Compétence', 'field': 'Compétence', 'sortable': True, 'align': 'left'},
                {'name': 'Fréquence', 'label': 'Fréquence', 'field': 'Fréquence', 'sortable': True, 'align': 'left'},
            ],
            rows=df_skills.to_dict('records'),
            row_key='Compétence'
        ).props('flat bordered')
        
        table.bind_filter_from(filter_input, 'value')

async def perform_analysis_in_background(job_title: str, num_offers: int):
    """Contient la logique d'analyse longue, destinée à tourner en arrière-plan."""
    logger = logging.getLogger()
    
    try:
        results = await get_skills_for_job(job_title, num_offers, logger)
        if results is None:
            raise ValueError(f"Impossible de récupérer les compétences.")
        
        display_results(results_container, results, job_title, num_offers)

    except Exception as e:
        logger.error(f"Une erreur est survenue : {e}")
        results_container.clear()
        with results_container:
            with ui.card().classes('w-full bg-red-100 p-4'):
                with ui.row().classes('items-center'):
                    ui.icon('report_problem', color='negative')
                    ui.label(str(e)).classes('text-negative font-bold ml-2')

async def start_analysis(force_refresh: bool = False):
    """Prépare l'UI et lance la tâche d'analyse en arrière-plan."""
    if not all([job_input, offers_select, job_input.value, offers_select.value]):
        ui.notify("Veuillez entrer un métier et sélectionner un volume.", color='warning')
        return

    job_title = job_input.value
    num_offers = offers_select.value
    cache_key = f"{job_title.lower().strip()}@{num_offers}"
    
    if force_refresh:
        # Rafraîchir ne fait que supprimer du cache. L'analyse suivra.
        await run.io_bound(delete_from_cache, cache_key)

    results_container.clear()
    log_view.clear()
    
    logger = logging.getLogger()
    if not any(isinstance(h, UiLogHandler) for h in logger.handlers):
        logger.handlers.clear()
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        log_handler = UiLogHandler(log_view)
        log_handler.setFormatter(formatter)
        logger.addHandler(log_handler)

    with results_container:
        ui.spinner(size='lg', color='primary').classes('mx-auto')
        ui.label(f"Analyse de {num_offers} offres en cours...").classes('mx-auto text-gray-600')

    # Lance la tâche longue en arrière-plan sans bloquer
    app.add_background_task(perform_analysis_in_background, job_title, num_offers)

async def refresh_analysis(job_title_to_refresh: str, num_offers_to_refresh: int):
    job_input.value = job_title_to_refresh
    offers_select.value = num_offers_to_refresh
    await start_analysis(force_refresh=True)

async def handle_flush_cache():
    success = await run.io_bound(flush_all_cache)
    if success:
        ui.notify('Le cache a été entièrement vidé !', color='positive')
        results_container.clear()
    else:
        ui.notify('Erreur lors du vidage du cache.', color='negative')

@ui.page('/')
def main_page():
    global job_input, offers_select, results_container, log_view
    
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

        with ui.row().classes('w-full max-w-lg items-stretch gap-2'):
            job_input = ui.input(placeholder="Ex: Développeur Python...").props('outlined dense').classes('flex-grow')
            offers_select = ui.select({50: '50 offres', 100: '100 offres', 150: '150 offres'}, value=100, label='Volume').props('outlined dense')
        
        launch_button = ui.button('Lancer l\'analyse', on_click=lambda: start_analysis(force_refresh=False)).props('color=primary unelevated').classes('w-full max-w-lg mt-2')
        
        results_container = ui.column().classes('w-full mt-6')
        
        with ui.expansion("Voir les logs et Gérer le Cache", icon='code').classes('w-full mt-4'):
            log_view = ui.log().classes('w-full h-40 bg-gray-800 text-white font-mono text-xs')
            ui.button('Vider tout le cache', on_click=handle_flush_cache, color='negative').props('outline size=sm').classes('m-2')

    def check_inputs():
        return bool(job_input and job_input.value and offers_select and offers_select.value)
    
    ui.timer(0.1, lambda: launch_button.set_enabled(check_inputs()))

port = int(os.environ.get('PORT', 8080))
ui.run(host='0.0.0.0', port=port, title='SkillScope v4')