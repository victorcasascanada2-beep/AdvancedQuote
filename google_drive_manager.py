import io
import sys
import logging
import traceback
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload
from google.oauth2 import service_account
import google.auth

# --- CONFIGURACIÓN DE IDs ---
ID_UNIDAD_COMPARTIDA = "0AEU0RHjR-mDOUk9PVA"
ID_CARPETA_RAIZ_TASACIONES = "1jHfVRjC6I0qPV9ArDIkhoKCYP7Iepmt9"
ID_FICHERO_VENDEDORES = "0AEU0RHjR-mDOUk9PVA"

SCOPES = ["https://www.googleapis.com/auth/drive"]

def _get_drive_service(creds_dict=None):
    """Obtiene el servicio de Drive (Híbrido: ADC o Service Account)."""
    try:
        if creds_dict is None:
            # MODO CLOUD RUN: Usa credenciales por defecto del sistema
            creds, _ = google.auth.default()
            creds = google.auth.credentials.with_scopes_if_required(creds, SCOPES)
        else:
            # MODO LOCAL: Usa el arreglo de secretos de Streamlit
            pk = str(creds_dict.get("private_key", "")).replace("\\n", "\n").strip()
            auth_info = {
                "type": "service_account",
                "project_id": creds_dict.get("project_id"),
                "private_key_id": creds_dict.get("private_key_id"),
                "private_key": pk,
                "client_email": creds_dict.get("client_email"),
                "client_id": creds_dict.get("client_id"),
                "token_uri": "https://oauth2.googleapis.com/token",
            }
            creds = service_account.Credentials.from_service_account_info(auth_info, scopes=SCOPES)

        return build("drive", "v3", credentials=creds, static_discovery=False)
    except Exception as e:
        print(f"❌ Error en _get_drive_service: {e}", file=sys.stderr)
        return None

def leer_vendedores(creds_dict=None):
    """Lee el archivo vendedores.txt de la Unidad Compartida."""
    service = _get_drive_service(creds_dict)
    if not service: return []
    try:
        request = service.files().get_media(fileId=ID_FICHERO_VENDEDORES)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        
        texto = fh.getvalue().decode('utf-8')
        return sorted([n.strip() for n in texto.splitlines() if n.strip()])
    except Exception as e:
        print(f"⚠️ Aviso: Error leyendo vendedores: {e}")
        return []

def actualizar_vendedores(creds_dict, lista_nombres):
    """Actualiza la lista de vendedores en Drive."""
    service = _get_drive_service(creds_dict)
    if not service: return False
    try:
        contenido = "\n".join(sorted(list(set(lista_nombres))))
        fh = io.BytesIO(contenido.encode('utf-8'))
        media = MediaIoBaseUpload(fh, mimetype='text/plain', resumable=False)
        service.files().update(
            fileId=ID_FICHERO_VENDEDORES,
            media_body=media,
            supportsAllDrives=True
        ).execute()
        return True
    except Exception as e:
        print(f"❌ Error actualizando vendedores: {e}")
        return False

def _get_or_create_folder(service, folder_name, parent_id):
    """Busca o crea una carpeta en la Unidad Compartida."""
    query = (f"name = '{folder_name}' and mimeType = 'application/vnd.google-apps.folder' "
             f"and '{parent_id}' in parents and trashed = false")
    
    resp = service.files().list(
        q=query, corpora="drive", driveId=ID_UNIDAD_COMPARTIDA,
        includeItemsFromAllDrives=True, supportsAllDrives=True, fields="files(id)"
    ).execute()

    files = resp.get("files", [])
    if files: return files[0]["id"]

    meta = {"name": folder_name, "mimeType": "application/vnd.google-apps.folder", "parents": [parent_id]}
    created = service.files().create(body=meta, supportsAllDrives=True, fields="id").execute()
    return created.get("id")

def subir_informe(creds_dict, nombre_archivo, contenido_html, folder_name="General"):
    """Sube el HTML a la carpeta correspondiente."""
    try:
        service = _get_drive_service(creds_dict)
        if not service: return None
        
        folder_id = _get_or_create_folder(service, folder_name, ID_CARPETA_RAIZ_TASACIONES)
        
        fh = io.BytesIO(contenido_html.encode("utf-8") if isinstance(contenido_html, str) else contenido_html)
        media = MediaIoBaseUpload(fh, mimetype="text/html", resumable=False)
        
        meta = {"name": nombre_archivo, "parents": [folder_id]}
        created = service.files().create(body=meta, media_body=media, supportsAllDrives=True, fields="id").execute()
        return created.get("id")
    except Exception as e:
        print(f"❌ Error subiendo informe: {e}")
        return None
