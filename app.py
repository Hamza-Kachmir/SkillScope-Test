# FICHIER : app.py (Version simplifiée sans sélection du nombre d'offres)
import pandas as pd
import logging
from nicegui import ui, app, run
import os
import sys

# Configuration du chemin
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), 'src')))

from pipeline import get_skills_for_job
from src.cache_manager import delete_from_cache, flush_all_cache

# Variables globales
job_input = None
launch_button = None
results_container = None
log_view = None

class UiLogHandler(logging.Handler):
    def __init__(self, log_element: ui.log):
        super().__init__()
        self.log_element = log_element
        self.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    def emit(self, record):
        try: msg = self.format(record); self.log_element.push(msg)
        except Exception as e: print(f"Error in UiLogHandler: {e}")

def format_skill_name(skill: str) -> str:
    known_acronyms = {'aws', 'gcp', 'sql', 'etl', 'api', 'rest', 'erp', 'crm', 'devops', 'qa', 'ux', 'ui', 'saas', 'cicd', 'kpi', 'sap'}
    if skill.lower() in known_acronyms: return skill.upper()
    return skill.capitalize()

def display_results(container: ui.column, results_dict: dict):
    logger = logging.getLogger()
    logger.info("Affichage des résultats : Début de la fonction display_results.")
    container.clear()
    skills_data = results_dict.get('skills', [])
    top_diploma = results_dict.get('top_diploma', 'Non précisé')
    actual_offers = results_dict.get('actual_offers_count', 0)
    if not skills_data:
        logger.warning("Affichage des résultats : Aucune donnée de compétence à afficher.")
        with container:
            with ui.card().classes('w-full bg-yellow-100 p-4'):
                ui.label("Aucune offre ou compétence pertinente n'a pu être extraite.").classes('text-yellow-800')
        return

    formatted_skills = [{'classement': i + 1, 'competence': format_skill_name(item['skill']), 'frequence': item['frequency']} for i, item in enumerate(skills_data)]
    
    with container:
        with ui.row().classes('w-full items-baseline'):
            ui.label("Synthèse").classes('text-2xl font-bold text-gray-800')
            ui.label(f"({actual_offers} offres analysées)").classes('text-sm text-gray-500 ml-2')

        with ui.row().classes('w-full mt-4 gap-4 flex flex-wrap'):
            with ui.card().classes('items-center p-4 w-full sm:flex-1'):
                ui.label('Top Compétence').classes('text-sm text-gray-500')
                ui.label(formatted_skills[0]['competence']).classes('text-2xl font-bold text-center text-blue-600')
            with ui.card().classes('items-center p-4 w-full sm:flex-1'):
                ui.label('Niveau Demandé').classes('text-sm text-gray-500')
                ui.label(top_diploma).classes('text-2xl font-bold text-blue-600')
        
        ui.label("Classement des compétences").classes('text-xl font-bold mt-8 mb-2')
        with ui.column().classes('w-full gap-2'):
            filter_input = ui.input(placeholder="Chercher une compétence").props('outlined dense').classes('w-full')
            table = ui.table(
                columns=[
                    {'name': 'classement', 'label': '#', 'field': 'classement', 'align': 'left'},
                    {'name': 'competence', 'label': 'Compétence', 'field': 'competence', 'align': 'left', 'sortable': True},
                    {'name': 'frequence', 'label': 'Fréquence', 'field': 'frequence', 'align': 'left', 'sortable': True},
                ],
                rows=formatted_skills, row_key='competence'
            ).props('flat bordered').classes('w-full')
            table.props('pagination={"rowsPerPage": 10}')
            table.bind_filter_from(filter_input, 'value')
    logger.info("Affichage des résultats : Fin de la fonction display_results.")

async def run_analysis_logic(force_refresh: bool = False):
    logger = logging.getLogger()
    
    logger.info("--- NOUVELLE ANALYSE DÉCLENCHÉE ---")
    if not job_input.value: 
        logger.warning("Analyse annulée : aucun métier n'a été entré.")
        return
    
    try:
        results_container.clear()
        with results_container:
            with ui.card().classes('w-full p-4 items-center'):
                ui.spinner(size='lg', color='primary')
                ui.label("Analyse en cours...").classes('text-gray-600 mt-2')

        job_value = job_input.value
        # FIX: Le nombre d'offres est maintenant fixé à 150
        offers_value = 100
        logger.info(f"Appel du pipeline pour '{job_value}' avec {offers_value} offres (valeur fixe).")
        
        results = await get_skills_for_job(job_value, offers_value, logger)
        
        if results is None: raise ValueError("Aucune offre ou compétence trouvée.")
        display_results(results_container, results)
        
    except Exception as e:
        logger.critical(f"ERREUR CRITIQUE : {e}")
        results_container.clear()
        with results_container: ui.label(f"Une erreur est survenue, veuillez réessayer.").classes('text-negative')
    logger.info("--- FIN DU PROCESSUS ---")


@ui.page('/')
def main_page():
    global job_input, launch_button, results_container, log_view
    
    ui.add_head_html('<meta name="viewport" content="width=device-width, initial-scale=1.0">')
    app.add_static_files('/assets', 'assets')
    ui.query('body').style('background-color: #f8fafc;')

    with ui.header(elevated=True).classes('bg-white text-black px-4'):
        with ui.row().classes('w-full items-center justify-center'):
            ui.image('/assets/SkillScope.svg').classes('w-32 md:w-40')

    with ui.column().classes('w-full max-w-4xl mx-auto p-4 md:p-8 items-center gap-4'):
        ui.markdown("### Un outil d'analyse pour extraire et quantifier les compétences les plus demandées sur le marché de l'emploi.").classes('text-center font-light text-gray-800')
        with ui.row():
            ui.html("<i>Actuellement basé sur les données de <b>France Travail</b> et l'analyse de <b>Google Gemini.</b></i>").classes('text-center text-gray-500 mb-6')

        # FIX: Suppression du sélecteur d'offres pour simplifier
        with ui.row().classes('w-full max-w-lg items-stretch'):
            job_input = ui.input(placeholder="Chercher un métier").props('outlined dense clearable').classes('w-full')
            job_input.style('font-size: 16px;')
        
        launch_button = ui.button('Lancer l\'analyse', on_click=run_analysis_logic).props('color=primary').classes('w-full max-w-md')
        
        results_container = ui.column().classes('w-full mt-6')
        
        with ui.column().classes('w-full items-center mt-8 pt-6'):
             ui.html(f'''
                <p style="margin: 0; font-size: 0.875rem; color: #6b7280;">
                    <b style="color: black;">Développé par</b>
                    <span style="color: #f9b15c; font-weight: bold;"> Hamza Kachmir</span>
                </p>
            ''')
             with ui.row().classes('gap-4 mt-2'):
                ui.html(f'<a href="https://portfolio-hamza-kachmir.vercel.app/" target="_blank" style="color: #2474c5; font-weight: bold; text-decoration: none;">Portfolio</a>')
                ui.html(f'<a href="https://www.linkedin.com/in/hamza-kachmir/" target="_blank" style="color: #2474c5; font-weight: bold; text-decoration: none;">LinkedIn</a>')

        with ui.expansion("Voir les logs", icon='o_code').classes('w-full mt-12 bg-gray-50 rounded-lg'):
            log_view = ui.log().classes('w-full h-40 bg-gray-800 text-white font-mono text-xs')
            handler = UiLogHandler(log_view)
            logger = logging.getLogger()
            logger.setLevel(logging.INFO)
            logger.handlers.clear()
            logger.addHandler(handler)

    launch_button.bind_enabled_from(job_input, 'value', backward=lambda v: bool(v))

port = int(os.environ.get('PORT', 10000))
ui.run(host='0.0.0.0', port=port, title='SkillScope | Analyse de compétences')