import pandas as pd
import logging
import os
import sys
import io
import asyncio
import unicodedata
from typing import Dict, Any, List, Optional
from nicegui import ui, app, run, Client
from starlette.responses import Response
from starlette.requests import Request


# Ajoute le répertoire 'src' au chemin pour permettre les imports locaux.
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), 'src')))

from src.pipeline import get_skills_for_job_streaming # Importer la nouvelle fonction streaming
from src.cache_manager import flush_all_cache

# --- Constantes de configuration ---
[cite_start]NB_OFFERS_TO_ANALYZE = 100 # Définit le nombre d'offres d'emploi à analyser par défaut. [cite: 1]

# Détermine si l'application est en mode production pour contrôler l'affichage des logs UI.
[cite_start]IS_PRODUCTION_MODE = os.getenv('PRODUCTION_MODE', 'false').lower() in ('true', '1') # Changé à 'false' par défaut pour le développement [cite: 1]

# --- Stockage Global pour l'Export ---
# [cite_start]Ce dictionnaire stocke temporairement les données d'export par ID de session client. [cite: 1]
_export_data_storage: Dict[str, Dict[str, Any]] = {}

# --- Verrouillage des Recherches Concurrentes ---
# [cite_start]Ce dictionnaire gère les recherches de métiers déjà en cours pour éviter les requêtes redondantes. [cite: 1]
_active_searches: Dict[str, asyncio.Future] = {}

def _normalize_search_term(term: str) -> str:
    """
    Normalise une chaîne de caractères pour une utilisation cohérente comme clé de recherche ou de cache.
    Cette fonction convertit le terme en minuscules, supprime les accents et les espaces superflus.
    """
    [cite_start]normalized_term = unicodedata.normalize('NFKD', term) # Normalise les caractères Unicode. [cite: 1]
    [cite_start]normalized_term = normalized_term.encode('ascii', 'ignore').decode('utf-8').lower().strip() # Supprime les accents et met en minuscules. [cite: 1]
    return normalized_term


# --- Gestionnaire de Logs pour l'Interface Utilisateur (pour le développeur) ---
class UiLogHandler(logging.Handler):
    """
    Un gestionnaire de logs personnalisé qui pousse les messages vers un élément `ui.log` de NiceGUI.
    En mode production, il est désactivé pour l'affichage dans l'UI.
    """
    def __init__(self, log_element: ui.log, log_messages_list: list):
        super().__init__()
        self.log_element = log_element
        self.log_messages_list = log_messages_list
        # [cite_start]Définit le format des messages de log affichés dans l'UI développeur. [cite: 1]
        self.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(name)s - %(message)s'))

    def emit(self, record):
        """
        [cite_start]Formate un enregistrement de log et l'affiche dans l'interface utilisateur en mode non-production. [cite: 1]
        """
        try:
            msg = self.format(record)
            self.log_messages_list.append(msg)

            # [cite_start]Pousse le log vers l'élément ui.log si en mode non-production et connecté. [cite: 1]
            if not IS_PRODUCTION_MODE and self.log_element and hasattr(self.log_element, 'push') and self.log_element.client.has_socket_connection:
                self.log_element.push(msg)

        except Exception as e:
            print(f"Erreur dans UiLogHandler: {e}")


# --- Points de terminaison (API Endpoints) pour le téléchargement ---
@app.get('/download/excel/{client_id}')
def download_excel_endpoint(client_id: str):
    """
    [cite_start]Point de terminaison FastAPI pour télécharger les résultats de l'analyse au format Excel. [cite: 1]
    [cite_start]L'ID du client est utilisé pour récupérer les données spécifiques à la session utilisateur. [cite: 1]
    """
    if client_id not in _export_data_storage:
        logging.warning(f"Export Excel demandé pour un client_id inconnu ou expiré: {client_id}")
        return Response("Aucune donnée à exporter ou session expirée.", media_type='text/plain', status_code=404)

    data = _export_data_storage[client_id]
    df = data.get('df')
    job_title = data.get('job_title', 'Non précisé')
    offers_count = data.get('actual_offers_count', 0)

    if df is None or df.empty:
        return Response("Aucune donnée à exporter.", media_type='text/plain', status_code=404)

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        header_info = pd.DataFrame([
            ['Métier Analysé:', job_title],
            ['Offres Analysées:', offers_count],
            []
        ])
        header_info.to_excel(writer, index=False, header=False, sheet_name='Resultats', startrow=0)
        df[['classement', 'competence']].to_excel(writer, index=False, sheet_name='Resultats', startrow=len(header_info)-1)

    headers = {'Content-Disposition': 'attachment; filename="skillscope_results.xlsx"'}
    return Response(content=output.getvalue(), media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', headers=headers)


@app.get('/download/csv/{client_id}')
def download_csv_endpoint(client_id: str):
    """
    [cite_start]Point de terminaison FastAPI pour télécharger les résultats de l'analyse au format CSV. [cite: 1]
    [cite_start]L'ID du client est utilisé pour récupérer les données spécifiques à la session utilisateur. [cite: 1]
    """
    if client_id not in _export_data_storage:
        logging.warning(f"Export CSV demandé pour un client_id inconnu ou expiré: {client_id}")
        return Response("Aucune donnée à exporter ou session expirée.", media_type='text/plain', status_code=404)

    data = _export_data_storage[client_id]
    df = data.get('df')
    job_title = data.get('job_title', 'Non précisé')
    offers_count = data.get('actual_offers_count', 0)

    if df is None or df.empty:
        return Response("Aucune donnée à exporter.", media_type='text/plain', status_code=404)

    header_lines = [
        f"Métier Analysé: {job_title}",
        f"Offres Analysées: {offers_count}",
        ""
    ]
    csv_data = "\n".join(header_lines) + "\n" + df[['classement', 'competence']].to_csv(index=False, encoding='utf-8')

    headers = {'Content-Disposition': 'attachment; filename="skillscope_results.csv"'}
    return Response(content=csv_data.encode('utf-8'), media_type='text/csv', headers=headers)


# --- Logique d'Affichage et d'Analyse des Compétences ---
# Cette fonction sera appelée par le pipeline pour les mises à jour intermédiaires
# et le résultat final.
async def _update_ui_with_results(results_dict: Dict[str, Any], job_title_original: str, container: ui.column, loading_label: ui.html, table: ui.table, page_info_label: ui.label, pagination_buttons, is_final: bool):
    """
    Met à jour l'interface utilisateur avec les résultats de l'analyse,
    soit de manière progressive, soit avec le résultat final.
    """
    skills_data = results_dict.get('skills', [])
    top_diploma = results_dict.get('top_diploma', 'Non précisé')
    actual_offers = results_dict.get('actual_offers_count', 0)

    if not skills_data and not is_final: # Si aucune compétence encore et pas le résultat final
        loading_label.content = f"Analyse en cours pour <strong>'{job_title_original}'</strong> ({actual_offers} offres traitées)..."
        return # Attendre plus de données pour afficher le tableau

    formatted_skills = [{'classement': i + 1, 'competence': item['skill']} for i, item in enumerate(skills_data)]
    df = pd.DataFrame(formatted_skills)

    # Mise à jour du stockage pour l'exportation
    _store_results_for_client_export(ui.context.client.id, results_dict, job_title_original)


    # Gestion de l'affichage initial et des mises à jour
    if container.client.has_socket_connection: # S'assurer que le client est toujours connecté
        if not table.visible: # Première apparition du tableau
            loading_label.visible = False
            for comp in pagination_buttons:
                comp.visible = True
            table.visible = True
            with container:
                # Ajout des éléments de synthèse seulement à la fin ou si c'est la première fois qu'on affiche un tableau
                if is_final or not hasattr(container, 'synthesis_row'): # Ajout initial de la synthèse
                    with ui.row().classes('w-full items-baseline') as synthesis_row:
                        ui.label(f"Synthèse pour '{job_title_original}'").classes('text-2xl font-bold text-gray-800').bind_text_from(ui.context.element, 'synthesis_title_text')
                        ui.label(f"({actual_offers} offres analysées)").classes('text-sm text-gray-500 ml-2').bind_text_from(ui.context.element, 'synthesis_offers_count_text')
                    container.synthesis_row = synthesis_row # Marque le conteneur pour ne pas le recréer
                    ui.context.element.synthesis_title_text = f"Synthèse pour '{job_title_original}'"
                    ui.context.element.synthesis_offers_count_text = f"({actual_offers} offres analysées)"

                    with ui.row().classes('w-full mt-4 gap-4 flex-wrap items-stretch') as top_stats_row:
                        with ui.card().classes('items-center p-4 w-full sm:flex-1 flex flex-col justify-center min-h-[120px]') as top_skill_card:
                            ui.label('Top Compétence').classes('text-sm text-gray-500')
                            ui.label().classes('text-2xl font-bold text-center text-blue-600').bind_text_from(ui.context.element, 'top_skill_text')
                        with ui.card().classes('items-center p-4 w-full sm:flex-1 flex flex-col justify-center min-h-[120px]') as top_diploma_card:
                            ui.label('Niveau Demandé').classes('text-sm text-gray-500')
                            ui.label().classes('text-2xl font-bold text-blue-600').bind_text_from(ui.context.element, 'top_diploma_text')
                    container.top_stats_row = top_stats_row

                    ui.label("Classement des compétences").classes('text-xl font-bold mt-8 mb-2').bind_visible_from(table, 'visible')

                    with ui.row().classes('w-full justify-center gap-4 mb-2 flex-wrap') as export_buttons_row:
                        client_id = ui.context.client.id
                        ui.link('Export Excel', f'/download/excel/{client_id}', new_tab=True).classes('no-underline bg-green-600 text-white px-4 py-2 rounded-lg hover:bg-green-700')
                        ui.link('Export CSV', f'/download/csv/{client_id}', new_tab=True).classes('no-underline bg-slate-600 text-white px-4 py-2 rounded-lg hover:bg-slate-700')
                    container.export_buttons_row = export_buttons_row


        # Mettre à jour les labels de synthèse si elles existent (elles sont déjà créées dans la première passe)
        if hasattr(ui.context.element, 'synthesis_offers_count_text'):
            ui.context.element.synthesis_offers_count_text = f"({actual_offers} offres analysées)"
        if hasattr(ui.context.element, 'top_skill_text') and skills_data:
            ui.context.element.top_skill_text = formatted_skills[0]['competence']
        if hasattr(ui.context.element, 'top_diploma_text'):
            ui.context.element.top_diploma_text = top_diploma

        # Mettre à jour les lignes du tableau
        pagination_state = table.pagination._page_state # Accès direct à l'état de pagination
        pagination_state['rowsNumber'] = len(df) # Important pour la pagination

        table.rows = df.to_dict('records')

        # Recalculer le total des pages
        total_pages = max(1, (len(df) - 1) // pagination_state['rowsPerPage'] + 1)
        # S'assurer que la page actuelle ne dépasse pas le nouveau total de pages
        pagination_state['page'] = min(pagination_state['page'], total_pages)

        page_info_label.text = f"{pagination_state['page']} sur {total_pages}"
        # Mettre à jour les états des boutons de pagination
        pagination_buttons[0].set_enabled(pagination_state['page'] > 1) # btn_first
        pagination_buttons[1].set_enabled(pagination_state['page'] > 1) # btn_prev
        pagination_buttons[2].set_enabled(pagination_state['page'] < total_pages) # btn_next
        pagination_buttons[3].set_enabled(pagination_state['page'] < total_pages) # btn_last

        # Forcer la mise à jour de l'UI
        await ui.run_javascript('NiceGUI.events.emit("update");', respond=False) # Forcer un refresh


@ui.page('/')
def main_page(client: Client):
    """
    [cite_start]Construit et configure la page principale de l'application SkillScope. [cite: 1]
    [cite_start]Cette fonction est exécutée une fois par nouvelle session utilisateur. [cite: 1]
    """
    job_input: ui.input = None
    results_container: ui.column = None
    loading_label: ui.html = None # Pour le label "Analyse en cours..."
    main_table: ui.table = None # Pour le tableau principal
    page_info_label: ui.label = None # Pour l'information de pagination
    pagination_buttons = [] # Pour stocker les boutons de pagination

    log_view: ui.log = None
    all_log_messages: List[str] = []

    # [cite_start]Configure un logger spécifique pour cette session utilisateur afin d'isoler les logs. [cite: 1]
    session_logger = logging.getLogger(f"session_logger_{id(client)}")
    [cite_start]session_logger.handlers.clear() # S'assure qu'aucun ancien handler n'est attaché. [cite: 1]
    [cite_start]session_logger.setLevel(logging.INFO) # Définit le niveau de log à INFO pour un suivi détaillé. [cite: 1]

    # [cite_start]Configure le logger racine pour la propagation des messages vers la console du serveur. [cite: 1]
    root_logger = logging.getLogger()
    [cite_start]if not root_logger.handlers: # Ajoute un handler de console seulement si aucun n'est déjà présent. [cite: 1]
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(name)s - %(message)s'))
        root_logger.addHandler(console_handler)
    [cite_start]root_logger.setLevel(logging.INFO) # Définit le niveau minimum de log pour le logger racine. [cite: 1]


    # --- Configuration du HTML Head et Styles CSS Globaux ---
    ui.add_head_html('''
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            .no-underline { text-decoration: none !important; }
            .footer-links a {
                text-decoration: none !important;
                color: #2474c5;
                font-weight: bold;
            }
            .footer-links a:hover {
                text-decoration: none !important;
            }
        </style>
    ''')
    [cite_start]app.add_static_files('/assets', 'assets') # Sert les fichiers statiques (ex: logo SkillScope.svg). [cite: 1]
    [cite_start]ui.query('body').style('background-color: #f8fafc;') # Définit la couleur de fond du corps de la page. [cite: 1]

    # --- En-tête de l'Application ---
    with ui.header(elevated=True).classes('bg-white text-black px-4'):
        with ui.row().classes('w-full items-center justify-center'):
            # [cite_start]Logo ajusté [cite: 1]
            ui.image('/assets/SkillScope.svg').classes('h-auto max-w-full object-contain w-40 md:w-48')


    # --- Contenu Principal de la Page ---
    with ui.column().classes('w-full max-w-4xl mx-auto p-4 md:p-8 items-center gap-4'):
        ui.markdown("### Un outil pour analyser les compétences les plus demandées sur le marché de l'emploi.").classes('text-center font-light text-gray-800')
        ui.html("<i>Basé sur les données de <b>France Travail</b> et l'analyse de l'IA <b>Google Gemini.</b></i>").classes('text-center text-gray-500 mb-6')

        ui.html('<p style="font-size: 0.85em; color: #6b7280; text-align: center;">'
                'Cette analyse est indicative et peut contenir des variations ou incohérences dues à l\'IA. Les résultats sont une représentation du marché.</p>').classes('mt-1 mb-4')


        # --- Section de Recherche ---
        with ui.row().classes('w-full max-w-lg items-stretch'):
            job_input = ui.input(placeholder="Chercher un métier").props('outlined dense clearable').classes('w-full text-lg')

        # Conteneur pour le spinner et le message initial
        initial_feedback_container = ui.column().classes('w-full p-4 items-center')
        with initial_feedback_container:
            loading_spinner = ui.spinner(size='lg', color='primary').bind_visible_from(initial_feedback_container, 'visible')
            loading_label = ui.html(f"").classes('text-gray-600 mt-4 text-lg').bind_visible_from(initial_feedback_container, 'visible')
            initial_feedback_container.visible = False # Masquer initialement


        # Conteneur pour les résultats (tableau, synthèse, etc.)
        results_container = ui.column().classes('w-full mt-6')
        with results_container:
            # Placeholder pour les éléments de synthèse qui seront créés dynamiquement
            ui.label().classes('text-2xl font-bold text-gray-800').style('display: none;') # Cache initiallement
            ui.label().classes('text-sm text-gray-500 ml-2').style('display: none;') # Cache initiallement

            # Placeholders for top skill/diploma cards
            ui.card().classes('items-center p-4 w-full sm:flex-1 flex flex-col justify-center min-h-[120px]').style('display: none;')
            ui.card().classes('items-center p-4 w-full sm:flex-1 flex flex-col justify-center min-h-[120px]').style('display: none;')

            ui.label().classes('text-xl font-bold mt-8 mb-2').style('display: none;') # Cache initiallement
            ui.row().classes('w-full justify-center gap-4 mb-2 flex-wrap').style('display: none;') # Cache initiallement (export buttons)

            # Table for skills
            main_table = ui.table(
                columns=[
                    {'name': 'classement', 'label': '#', 'field': 'classement', 'align': 'left', 'style': 'width: 10%'},
                    {'name': 'competence', 'label': 'Compétence', 'field': 'competence', 'align': 'left', 'style': 'width: 70%'},
                ],
                rows=[],
                row_key='competence'
            ).props('flat bordered').classes('w-full').bind_visible_from(results_container, 'visible', backward=lambda x: not x) # Cache initiallement

            with ui.row().classes('w-full justify-center items-center gap-2 mt-4'):
                btn_first = ui.button('<<').props('flat dense color=black').bind_visible_from(main_table, 'visible')
                btn_prev = ui.button('<').props('flat dense color=black').bind_visible_from(main_table, 'visible')
                page_info_label = ui.label().bind_visible_from(main_table, 'visible')
                btn_next = ui.button('>').props('flat dense color=black').bind_visible_from(main_table, 'visible')
                btn_last = ui.button('>>').props('flat dense color=black').bind_visible_from(main_table, 'visible')
                pagination_buttons = [btn_first, btn_prev, btn_next, btn_last]
                for comp in pagination_buttons:
                    comp.visible = False # Masquer initiallement

            def update_table_pagination():
                """Met à jour les lignes du tableau et l'état des boutons de pagination."""
                df_current = pd.DataFrame(main_table.rows) # Obtenir les données actuelles
                pagination_state = main_table.pagination._page_state
                total_pages = max(1, (len(df_current) - 1) // pagination_state['rowsPerPage'] + 1)
                start = (pagination_state['page'] - 1) * pagination_state['rowsPerPage']
                end = start + pagination_state['rowsPerPage']

                # Update table rows based on current pagination
                main_table.rows = df_current.iloc[start:end][['classement', 'competence']].to_dict('records')
                page_info_label.text = f"{pagination_state['page']} sur {total_pages}"
                btn_first.set_enabled(pagination_state['page'] > 1)
                btn_prev.set_enabled(pagination_state['page'] > 1)
                btn_next.set_enabled(pagination_state['page'] < total_pages)
                btn_last.set_enabled(pagination_state['page'] < total_pages)

            btn_first.on_click(lambda: (main_table.pagination._page_state.update(page=1), update_table_pagination()))
            btn_prev.on_click(lambda: (main_table.pagination._page_state.update(page=max(1, main_table.pagination._page_state['page'] - 1)), update_table_pagination()))
            btn_next.on_click(lambda: (main_table.pagination._page_state.update(page=min(total_pages, main_table.pagination._page_state['page'] + 1)), update_table_pagination()))
            btn_last.on_click(lambda: (main_table.pagination._page_state.update(page=total_pages), update_table_pagination()))


        async def handle_analysis_click():
            """
            [cite_start]Gère l'événement de clic sur le bouton d'analyse, lançant le pipeline et affichant les résultats. [cite: 1]
            [cite_start]Cette fonction gère également les recherches concurrentes pour un même terme. [cite: 1]
            """
            [cite_start]original_job_term = job_input.value # Récupère le terme tel qu'entré par l'utilisateur. [cite: 1]
            [cite_start]normalized_job_term = _normalize_search_term(original_job_term) # Normalise le terme pour la logique interne et le cache. [cite: 1]

            session_logger.info(f"Déclenchement d'une nouvelle analyse pour '{original_job_term}'.")

            if not original_job_term:
                session_logger.warning("Analyse annulée : aucun métier n'a été entré.")
                return

            # [cite_start]Vérifie si une recherche pour ce métier (normalisé) est déjà en cours. [cite: 1]
            if normalized_job_term in _active_searches:
                session_logger.info(f"Recherche pour '{normalized_job_term}' déjà en cours; l'utilisateur patiente.")
                initial_feedback_container.visible = True
                loading_label.content = f"Une analyse pour <strong>'{original_job_term}'</strong> est déjà en cours. Veuillez patienter..."
                return

            # [cite_start]Crée une future pour représenter la recherche en cours et l'ajoute au dictionnaire des recherches actives. [cite: 1]
            search_future = asyncio.Future()
            _active_searches[normalized_job_term] = search_future

            ui_log_handler_instance = None # Initialisation du handler de log.

            try:
                # Réinitialiser l'affichage
                results_container.clear()
                initial_feedback_container.visible = True
                loading_spinner.visible = True
                loading_label.visible = True
                loading_label.content = f"Analyse en cours pour <strong>'{original_job_term}'</strong>..."
                main_table.visible = False # Masquer le tableau au début

                # [cite_start]Attache le handler de log de l'UI (pour les logs techniques du développeur) si en mode non-production. [cite: 1]
                if not IS_PRODUCTION_MODE:
                    ui_log_handler_instance = UiLogHandler(log_view, all_log_messages)
                    session_logger.addHandler(ui_log_handler_instance)

                # Callback pour les mises à jour progressives de l'UI
                async def progress_update_callback(current_results: Dict[str, Any], final: bool):
                    await _update_ui_with_results(current_results, original_job_term, results_container, loading_label, main_table, page_info_label, pagination_buttons, final)

                # Exécute le pipeline d'analyse avec le terme normalisé.
                # Utilisez la nouvelle fonction get_skills_for_job_streaming
                results = await get_skills_for_job_streaming(normalized_job_term, NB_OFFERS_TO_ANALYZE, session_logger, progress_update_callback)

                if results is None or not results.get("skills"):
                    session_logger.error("Le pipeline n'a retourné aucun résultat exploitable ou aucune compétence.")
                    results_container.clear() # Nettoyer les résultats partiels si erreur
                    initial_feedback_container.visible = True
                    loading_spinner.visible = False
                    loading_label.content = f"Aucun résultat trouvé pour <strong>'{original_job_term}'</strong>. Veuillez réessayer."
                    return

                # Si l'analyse est complète et réussie, la dernière mise à jour via le callback aura affiché les résultats
                # et masqué le spinner. On n'a plus besoin d'appeler display_results ici.

            except Exception as e:
                session_logger.critical(f"ERREUR CRITIQUE PENDANT L'ANALYSE : {e}", exc_info=True)
                results_container.clear()
                initial_feedback_container.visible = True
                loading_spinner.visible = False
                loading_label.content = f"Une erreur est survenue lors de l'analyse : {e}"
            finally:
                # [cite_start]Détache le handler temporaire si il a été créé et attaché. [cite: 1]
                if ui_log_handler_instance is not None and ui_log_handler_instance in session_logger.handlers:
                    session_logger.removeHandler(ui_log_handler_instance)

                # [cite_start]Marque la Future comme terminée et retire le verrou. [cite: 1]
                if not search_future.done():
                    search_future.set_result(True)
                if normalized_job_term in _active_searches:
                    del _active_searches[normalized_job_term]

            session_logger.info("Fin du processus global de l'analyse.")


        launch_button = ui.button("Lancer l'analyse", on_click=handle_analysis_click).props('color=primary').classes('w-full max-w-lg mt-4')

        # [cite_start]Active le bouton de lancement uniquement si le champ d'entrée contient une valeur. [cite: 1]
        launch_button.bind_enabled_from(job_input, 'value', backward=bool)

        # Le results_container est défini plus haut et contient les éléments dynamiques

        # --- Footer ---
        with ui.column().classes('w-full items-center mt-8 pt-2 border-t'):
            ui.html('<p style="font-size: 0.875em; color: #6b7280;"><b style="color: black;">Développé par</b> <span style="color: #f9b15c; font-weight: bold;">Hamza Kachmir</span></p>')
            with ui.row().classes('gap-4 mt-2 footer-links'):
                ui.html('<a href="https://portfolio-hamza-kachmir.vercel.app/" target="_blank">Portfolio</a>') # Lien vers le portfolio.
                ui.html('<a href="https://www.linkedin.com/in/hamza-kachmir/" target="_blank">LinkedIn</a>') # Lien vers le profil LinkedIn.


        # --- Section "Logs & Outils" (visible ou masquée selon IS_PRODUCTION_MODE) ---
        [cite_start]if not IS_PRODUCTION_MODE: # Cette section est affichée uniquement en mode non-production pour le débogage. [cite: 1]
            with ui.expansion("Voir les logs & Outils", icon='o_code').classes('w-full mt-12 bg-gray-50 rounded-lg'):
                with ui.column().classes('w-full p-2'):
                    [cite_start]log_view = ui.log().classes('w-full h-40 bg-gray-800 text-white font-mono text-xs') # Affiche les logs de session. [cite: 1]
                    with ui.row().classes('mt-2 gap-2'):
                        [cite_start]ui.button('Vider tout le cache', on_click=lambda: (flush_all_cache(), ui.notify('Cache vidé avec succès !', color='positive')), color='red-6', icon='o_delete_forever') # Bouton pour vider le cache. [cite: 1]
                        [cite_start]ui.button('Copier les logs', on_click=lambda: ui.run_javascript(f'navigator.clipboard.writeText(`{"\\n".join(all_log_messages)}`)'), icon='o_content_copy') # Bouton pour copier les logs. [cite: 1]

                    [cite_start]session_logger.addHandler(UiLogHandler(log_view, all_log_messages)) # Attache le gestionnaire de log personnalisé à ce logger de session. [cite: 1]


if __name__ in {"__main__", "__mp_main__"}:
    [cite_start]port = int(os.environ.get('PORT', 10000)) # Récupère le port depuis les variables d'environnement ou utilise 10000 par défaut. [cite: 1]
    [cite_start]ui.run(host='0.0.0.0', port=port, title='SkillScope | Analyse de compétences', favicon='assets/SkillScope.svg') # Lance l'application NiceGUI. [cite: 1]