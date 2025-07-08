import pandas as pd
import logging
import os
import sys
import io
from typing import Dict, Any, List
from nicegui import ui, app, run
from starlette.responses import Response

# Ajoute le répertoire 'src' au chemin pour permettre les imports locaux
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), 'src')))

from pipeline import get_skills_for_job
from src.cache_manager import flush_all_cache

# --- Constantes de configuration ---
NB_OFFERS_TO_ANALYZE = 100 # Nombre d'offres à analyser par défaut
# En mode test, nous définissons explicitement IS_PRODUCTION_MODE à False
IS_PRODUCTION_MODE = False


# --- Gestionnaires de logs pour l'UI ---
class UiLogHandler(logging.Handler):
    """Un gestionnaire de logs qui pousse les messages vers un élément ui.log de NiceGUI."""
    def __init__(self, log_element: ui.log, log_messages_list: list):
        super().__init__()
        self.log_element = log_element
        self.log_messages_list = log_messages_list
        self.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

    def emit(self, record):
        """Formate et pousse un enregistrement de log vers l'interface."""
        try:
            msg = self.format(record)
            self.log_messages_list.append(msg)
            if self.log_element: # S'assurer que l'élément UI existe
                self.log_element.push(msg)
        except Exception as e:
            print(f"Error in UiLogHandler: {e}")


# --- Points de terminaison (API Endpoints) ---
def _get_export_data():
    """
    Récupère les données de la dernière analyse depuis le stockage de session de l'application.
    """
    # Récupérer les données depuis le storage de la session utilisateur
    # ui.context.storage.user est fiable ici car ces endpoints sont déclenchés par le client
    df = ui.context.storage.user.get('latest_df', None)
    job_title = ui.context.storage.user.get('latest_job_title', 'Non spécifié')
    actual_offers_count = ui.context.storage.user.get('latest_actual_offers_count', 0)
    
    if df is None or df.empty:
        return None, None, None
    return df, job_title, actual_offers_count

@app.get('/download/excel')
def download_excel_endpoint():
    """Point de terminaison pour télécharger les résultats au format Excel."""
    df, job_title, offers_count = _get_export_data()
    if df is None:
        return Response("Aucune donnée à exporter.", media_type='text/plain', status_code=404)

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        header_info = pd.DataFrame([
            ['Métier Analysé:', job_title],
            ['Offres Analysées:', offers_count],
            []
        ])
        header_info.to_excel(writer, index=False, header=False, sheet_name='Resultats', startrow=0)
        df.to_excel(writer, index=False, sheet_name='Resultats', startrow=len(header_info)-1)
    
    headers = {'Content-Disposition': 'attachment; filename="skillscope_results.xlsx"'}
    return Response(content=output.getvalue(), media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', headers=headers)


@app.get('/download/csv')
def download_csv_endpoint():
    """Point de terminaison pour télécharger les résultats au format CSV."""
    df, job_title, offers_count = _get_export_data()
    if df is None:
        return Response("Aucune donnée à exporter.", media_type='text/plain', status_code=404)
    
    header_lines = [
        f"Metier Analyse: {job_title}",
        f"Offres Analysees: {offers_count}",
        ""
    ]
    csv_data = "\n".join(header_lines) + "\n" + df.to_csv(index=False, encoding='utf-8')
    
    headers = {'Content-Disposition': 'attachment; filename="skillscope_results.csv"'}
    return Response(content=csv_data.encode('utf-8'), media_type='text/csv', headers=headers)


# --- Logique d'affichage et d'analyse ---
async def run_analysis_logic(job_input_val: str, results_container_ui: ui.column, log_messages_list_ui: List[str], logger_instance: logging.Logger):
    """
    Fonction principale qui orchestre le lancement de l'analyse suite au clic de l'utilisateur.
    Reçoit maintenant les éléments UI et le logger spécifiques à la session.
    """
    logger_instance.info("--- NOUVELLE ANALYSE DÉCLENCHÉE ---")
    
    job_value = job_input_val
    if not job_value:
        logger_instance.warning("Analyse annulée : aucun métier n'a été entré.")
        return

    try:
        results_container_ui.clear()
        with results_container_ui:
            with ui.column().classes('w-full p-4 items-center'):
                ui.spinner(size='lg', color='primary')
                ui.html(f"Analyse en cours pour <strong>'{job_value}'</strong>...").classes('text-gray-600 mt-4 text-lg')

        logger_instance.info(f"Appel du pipeline pour '{job_value}' avec {NB_OFFERS_TO_ANALYZE} offres.")
        results = await get_skills_for_job(job_value, NB_OFFERS_TO_ANALYZE, logger_instance)
        
        if results is None:
            raise ValueError("Le pipeline n'a retourné aucun résultat.")

        # Les données pour l'export sont maintenant passées directement à display_results
        # et stockées dans ui.context.storage.user à l'intérieur de display_results.
        display_results(results_container_ui, results, job_value)

    except Exception as e:
        logger_instance.critical(f"ERREUR CRITIQUE PENDANT L'ANALYSE : {e}", exc_info=True)
        results_container_ui.clear()
        with results_container_ui:
            ui.label(f"Une erreur est survenue : {e}").classes('text-negative')
    
    logger_instance.info("--- FIN DU PROCESSUS ---")


def display_results(container: ui.column, results_dict: Dict[str, Any], job_title: str):
    """
    Construit dynamiquement la section des résultats dans l'interface.
    Stocke aussi les données dans le storage de session.
    """
    container.clear()

    skills_data = results_dict.get('skills', [])
    top_diploma = results_dict.get('top_diploma', 'Non précisé')
    actual_offers = results_dict.get('actual_offers_count', 0)

    if not skills_data:
        with container:
            ui.label("Aucune offre ou compétence pertinente n'a pu être extraite.").classes('text-yellow-800')
        return

    formatted_skills = [{'classement': i + 1, 'competence': item['skill'], 'frequence': item['frequency']} for i, item in enumerate(skills_data)]
    df = pd.DataFrame(formatted_skills)

    # Stockage des données spécifiques à la session pour l'export.
    # Ceci est fait ici car display_results est appelée directement par un événement UI.
    ui.context.storage.user['latest_df'] = df
    ui.context.storage.user['latest_job_title'] = job_title
    ui.context.storage.user['latest_actual_offers_count'] = actual_offers

    with container:
        with ui.row().classes('w-full items-baseline'):
            ui.label(f"Synthèse pour '{job_title}'").classes('text-2xl font-bold text-gray-800')
            ui.label(f"({actual_offers} offres analysées)").classes('text-sm text-gray-500 ml-2')

        with ui.row().classes('w-full mt-4 gap-4 flex-wrap'):
            with ui.card().classes('items-center p-4 w-full sm:flex-1'):
                ui.label('Top Compétence').classes('text-sm text-gray-500')
                ui.label(formatted_skills[0]['competence']).classes('text-2xl font-bold text-center text-blue-600')
            with ui.card().classes('items-center p-4 w-full sm:flex-1'):
                ui.label('Niveau Demandé').classes('text-sm text-gray-500')
                ui.label(top_diploma).classes('text-2xl font-bold text-blue-600')
        
        ui.label("Classement des compétences").classes('text-xl font-bold mt-8 mb-2')
        with ui.row().classes('w-full justify-center gap-4 mb-2 flex-wrap'):
            ui.link('Export Excel', '/download/excel', new_tab=True).classes('no-underline bg-green-600 text-white px-4 py-2 rounded-lg hover:bg-green-700')
            ui.link('Export CSV', '/download/csv', new_tab=True).classes('no-underline bg-slate-600 text-white px-4 py-2 rounded-lg hover:bg-slate-700')

        pagination_state = {'page': 1, 'rows_per_page': 10}
        total_pages = max(1, (len(df) - 1) // pagination_state['rows_per_page'] + 1)
        
        table = ui.table(
            columns=[
                {'name': 'classement', 'label': '#', 'field': 'classement', 'align': 'left', 'style': 'width: 10%'},
                {'name': 'competence', 'label': 'Compétence', 'field': 'competence', 'align': 'left', 'style': 'width: 70%'},
                {'name': 'frequence', 'label': 'Fréquence', 'field': 'frequence', 'align': 'left', 'style': 'width: 20%'},
            ],
            rows=[],
            row_key='competence'
        ).props('flat bordered').classes('w-full')

        def update_table():
            """Met à jour les lignes du tableau et l'état des boutons de pagination."""
            start = (pagination_state['page'] - 1) * pagination_state['rows_per_page']
            end = start + pagination_state['rows_per_page']
            table.rows = df.iloc[start:end].to_dict('records')
            page_info_label.text = f"{pagination_state['page']} sur {total_pages}"
            btn_first.set_enabled(pagination_state['page'] > 1)
            btn_prev.set_enabled(pagination_state['page'] > 1)
            btn_next.set_enabled(pagination_state['page'] < total_pages)
            btn_last.set_enabled(pagination_state['page'] < total_pages)

        update_table()


@ui.page('/')
def main_page():
    """Construit et configure la page principale de l'application, spécifique à chaque session."""
    # Ces variables sont maintenant locales à CHAQUE session utilisateur
    job_input: ui.input = None
    results_container: ui.column = None
    log_view: ui.log = None
    all_log_messages: List[str] = [] # Liste de messages de log propre à cette session

    # Configurez un logger spécifique à cette session
    session_logger = logging.getLogger(f"session_logger_{id(ui.context)}")
    session_logger.handlers.clear()
    session_logger.setLevel(logging.INFO) # Niveau de log à INFO pour le test

    # --- Configuration de la page et des styles CSS ---
    ui.add_head_html('''
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            .no-underline { text-decoration: none !important; }
            .link-hover:hover { text-decoration: underline !important; }
        </style>
    ''')
    app.add_static_files('/assets', 'assets')
    ui.query('body').style('background-color: #f8fafc;')

    # --- En-tête de la page ---
    with ui.header(elevated=True).classes('bg-white text-black px-4'):
        with ui.row().classes('w-full items-center justify-center'):
            ui.image('/assets/SkillScope.svg').classes('w-40 md:w-48')

    # --- Contenu principal ---
    with ui.column().classes('w-full max-w-4xl mx-auto p-4 md:p-8 items-center gap-4'):
        ui.markdown("### Un outil pour quantifier les compétences les plus demandées sur le marché de l'emploi.").classes('text-center font-light text-gray-800')
        ui.html("<i>Basé sur les données de <b>France Travail</b> et l'analyse de <b>Google Gemini.</b></i>").classes('text-center text-gray-500 mb-6')

        # --- Section de recherche ---
        with ui.row().classes('w-full max-w-lg items-stretch'):
            job_input = ui.input(placeholder="Chercher un métier").props('outlined dense clearable').classes('w-full text-lg')
        
        launch_button = ui.button("Lancer l'analyse", on_click=lambda: run_analysis_logic(
            job_input.value, results_container, all_log_messages, session_logger
        )).props('color=primary').classes('w-full max-w-lg mt-4')
        
        launch_button.bind_enabled_from(job_input, 'value', backward=bool)

        results_container = ui.column().classes('w-full mt-6')

        # --- Pied de page et liens externes ---
        with ui.column().classes('w-full items-center mt-8 pt-6 border-t'):
            ui.html('<p style="font-size: 0.875rem; color: #6b7280;"><b style="color: black;">Développé par</b> <span style="color: #f9b15c; font-weight: bold;">Hamza Kachmir</span></p>')
            with ui.row().classes('gap-4 mt-2'):
                ui.html('<a href="https://portfolio-hamza-kachmir.vercel.app/" target="_blank" class="link-hover" style="color: #2474c5; font-weight: bold; text-decoration: none;">Portfolio</a>')
                ui.html('<a href="https://www.linkedin.com/in/hamza-kachmir/" target="_blank" class="link-hover" style="color: #2474c5; font-weight: bold; text-decoration: none;">LinkedIn</a>')

        # --- Section "Logs" extensible (toujours affichée en mode test) ---
        with ui.expansion("Voir les logs & Outils", icon='o_code').classes('w-full mt-12 bg-gray-50 rounded-lg'):
            with ui.column().classes('w-full p-2'):
                log_view = ui.log().classes('w-full h-40 bg-gray-800 text-white font-mono text-xs')
                with ui.row().classes('mt-2 gap-2'):
                    ui.button('Vider tout le cache', on_click=lambda: (flush_all_cache(), ui.notify('Cache vidé avec succès !', color='positive')), color='red-6', icon='o_delete_forever')
                    ui.button('Copier les logs', on_click=lambda: ui.run_javascript(f'navigator.clipboard.writeText(`{"\\n".join(all_log_messages)}`)'), icon='o_content_copy')
            
            session_logger.addHandler(UiLogHandler(log_view, all_log_messages))


if __name__ in {"__main__", "__mp_main__"}:
    port = int(os.environ.get('PORT', 10000))
    ui.run(host='0.0.0.0', port=port, title='SkillScope | Analyse de compétences', favicon='assets/SkillScope.svg')