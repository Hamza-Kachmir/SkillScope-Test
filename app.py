# FICHIER : app.py (Version avec un tableau personnalisé)
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
offers_select = None
launch_button = None
results_container = None
log_view = None

class UiLogHandler(logging.Handler):
    # ... (code inchangé)
    def __init__(self, log_element: ui.log):
        super().__init__()
        self.log_element = log_element
        self.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))
    def emit(self, record):
        try: msg = self.format(record); self.log_element.push(msg)
        except Exception as e: print(f"Error in UiLogHandler: {e}")

def format_skill_name(skill: str) -> str:
    # ... (code inchangé)
    known_acronyms = {'aws', 'gcp', 'sql', 'etl', 'api', 'rest', 'erp', 'crm', 'devops', 'qa', 'ux', 'ui', 'saas', 'cicd', 'kpi', 'sap'}
    if skill.lower() in known_acronyms: return skill.upper()
    return skill.capitalize()

def display_results(container: ui.column, results_dict: dict):
    container.clear()
    skills_data = results_dict.get('skills', [])
    top_diploma = results_dict.get('top_diploma', 'Non précisé')
    actual_offers = results_dict.get('actual_offers_count', 0)
    if not skills_data: return

    with container:
        with ui.row().classes('w-full items-center'):
            ui.label("Synthèse").classes('text-2xl font-bold text-gray-800')
            ui.label(f"({actual_offers} offres analysées)").classes('text-sm text-gray-500 ml-2')

        with ui.row().classes('w-full mt-4 gap-4 flex flex-wrap'):
            with ui.card().classes('items-center p-4 w-full sm:flex-1'):
                ui.label('Top Compétence').classes('text-sm text-gray-500')
                ui.label(format_skill_name(skills_data[0]['skill'])).classes('text-2xl font-bold text-center text-blue-600')
            with ui.card().classes('items-center p-4 w-full sm:flex-1'):
                ui.label('Niveau Demandé').classes('text-sm text-gray-500')
                ui.label(top_diploma).classes('text-2xl font-bold text-blue-600')
        
        ui.label("Classement détaillé des compétences").classes('text-xl font-bold mt-8 mb-2')
        
        with ui.column().classes('w-full gap-2'):
            # FIX: Placeholder mis à jour
            filter_input = ui.input(placeholder="Chercher une compétence").props('outlined dense').classes('w-full')
            
            # FIX: Remplacement complet du ui.table par un système de lignes et colonnes
            with ui.column().classes('w-full styled-scrollbar border rounded-lg').style('max-height: 50vh; overflow-y: auto;'):
                # En-tête du tableau personnalisé
                with ui.row().classes('w-full p-2 bg-gray-50 font-bold sticky top-0 z-10'):
                    ui.label('#').classes('w-1/12 text-center')
                    ui.label('Compétence').classes('w-7/12')
                    ui.label('Fréquence').classes('w-4/12 text-center')
                
                # Conteneur pour les lignes de données filtrables
                rows_container = ui.column().classes('w-full')

            def update_rows():
                rows_container.clear()
                search_term = filter_input.value.lower()
                
                # Recréation des données formatées à chaque mise à jour
                formatted_skills = []
                for i, item in enumerate(skills_data):
                    formatted_skills.append({
                        'classement': i + 1,
                        'competence': format_skill_name(item['skill']),
                        'frequence': item['frequency']
                    })

                filtered_data = [
                    row for row in formatted_skills
                    if search_term in row['competence'].lower()
                ]

                with rows_container:
                    if not filtered_data:
                        ui.label("Aucune compétence ne correspond à votre filtre.").classes('p-4 text-center text-gray-500')
                    else:
                        for row_data in filtered_data:
                            with ui.row().classes('w-full p-2 border-t items-center'):
                                ui.label(row_data['classement']).classes('w-1/12 text-center')
                                ui.label(row_data['competence']).classes('w-7/12')
                                ui.label(row_data['frequence']).classes('w-4/12 text-center')
            
            filter_input.on('change', update_rows)
            update_rows() # Affichage initial


async def run_analysis_logic(force_refresh: bool = False):
    global launch_button, job_input
    if not job_input.value: return

    launch_button.disable()
    job_input.disable()
    ui.run_javascript('document.activeElement.blur()')
    try:
        results_container.clear()
        with results_container:
            with ui.card().classes('w-full p-4 items-center'):
                ui.spinner(size='lg', color='primary')
                ui.label("Analyse en cours...").classes('text-gray-600 mt-2')
        results = await get_skills_for_job(job_input.value, offers_select.value, logging.getLogger())
        if results is None: raise ValueError("Aucune offre ou compétence trouvée.")
        display_results(results_container, results)
    except Exception as e:
        logging.getLogger().error(f"Une erreur est survenue : {e}")
        results_container.clear()
        with results_container: ui.label(f"Erreur : {e}").classes('text-negative')
    finally:
        launch_button.enable()
        job_input.enable()

@ui.page('/')
def main_page():
    global job_input, offers_select, launch_button, results_container, log_view
    ui.add_head_html('<meta name="viewport" content="width=device-width, initial-scale=1.0">')
    ui.add_css('''
        .styled-scrollbar::-webkit-scrollbar { width: 12px; }
        .styled-scrollbar::-webkit-scrollbar-track { background: #f1f1f1; }
        .styled-scrollbar::-webkit-scrollbar-thumb { background: #ccc; border-radius: 6px; }
        .styled-scrollbar::-webkit-scrollbar-thumb:hover { background: #aaa; }
    ''')
    app.add_static_files('/assets', 'assets')
    ui.query('body').style('background-color: #f8fafc;')

    with ui.header(elevated=True).classes('bg-white text-black px-4'):
        with ui.row().classes('w-full items-center justify-center'):
            ui.image('/assets/SkillScope.svg').classes('w-32 md:w-40')

    with ui.column().classes('w-full max-w-4xl mx-auto p-4 md:p-8 items-center gap-4'):
        ui.markdown("### Un outil d'analyse pour extraire et quantifier les compétences les plus demandées sur le marché de l'emploi.").classes('text-center font-light text-gray-800')
        with ui.row():
            ui.html("<i>Actuellement basé sur les données de <b>France Travail</b> et l'analyse de <b>Google Gemini.</b></i>").classes('text-center text-gray-500 mb-6')

        with ui.row().classes('w-full max-w-lg items-stretch gap-2'):
            # FIX: Placeholder mis à jour et inputs en mode "dense"
            job_input = ui.input(placeholder="Chercher un métier").props('outlined dense clearable').classes('flex-grow')
            job_input.style('font-size: 16px;')
            
            offers_select = ui.select({50: '50 offres', 100: '100 offres', 150: '150 offres'}, value=100).props('outlined dense')
            offers_select.style('font-size: 16px;')
        
        # FIX: Bouton moins large et moins haut
        launch_button = ui.button('Lancer l\'analyse', on_click=lambda: run_analysis_logic(force_refresh=False)).props('color=primary id="launch-button"').classes('w-full max-w-md')
        job_input.on('keydown.enter', lambda: ui.run_javascript('document.getElementById("launch-button").click()'))
        
        results_container = ui.column().classes('w-full mt-6')
        
        with ui.expansion("Voir les logs", icon='o_code').classes('w-full mt-8 bg-gray-50 rounded-lg'):
            log_view = ui.log().classes('w-full h-40 bg-gray-800 text-white font-mono text-xs')
            handler = UiLogHandler(log_view)
            logger = logging.getLogger()
            logger.setLevel(logging.INFO)
            logger.handlers.clear()
            logger.addHandler(handler)

        with ui.column().classes('w-full items-center mt-12 pt-6 border-t'):
            # ... (code du footer inchangé)
             ui.html(f'''
                <p style="margin: 0; font-size: 0.875rem; color: #6b7280;">
                    <b style="color: black;">Développé par</b>
                    <span style="color: #f9b15c; font-weight: bold;"> Hamza Kachmir</span>
                </p>
            ''')
             with ui.row().classes('gap-4 mt-2'):
                ui.html(f'<a href="https://portfolio-hamza-kachmir.vercel.app/" target="_blank" style="color: #2474c5; font-weight: bold; text-decoration: none;">Portfolio</a>')
                ui.html(f'<a href="https://www.linkedin.com/in/hamza-kachmir/" target="_blank" style="color: #2474c5; font-weight: bold; text-decoration: none;">LinkedIn</a>')

    launch_button.bind_enabled_from(job_input, 'value', backward=lambda v: bool(v))

port = int(os.environ.get('PORT', 10000))
ui.run(host='0.0.0.0', port=port, title='SkillScope | Analyse de compétences')