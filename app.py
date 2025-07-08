import pandas as pd
import logging
import os
import sys
import io
from typing import Dict
from nicegui import ui, app, run
from starlette.responses import Response

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), 'src')))

from pipeline import get_skills_for_job
from src.cache_manager import flush_all_cache

# --- Constantes de configuration ---
NB_OFFERS_TO_ANALYZE = 100

# --- État global de l'interface ---
job_input = None
results_container = None
log_view = None
all_log_messages = []
# Éléments pour le nouvel indicateur de chargement
progress_label = None
progress_bar = None
loading_container = None


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
            self.log_element.push(msg)
        except Exception as e:
            print(f"Error in UiLogHandler: {e}")


# --- Points de terminaison (API Endpoints) ---
def _get_export_data():
    """Récupère les données nécessaires pour l'export depuis le stockage de l'application."""
    df = getattr(app, 'latest_df', None)
    job_title = getattr(app, 'latest_job_title', 'Non spécifié')
    actual_offers_count = getattr(app, 'latest_actual_offers_count', 0)
    
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


# --- Logique principale de l'application ---
def display_results(container: ui.column, results_dict: dict, job_title: str):
    """Affiche les résultats de l'analyse dans l'interface utilisateur."""
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

    app.latest_df = df
    app.latest_job_title = job_title
    app.latest_actual_offers_count = actual_offers

    with container:
        with ui.row().classes('w-full items-baseline'):
            ui.label(f"Synthèse pour '{job_title}'").classes('text-2xl font-bold text-gray-800')
            ui.label(f"({actual_offers} offres analysées)").classes('text-sm text-gray-500 ml-2')

        with ui.row().classes('w-full mt-4 gap-4 flex flex-wrap'):
            with ui.card().classes('items-center p-4 w-full sm:flex-1'):
                ui.label('Top Compétence').classes('text-sm text-gray-500')
                ui.label(formatted_skills[0]['competence']).classes('text-2xl font-bold text-center text-blue-600')
            with ui.card().classes('items-center p-4 w-full sm:flex-1'):
                ui.label('Niveau Demandé').classes('text-sm text-gray-500')
                ui.label(top_diploma).classes('text-2xl font-bold text-blue-600')

        ui.label("Classement des compétences").classes('text-xl font-bold mt-8 mb-2')
        with ui.row().classes('w-full justify-center gap-2 mb-2'):
            ui.link('Export Excel', '/download/excel', new_tab=True).classes('bg-green-600 text-white px-4 py-2 rounded-lg hover:bg-green-700')
            ui.link('Export CSV', '/download/csv', new_tab=True).classes('bg-blue-grey-600 text-white px-4 py-2 rounded-lg hover:bg-blue-grey-700')

        pagination_state = {'page': 1, 'rows_per_page': 10}
        total_pages = max(1, (len(df) - 1) // pagination_state['rows_per_page'] + 1)
        
        # CORRECTION DU BUG: Le paramètre 'rows' est maintenant fourni à l'initialisation.
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
            """Met à jour les lignes du tableau et les boutons de pagination."""
            start = (pagination_state['page'] - 1) * pagination_state['rows_per_page']
            end = start + pagination_state['rows_per_page']
            table.rows = df.iloc[start:end].to_dict('records')
            page_info_label.text = f"{pagination_state['page']} sur {total_pages}"
            btn_first.set_enabled(pagination_state['page'] > 1)
            btn_prev.set_enabled(pagination_state['page'] > 1)
            btn_next.set_enabled(pagination_state['page'] < total_pages)
            btn_last.set_enabled(pagination_state['page'] < total_pages)

        with ui.row().classes('w-full justify-center items-center gap-2 mt-4'):
            btn_first = ui.button('<<', on_click=lambda: (pagination_state.update(page=1), update_table())).props('flat dense')
            btn_prev = ui.button('<', on_click=lambda: (pagination_state.update(page=max(1, pagination_state['page'] - 1)), update_table())).props('flat dense')
            page_info_label = ui.label()
            btn_next = ui.button('>', on_click=lambda: (pagination_state.update(page=min(total_pages, pagination_state['page'] + 1)), update_table())).props('flat dense')
            btn_last = ui.button('>>', on_click=lambda: (pagination_state.update(page=total_pages), update_table())).props('flat dense')

        update_table()


async def update_progress(data: Dict):
    """Callback pour mettre à jour l'UI de chargement depuis le pipeline."""
    progress_label.text = f"Étape {data['step']}/{data['total']}: {data['message']}"
    progress_bar.value = data['progress']

async def run_analysis_logic():
    """Fonction principale qui orchestre le lancement de l'analyse."""
    global loading_container
    logger = logging.getLogger()
    logger.info("--- NOUVELLE ANALYSE DÉCLENCHÉE ---")
    
    job_value = job_input.value
    if not job_value:
        logger.warning("Analyse annulée : aucun métier n'a été entré.")
        return

    try:
        # --- Afficher le nouvel indicateur de chargement ---
        results_container.clear()
        with results_container:
            # Le conteneur de chargement est maintenant sans carte
            loading_container = ui.column().classes('w-full p-4 items-center')
            with loading_container:
                # Texte dynamique qui sera mis à jour par le callback
                ui.spinner(size='lg', color='primary')
                ui.html(f"Analyse en cours pour <strong>'{job_value}'</strong>...").classes('text-gray-600 mt-4 text-lg')
                
                # Label pour les étapes détaillées
                global progress_label
                progress_label = ui.label("Initialisation...").classes("text-gray-500 text-sm mt-2")
                
                # Barre de progression
                global progress_bar
                progress_bar = ui.linear_progress(0.0).classes("w-full max-w-md mt-2")

        # --- Lancer le pipeline avec le callback ---
        logger.info(f"Appel du pipeline pour '{job_value}'.")
        results = await get_skills_for_job(job_value, NB_OFFERS_TO_ANALYZE, logger, progress_callback=update_progress)
        
        if results is None:
            raise ValueError("Le pipeline n'a retourné aucun résultat.")

        # Afficher les résultats une fois terminés
        display_results(results_container, results, job_value)

    except Exception as e:
        logger.critical(f"ERREUR CRITIQUE PENDANT L'ANALYSE : {e}", exc_info=True)
        results_container.clear()
        with results_container:
            ui.label(f"Une erreur est survenue : {e}").classes('text-negative')
    
    logger.info("--- FIN DU PROCESSUS ---")


@ui.page('/')
def main_page():
    """Construit et configure la page principale de l'application."""
    global job_input, results_container, log_view, all_log_messages

    ui.add_head_html('<meta name="viewport" content="width=device-width, initial-scale=1.0">')
    app.add_static_files('/assets', 'assets')
    ui.query('body').style('background-color: #f8fafc;')

    with ui.header(elevated=True).classes('bg-white text-black px-4'):
        with ui.row().classes('w-full items-center justify-center'):
            ui.image('/assets/SkillScope.svg').classes('w-40 md:w-48')

    with ui.column().classes('w-full max-w-4xl mx-auto p-4 md:p-8 items-center gap-4'):
        ui.markdown("### Un outil pour quantifier les compétences les plus demandées sur le marché de l'emploi.").classes('text-center font-light text-gray-800')
        ui.html("<i>Basé sur les données de <b>France Travail</b> et l'analyse de <b>Google Gemini.</b></i>").classes('text-center text-gray-500 mb-6')

        with ui.card().classes('w-full max-w-lg p-4'):
            job_input = ui.input(placeholder="Chercher un métier...").props('outlined dense clearable').classes('w-full text-lg')
            launch_button = ui.button("Lancer l'analyse", on_click=run_analysis_logic).props('color=primary no-caps').classes('w-full mt-2')
            launch_button.bind_enabled_from(job_input, 'value', backward=bool)

        results_container = ui.column().classes('w-full mt-6')

        with ui.column().classes('w-full items-center mt-8 pt-6 border-t'):
            ui.html('<p style="font-size: 0.875rem; color: #6b7280;"><b style="color: black;">Développé par</b> <span style="color: #f9b15c; font-weight: bold;">Hamza Kachmir</span></p>')
            with ui.row().classes('gap-4 mt-2'):
                ui.html('<a href="https://portfolio-hamza-kachmir.vercel.app/" target="_blank" style="color: #2474c5; font-weight: bold; text-decoration: none;">Portfolio</a>')
                ui.html('<a href="https://www.linkedin.com/in/hamza-kachmir/" target="_blank" style="color: #2474c5; font-weight: bold; text-decoration: none;">LinkedIn</a>')

        with ui.expansion("Voir les logs & Outils", icon='o_code').classes('w-full mt-12 bg-gray-50 rounded-lg'):
            with ui.column().classes('w-full p-2'):
                log_view = ui.log().classes('w-full h-40 bg-gray-800 text-white font-mono text-xs')
                with ui.row().classes('mt-2 gap-2'):
                    ui.button('Vider tout le cache', on_click=lambda: (flush_all_cache(), ui.notify('Cache vidé avec succès !', color='positive')), color='red-6', icon='o_delete_forever')
                    ui.button('Copier les logs', on_click=lambda: ui.run_javascript(f'navigator.clipboard.writeText(`{"\\n".join(all_log_messages)}`)'), icon='o_content_copy')
            
            handler = UiLogHandler(log_view, all_log_messages)
            logger = logging.getLogger()
            logger.setLevel(logging.INFO)
            logger.handlers.clear()
            logger.addHandler(handler)


if __name__ in {"__main__", "__mp_main__"}:
    port = int(os.environ.get('PORT', 10000))
    ui.run(host='0.0.0.0', port=port, title='SkillScope | Analyse de compétences', favicon='assets/SkillScope.svg')