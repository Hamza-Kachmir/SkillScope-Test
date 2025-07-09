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

from pipeline import get_skills_for_job
from src.cache_manager import flush_all_cache

# --- Constantes de configuration ---
NB_OFFERS_TO_ANALYZE = 100 # Nombre d'offres d'emploi à analyser par défaut.

# Détermine si l'application est en mode production.
# Si 'PRODUCTION_MODE' est défini à 'true' ou '1' dans les variables d'environnement,
# les logs UI et les outils d'administration seront masqués.
IS_PRODUCTION_MODE = os.getenv('PRODUCTION_MODE', 'false').lower() in ('true', '1')

# --- Stockage Global pour l'Export ---
# Dictionnaire pour stocker temporairement les données d'export (Excel/CSV) par ID de session client.
# Cela permet aux endpoints de téléchargement d'accéder aux données spécifiques à un utilisateur.
_export_data_storage: Dict[str, Dict[str, Any]] = {}

# --- Verrouillage des Recherches Concurrentes ---
# Dictionnaire pour gérer les recherches de métiers déjà en cours.
# Empêche le lancement de requêtes API redondantes pour le même terme.
_active_searches: Dict[str, asyncio.Future] = {}

def _normalize_search_term(term: str) -> str:
    """
    Normalise une chaîne de caractères pour une utilisation cohérente comme clé de recherche ou de cache.
    Convertit le terme en minuscules, supprime les accents et les espaces superflus.
    Exemple : "Développeur Web" devient "developpeur web".

    :param term: La chaîne de caractères à normaliser.
    :return: La chaîne normalisée.
    """
    # Normalise les caractères Unicode pour décomposer les caractères accentués.
    normalized_term = unicodedata.normalize('NFKD', term)
    # Encode en ASCII (ignorant les caractères non-ASCII, y compris les accents)
    # puis décode en UTF-8, convertit en minuscules et supprime les espaces blancs.
    normalized_term = normalized_term.encode('ascii', 'ignore').decode('utf-8').lower().strip()
    return normalized_term


# --- Gestionnaire de Logs pour l'Interface Utilisateur (pour le développeur) ---
class UiLogHandler(logging.Handler):
    """
    Un gestionnaire de logs personnalisé qui pousse les messages vers un élément `ui.log` de NiceGUI
    (pour le développeur). En mode production, il est désactivé pour l'UI.
    """
    def __init__(self, log_element: ui.log, log_messages_list: list):
        super().__init__()
        self.log_element = log_element
        self.log_messages_list = log_messages_list
        # Définit le format des messages de log affichés dans l'UI développeur.
        self.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(name)s - %(message)s'))

    def emit(self, record):
        """
        Formate un enregistrement de log et tente de le pousser vers l'interface utilisateur (pour le développeur).
        Si le client est déconnecté, le message est imprimé dans la console de secours.
        """
        try:
            msg = self.format(record)
            self.log_messages_list.append(msg)
            
            # Pousse le log brut vers l'élément ui.log (pour le développeur) si en mode non-production
            if not IS_PRODUCTION_MODE and self.log_element and hasattr(self.log_element, 'push') and self.log_element.client.has_socket_connection:
                self.log_element.push(msg)
            
        except Exception as e:
            print(f"Erreur dans UiLogHandler: {e}")


# --- Points de terminaison (API Endpoints) pour le téléchargement ---
@app.get('/download/excel/{client_id}') 
def download_excel_endpoint(client_id: str): 
    """
    Point de terminaison FastAPI pour télécharger les résultats au format Excel.
    L'ID du client est utilisé pour récupérer les données spécifiques à la session.

    :param client_id: L'identifiant unique de la session client.
    :return: Une réponse HTTP avec le fichier Excel ou une erreur 404 si les données sont introuvables.
    """
    if client_id not in _export_data_storage:
        logging.warning(f"Export Excel demandé pour un client_id inconnu ou expiré: {client_id}")
        return Response("Aucune donnée à exporter ou session expirée.", media_type='text/plain', status_code=404)
    
    data = _export_data_storage[client_id]
    df = data.get('df') # Récupère le DataFrame complet, y compris la fréquence
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
        # Exclure la colonne 'frequence' lors de l'export vers Excel
        df[['classement', 'competence']].to_excel(writer, index=False, sheet_name='Resultats', startrow=len(header_info)-1) 
    
    headers = {'Content-Disposition': 'attachment; filename="skillscope_results.xlsx"'}
    return Response(content=output.getvalue(), media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', headers=headers)


@app.get('/download/csv/{client_id}') 
def download_csv_endpoint(client_id: str): 
    """
    Point de terminaison FastAPI pour télécharger les résultats au format CSV.
    L'ID du client est utilisé pour récupérer les données spécifiques à la session.

    :param client_id: L'identifiant unique de la session client.
    :return: Une réponse HTTP avec le fichier CSV ou une erreur 404 si les données sont introuvables.
    """
    if client_id not in _export_data_storage:
        logging.warning(f"Export CSV demandé pour un client_id inconnu ou expiré: {client_id}")
        return Response("Aucune donnée à exporter ou session expirée.", media_type='text/plain', status_code=404)

    data = _export_data_storage[client_id]
    df = data.get('df') # Récupère le DataFrame complet, y compris la fréquence
    job_title = data.get('job_title', 'Non précisé')
    offers_count = data.get('actual_offers_count', 0)

    if df is None or df.empty:
        return Response("Aucune donnée à exporter.", media_type='text/plain', status_code=404)
    
    header_lines = [
        f"Métier Analysé: {job_title}",
        f"Offres Analysées: {offers_count}",
        ""
    ]
    # Exclure la colonne 'frequence' lors de l'export vers CSV
    csv_data = "\n".join(header_lines) + "\n" + df[['classement', 'competence']].to_csv(index=False, encoding='utf-8') 
    
    headers = {'Content-Disposition': 'attachment; filename="skillscope_results.csv"'}
    return Response(content=csv_data.encode('utf-8'), media_type='text/csv', headers=headers)


# --- Logique d'Affichage et d'Analyse des Compétences ---
async def _run_analysis_pipeline(job_input_val: str, logger_instance: logging.Logger) -> Optional[Dict[str, Any]]:
    """
    Exécute le pipeline d'analyse complet : recherche d'offres et extraction de compétences.
    Cette fonction est isolée des interactions UI directes pendant son exécution.

    Le `job_input_val` est déjà normalisé (minuscules, sans accents) à ce stade.

    :param job_input_val: Le terme de métier normalisé pour l'analyse.
    :param logger_instance: L'instance de logger spécifique à la session.
    :return: Le dictionnaire de résultats agrégés, ou None en cas d'échec.
    """
    logger_instance.info(f"Début du pipeline d'analyse pour '{job_input_val}'.")
    if not job_input_val:
        logger_instance.warning("Analyse annulée dans le pipeline : aucun métier n'a été entré.")
        return None

    try:
        logger_instance.info(f"Appel du pipeline pour '{job_input_val}' avec {NB_OFFERS_TO_ANALYZE} offres.")
        results = await get_skills_for_job(job_input_val, NB_OFFERS_TO_ANALYZE, logger_instance)
        
        if results is None:
            logger_instance.warning("Le pipeline n'a retourné aucun résultat pour la recherche.")
            return None
        
        logger_instance.info(f"Fin du pipeline d'analyse pour '{job_input_val}'.")
        return results

    except Exception as e:
        logger_instance.critical(f"ERREUR CRITIQUE DANS LE PIPELINE D'ANALYSE : {e}", exc_info=True)
        return None


def _store_results_for_client_export(client_id: str, results: Dict[str, Any], job_title_original: str): 
    """
    Stocke les résultats de l'analyse dans un dictionnaire global, indexé par l'ID du client.
    Ces données seront utilisées par les endpoints de téléchargement.

    :param client_id: L'ID unique du client (session utilisateur) ayant lancé l'analyse.
    :param results: Le dictionnaire de résultats à stocker.
    :param job_title_original: Le terme de métier original (non normalisé) pour l'affichage dans l'export.
    """
    df_to_store = pd.DataFrame([
        {'classement': i + 1, 'competence': item['skill'], 'frequence': item['frequency']} 
        for i, item in enumerate(results.get('skills', []))
    ])
    
    _export_data_storage[client_id] = {
        'df': df_to_store,
        'job_title': job_title_original, 
        'actual_offers_count': results.get('actual_offers_count', 0)
    }


def display_results(container: ui.column, results_dict: Dict[str, Any], job_title_original: str): 
    """
    Construit et met à jour dynamiquement la section des résultats dans l'interface utilisateur.

    :param container: L'élément UI (colonne) où les résultats doivent être affichés.
    :param results_dict: Le dictionnaire de résultats agrégés à afficher.
    :param job_title_original: Le terme de métier original (non normalisé) pour l'affichage.
    """
    container.clear()

    skills_data = results_dict.get('skills', [])
    top_diploma = results_dict.get('top_diploma', 'Non précisé')
    actual_offers = results_dict.get('actual_offers_count', 0)

    if not skills_data:
        with container:
            ui.label("Aucune offre ou compétence pertinente n'a pu être extraite.").classes('text-yellow-800')
        return

    # La fréquence est toujours calculée mais pas formatée pour l'affichage ici.
    formatted_skills = [{'classement': i + 1, 'competence': item['skill']} for i, item in enumerate(skills_data)]
    df = pd.DataFrame(formatted_skills)

    with container:
        # Correction de la syntaxe pour les ui.row().classes
        with ui.row().classes('w-full items-baseline'):
            ui.label(f"Synthèse pour '{job_title_original}'").classes('text-2xl font-bold text-gray-800') 
            ui.label(f"({actual_offers} offres analysées)").classes('text-sm text-gray-500 ml-2')

        # Harmonisation de la taille des cartes Top Compétence et Niveau Demandé
        with ui.row().classes('w-full mt-4 gap-4 flex-wrap items-stretch'): # <-- Ajout items-stretch ici
            with ui.card().classes('items-center p-4 w-full sm:flex-1 flex flex-col justify-center min-h-[120px]'):
                ui.label('Top Compétence').classes('text-sm text-gray-500')
                ui.label(formatted_skills[0]['competence']).classes('text-2xl font-bold text-center text-blue-600')
            with ui.card().classes('items-center p-4 w-full sm:flex-1 flex flex-col justify-center min-h-[120px]'):
                ui.label('Niveau Demandé').classes('text-sm text-gray-500')
                ui.label(top_diploma).classes('text-2xl font-bold text-blue-600')
        
        ui.label("Classement des compétences").classes('text-xl font-bold mt-8 mb-2')
        with ui.row().classes('w-full justify-center gap-4 mb-2 flex-wrap'):
            client_id = ui.context.client.id 
            ui.link('Export Excel', f'/download/excel/{client_id}', new_tab=True).classes('no-underline bg-green-600 text-white px-4 py-2 rounded-lg hover:bg-green-700')
            ui.link('Export CSV', f'/download/csv/{client_id}', new_tab=True).classes('no-underline bg-slate-600 text-white px-4 py-2 rounded-lg hover:bg-slate-700')

        pagination_state = {'page': 1, 'rows_per_page': 10}
        total_pages = max(1, (len(df) - 1) // pagination_state['rows_per_page'] + 1)
        
        table = ui.table(
            columns=[
                {'name': 'classement', 'label': '#', 'field': 'classement', 'align': 'left', 'style': 'width: 10%'},
                {'name': 'competence', 'label': 'Compétence', 'field': 'competence', 'align': 'left', 'style': 'width: 70%'},
                # La colonne 'frequence' est supprimée de l'affichage
                # {'name': 'frequence', 'label': 'Fréquence', 'field': 'frequence', 'align': 'left', 'style': 'width: 20%'},
            ],
            rows=[], 
            row_key='competence'
        ).props('flat bordered').classes('w-full')

        with ui.row().classes('w-full justify-center items-center gap-2 mt-4'):
            btn_first = ui.button('<<', on_click=lambda: (pagination_state.update(page=1), update_table())).props('flat dense color=black')
            btn_prev = ui.button('<', on_click=lambda: (pagination_state.update(page=max(1, pagination_state['page'] - 1)), update_table())).props('flat dense color=black')
            
            page_info_label = ui.label() 
            
            btn_next = ui.button('>', on_click=lambda: (pagination_state.update(page=min(total_pages, pagination_state['page'] + 1)), update_table())).props('flat dense color=black')
            btn_last = ui.button('>>', on_click=lambda: (pagination_state.update(page=total_pages), update_table())).props('flat dense color=black')

        def update_table():
            """Met à jour les lignes du tableau et l'état des boutons de pagination."""
            start = (pagination_state['page'] - 1) * pagination_state['rows_per_page']
            end = start + pagination_state['rows_per_page']
            # Sélectionne uniquement les colonnes 'classement' et 'competence'
            table.rows = df.iloc[start:end][['classement', 'competence']].to_dict('records') 
            page_info_label.text = f"{pagination_state['page']} sur {total_pages}"
            btn_first.set_enabled(pagination_state['page'] > 1)
            btn_prev.set_enabled(pagination_state['page'] > 1)
            btn_next.set_enabled(pagination_state['page'] < total_pages)
            btn_last.set_enabled(pagination_state['page'] < total_pages)

        update_table()


@ui.page('/')
def main_page(client: Client):
    """
    Construit et configure la page principale de l'application.
    Cette fonction est exécutée une fois par nouvelle session utilisateur, assurant un état isolé.

    :param client: L'objet client NiceGUI représentant la session utilisateur actuelle.
    """
    job_input: ui.input = None
    results_container: ui.column = None
    
    log_view: ui.log = None
    all_log_messages: List[str] = [] # Liste de messages de log propre à cette session UI.

    # Configure un logger spécifique pour cette session utilisateur, pour isoler les logs.
    session_logger = logging.getLogger(f"session_logger_{id(client)}") 
    session_logger.handlers.clear() # S'assure qu'aucun ancien handler n'est attaché à ce logger.
    session_logger.setLevel(logging.INFO) # Définit le niveau de log à INFO pour un suivi détaillé en mode développement/test.

    # Configure le logger racine pour la propagation des messages vers la console du serveur.
    root_logger = logging.getLogger()
    if not root_logger.handlers: # Ajoute un handler de console seulement si aucun n'est déjà présent.
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(name)s - %(message)s'))
        root_logger.addHandler(console_handler)
    root_logger.setLevel(logging.INFO) # Définit le niveau minimum de log pour le logger racine.


    # --- Configuration du HTML Head et Styles CSS Globaux ---
    ui.add_head_html('''
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            .no-underline { text-decoration: none !important; }
            /* Règle CSS plus spécifique pour les liens dans le pied de page pour éviter le soulignement. */
            .footer-links a { 
                text-decoration: none !important; 
                color: #2474c5; /* Couleur par défaut pour les liens du pied de page */
                font-weight: bold;
            }
            .footer-links a:hover { 
                text-decoration: none !important; /* Pas de soulignement au survol */
            }
        </style>
    ''')
    app.add_static_files('/assets', 'assets') # Sert les fichiers statiques (ex: logo SkillScope.svg).
    ui.query('body').style('background-color: #f8fafc;') # Définit la couleur de fond du corps de la page.

    # --- En-tête de l'Application ---
    with ui.header(elevated=True).classes('bg-white text-black px-4'):
        with ui.row().classes('w-full items-center justify-center'):
            ui.image('/assets/SkillScope.svg').classes('w-40 md:w-48')

    # --- Contenu Principal de la Page ---
    with ui.column().classes('w-full max-w-4xl mx-auto p-4 md:p-8 items-center gap-4'):
        ui.markdown("### Un outil pour quantifier les compétences les plus demandées sur le marché de l'emploi.").classes('text-center font-light text-gray-800')
        # Phrase d'introduction
        ui.html("<i>Basé sur les données de <b>France Travail</b> et l'analyse de l'IA <b>Google Gemini.</b></i>").classes('text-center text-gray-500 mb-6')
        
        # Nouveau message court de disclaimer, placé APRÈS la phrase d'introduction, sans astérisque
        ui.html('<p style="font-size: 0.85em; color: #6b7280; text-align: center;">'
                'Cette analyse est indicative et peut contenir des variations ou incohérences dues à l\'IA. Les résultats sont une représentation du marché.</p>').classes('mt-1 mb-4')


        # --- Section de Recherche ---
        with ui.row().classes('w-full max-w-lg items-stretch'):
            job_input = ui.input(placeholder="Chercher un métier").props('outlined dense clearable').classes('w-full text-lg')
        
        async def handle_analysis_click():
            """
            Gère l'événement de clic sur le bouton d'analyse.
            Lance le pipeline d'analyse et gère l'affichage des résultats et des erreurs.
            """
            original_job_term = job_input.value # Récupère le terme tel qu'entré par l'utilisateur.
            normalized_job_term = _normalize_search_term(original_job_term) # Normalise le terme pour la logique interne et le cache.
            
            session_logger.info(f"Déclenchement d'une nouvelle analyse. Terme original: '{original_job_term}', Terme normalisé: '{normalized_job_term}'.")
            
            if not original_job_term: 
                session_logger.warning("Analyse annulée : aucun métier n'a été entré.")
                return

            # Vérifie si une recherche pour ce métier (normalisé) est déjà en cours.
            if normalized_job_term in _active_searches:
                session_logger.info(f"Recherche pour '{normalized_job_term}' déjà en cours. L'utilisateur est mis en attente.")
                results_container.clear()
                with results_container:
                    ui.label(f"Une analyse pour '{original_job_term}' est déjà en cours. Veuillez patienter...").classes('text-gray-600 mt-4 text-lg')
                
                try:
                    # Attendre la fin de la recherche déjà active et s'assurer que le verrou est retiré.
                    await _active_searches[normalized_job_term] 
                    session_logger.info(f"Reprise de la session après attente pour '{normalized_job_term}'. Les résultats seront servis via le cache.")
                    
                    # Après l'attente, les résultats devraient être en cache. Relance le pipeline
                    # pour les récupérer du cache et les afficher à l'utilisateur qui attendait.
                    results_for_display = await _run_analysis_pipeline(normalized_job_term, session_logger)
                    if results_for_display:
                         _store_results_for_client_export(client.id, results_for_display, original_job_term)
                         display_results(results_container, results_for_display, original_job_term)
                    else:
                        session_logger.error(f"La recherche pour '{normalized_job_term}' n'a pas produit de résultats valides même après attente du verrou.")
                        results_container.clear()
                        with results_container:
                            ui.label(f"Aucun résultat trouvé pour '{original_job_term}' après attente. Veuillez réessayer.").classes('text-negative')
                    
                except Exception as e:
                    session_logger.error(f"Erreur lors de l'attente de la recherche en cours pour '{normalized_job_term}': {e}", exc_info=True)
                    results_container.clear()
                    with results_container:
                        ui.label(f"Une erreur est survenue lors de l'attente de l'analyse : {e}").classes('text-negative')
                finally:
                    # S'assurer que le verrou est retiré même si l'attente échoue ou est annulée
                    if normalized_job_term in _active_searches and _active_searches[normalized_job_term].done():
                         del _active_searches[normalized_job_term]
                    
                return

            search_future = asyncio.Future()
            _active_searches[normalized_job_term] = search_future 

            # Déclaration et initialisation du handler ici pour garantir sa portée
            ui_log_handler_instance = None 

            try:
                client_id_for_export = client.id

                # Affiche l'UI de chargement simple (spinner + message)
                results_container.clear()
                with results_container:
                    with ui.column().classes('w-full p-4 items-center'):
                        ui.spinner(size='lg', color='primary')
                        ui.html(f"Analyse en cours pour <strong>'{original_job_term}'</strong>...").classes('text-gray-600 mt-4 text-lg')
                        # Les éléments de progression utilisateur détaillés ne sont plus affichés.

                # Attache le handler de log de l'UI (qui ne gérera que les logs techniques pour le développeur).
                if not IS_PRODUCTION_MODE:
                    ui_log_handler_instance = UiLogHandler(log_view, all_log_messages)
                    session_logger.addHandler(ui_log_handler_instance)
                
                # Exécute le pipeline d'analyse avec le terme normalisé.
                results = await _run_analysis_pipeline(normalized_job_term, session_logger) 
                
                if results is None:
                    session_logger.error("Le pipeline n'a retourné aucun résultat exploitable.")
                    results_container.clear()
                    with results_container:
                        ui.label(f"Aucun résultat trouvé pour '{original_job_term}'.").classes('text-negative')
                    return

                _store_results_for_client_export(client_id_for_export, results, original_job_term) 

                display_results(results_container, results, original_job_term) 

            except Exception as e:
                session_logger.critical(f"ERREUR CRITIQUE PENDANT L'ANALYSE : {e}", exc_info=True)
                results_container.clear()
                with results_container:
                    ui.label(f"Une erreur est survenue : {e}").classes('text-negative')
            finally:
                # Détacher le handler temporaire si il a été créé et attaché.
                if ui_log_handler_instance is not None and ui_log_handler_instance in session_logger.handlers:
                    session_logger.removeHandler(ui_log_handler_instance)

                # Marque la Future comme terminée (succès ou échec) et retire le verrou.
                if not search_future.done():
                    search_future.set_result(True) 
                # Le verrou est toujours retiré, même en cas d'erreur ou d'échec
                if normalized_job_term in _active_searches:
                    del _active_searches[normalized_job_term] 

            session_logger.info("Fin du processus global de l'analyse.")


        launch_button = ui.button("Lancer l'analyse", on_click=handle_analysis_click).props('color=primary').classes('w-full max-w-lg mt-4')
        
        launch_button.bind_enabled_from(job_input, 'value', backward=bool)

        results_container = ui.column().classes('w-full mt-6')

        # --- Pied de Page et Liens Externes ---
        with ui.column().classes('w-full items-center mt-8 pt-6 border-t'):
            ui.html('<p style="font-size: 0.875em; color: #6b7280;"><b style="color: black;">Développé par</b> <span style="color: #f9b15c; font-weight: bold;">Hamza Kachmir</span></p>')
            with ui.row().classes('gap-4 mt-2 footer-links'): 
                ui.html('<a href="https://portfolio-hamza-kachmir.vercel.app/" target="_blank">Portfolio</a>')
                ui.html('<a href="https://www.linkedin.com/in/hamza-kachmir/" target="_blank">LinkedIn</a>')
            # Le disclaimer est maintenant déplacé et simplifié juste au-dessus du footer
            # Il n'y a plus d'astérisque ni de paragraphe dans le footer même.


        # --- Section "Logs & Outils" (visible ou masquée selon IS_PRODUCTION_MODE) ---
        if not IS_PRODUCTION_MODE: # Cette section n'est affichée qu'en mode non-production.
            with ui.expansion("Voir les logs & Outils", icon='o_code').classes('w-full mt-12 bg-gray-50 rounded-lg'):
                with ui.column().classes('w-full p-2'):
                    log_view = ui.log().classes('w-full h-40 bg-gray-800 text-white font-mono text-xs')
                    with ui.row().classes('mt-2 gap-2'):
                        ui.button('Vider tout le cache', on_click=lambda: (flush_all_cache(), ui.notify('Cache vidé avec succès !', color='positive')), color='red-6', icon='o_delete_forever')
                        ui.button('Copier les logs', on_click=lambda: ui.run_javascript(f'navigator.clipboard.writeText(`{"\\n".join(all_log_messages)}`)'), icon='o_content_copy')
                
                # Attache le gestionnaire de log personnalisé à ce logger de session.
                session_logger.addHandler(UiLogHandler(log_view, all_log_messages)) 
        else:
            # En mode production, les logs techniques ne sont pas affichés dans l'UI.
            pass


if __name__ in {"__main__", "__mp_main__"}:
    port = int(os.environ.get('PORT', 10000))
    ui.run(host='0.0.0.0', port=port, title='SkillScope | Analyse de compétences', favicon='assets/SkillScope.svg')