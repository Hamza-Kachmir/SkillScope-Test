# FICHIER : app.py (contenu mis à jour)
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

def display_results(container: ui.column, results_dict: dict, job_title: str):
    container.clear()
    
    skills_data = results_dict.get('skills', [])
    top_diploma = results_dict.get('top_diploma', 'Non précisé')
    # On récupère le nombre réel d'offres
    actual_offers = results_dict.get('actual_offers_count', 0)
    
    if not skills_data:
        with container:
            with ui.card().classes('w-full bg-yellow-100 p-4'):
                ui.label("Aucune compétence pertinente n'a pu être extraite.").classes('text-yellow-800')
        return

    for item in skills_data:
        item['skill'] = format_skill_name(item['skill'])

    df_skills = pd.DataFrame(skills_data)
    df_skills.rename(columns={'skill': 'Compétence', 'frequency': 'Fréquence'}, inplace=True)
    df_skills.insert(0, 'Classement', range(1, len(df_skills) + 1))
    
    with container:
        # Ligne de titre améliorée
        with ui.row().classes('w-full items-center justify-between'):
            with ui.row(wrap=False).classes('items-center'):
                ui.label(f"📊 Top {len(df_skills)} pour '{job_title}'").classes('text-2xl font-bold text-gray-800')
                # Affichage du nombre réel d'offres
                ui.label(f"({actual_offers} offres analysées)").classes('text-sm text-gray-500 ml-2')
            
            refresh_button = ui.button('Rafraîchir', icon='refresh', on_click=lambda: refresh_analysis(job_title, offers_select.value))
            refresh_button.props('color=grey-6 flat dense')

        # Cartes KPI simplifiées
        with ui.row().classes('w-full justify-around mt-4 gap-4'):
            with ui.card().classes('items-center flex-grow p-4'):
                ui.label('Top Compétence').classes('text-sm text-gray-500')
                ui.label(df_skills.iloc[0]['Compétence']).classes('text-2xl font-bold text-center text-blue-600')
            with ui.card().classes('items-center flex-grow p-4'):
                ui.label('Niveau Demandé').classes('text-sm text-gray-500')
                ui.label(top_diploma).classes('text-2xl font-bold text-blue-600')
        
        ui.label("Classement détaillé des compétences").classes('text-xl font-bold mt-8 mb-2')
        
        # Le filtre et le tableau sont dans une colonne pour aligner leur largeur
        with ui.column().classes('w-full gap-2'):
            filter_input = ui.input(placeholder="Filtrer les compétences...").props('dense outlined').classes('w-full')
            
            table = ui.table(
                columns=[
                    {'name': 'Classement', 'label': '#', 'field': 'Classement', 'align': 'left'},
                    {'name': 'Compétence', 'label': 'Compétence', 'field': 'Compétence', 'sortable': True, 'align': 'left'},
                    {'name': 'Fréquence', 'label': 'Fréquence', 'field': 'Fréquence', 'sortable': True, 'align': 'left'},
                ],
                rows=df_skills.to_dict('records'),
                row_key='Compétence'
            ).props('flat bordered')
            
            # Rend le tableau scrollable et limite l'affichage initial
            table.style('max-height: 50vh;')
            table.props('pagination={"rowsPerPage": 10}')
            
            table.bind_filter_from(filter_input, 'value')

async def run_analysis_logic(force_refresh: bool = False):
    if not all([job_input, offers_select, job_input.value, offers_select.value]):
        return

    job_title = job_input.value
    num_offers = offers_select.value
    cache_key = f"{job_title.lower().strip()}@{num_offers}"
    
    if force_refresh:
        await run.io_bound(delete_from_cache, cache_key)

    results_container.clear()
    log_view.clear()
    
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    if not any(isinstance(h, UiLogHandler) for h in logger.handlers):
        logger.handlers.clear()
        log_handler = UiLogHandler(log_view)
        log_handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))
        logger.addHandler(log_handler)

    with results_container:
        with ui.card().classes('w-full p-4 items-center'):
            ui.spinner(size='lg', color='primary')
            ui.label(f"Analyse en cours...").classes('text-gray-600 mt-2')

    try:
        results = await get_skills_for_job(job_title, num_offers, logger)
        if results is None:
            raise ValueError("Aucune offre ou compétence trouvée.")
        
        # Le nombre d'offres n'est plus passé séparément
        display_results(results_container, results, job_title)

    except Exception as e:
        logger.error(f"Une erreur est survenue : {e}")
        results_container.clear()
        with results_container:
            ui.label(f"Erreur : {e}").classes('text-negative')

async def refresh_analysis(job_title_to_refresh: str, num_offers_to_refresh: int):
    job_input.value = job_title_to_refresh
    offers_select.value = num_offers_to_refresh
    await run_analysis_logic(force_refresh=True)

async def handle_flush_cache():
    success = await run.io_bound(flush_all_cache)
    if success:
        ui.notify('Le cache a été vidé.', color='positive')
        results_container.clear()
    else:
        ui.notify('Erreur lors du vidage du cache.', color='negative')

@ui.page('/')
def main_page():
    global job_input, offers_select, results_container, log_view
    
    ui.query('body').style('background-color: #f8fafc;')

    # En-tête avec liens nettoyés et responsive
    with ui.header(elevated=True).classes('bg-white text-black px-4'):
        with ui.row().classes('w-full items-center justify-between'):
            ui.image('/assets/SkillScope.svg').classes('w-32 md:w-40')
            with ui.row().classes('items-center'):
                ui.link('Portfolio', 'https://portfolio-hamza-kachmir.vercel.app/', new_tab=True).classes('text-gray-600 hover:text-blue-700').style('text-decoration: none;')
                ui.link('LinkedIn', 'https://www.linkedin.com/in/hamza-kachmir/', new_tab=True).classes('ml-4 text-gray-600 hover:text-blue-700').style('text-decoration: none;')

    # Conteneur principal responsive
    with ui.column().classes('w-full max-w-4xl mx-auto p-4 md:p-8 items-center gap-4'):
        ui.markdown("## Analysez les compétences clés d'un métier").classes('text-2xl md:text-3xl text-center font-light')
        ui.markdown("_Données **France Travail** analysées par **Google Gemini**._").classes('text-center text-gray-500 mb-6')

        # Zone de recherche responsive
        with ui.row().classes('w-full max-w-lg items-stretch gap-2'):
            job_input = ui.input(placeholder="Ex: Ingénieur Data...").props('outlined').classes('flex-grow')
            offers_select = ui.select({50: '50', 100: '100', 150: '150'}, value=100, label='Offres').props('outlined')
        
        launch_button = ui.button('Lancer l\'analyse', on_click=lambda: run_analysis_logic(force_refresh=False)).props('color=primary size=lg').classes('w-full max-w-lg')
        
        results_container = ui.column().classes('w-full mt-6')
        
        # Section des logs améliorée
        with ui.expansion("Logs et gestion du cache", icon='o_code').classes('w-full mt-8 bg-gray-50 rounded-lg'):
            with ui.row().classes('w-full items-center justify-between p-2'):
                ui.label("Activité du processus").classes('text-gray-600')
                ui.button('Vider le cache', on_click=handle_flush_cache, color='red').props('flat dense')
            log_view = ui.log().classes('w-full h-40 bg-gray-800 text-white font-mono text-xs rounded-b-lg')

    job_input.props('clearable')
    launch_button.bind_enabled_from(job_input, 'value', backward=lambda v: bool(v))

port = int(os.environ.get('PORT', 8080))
ui.run(host='0.0.0.0', port=port, title='SkillScope | Analyse de compétences')