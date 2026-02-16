import io
import logging
import sys
import traceback
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload
from google.oauth2 import service_account
import google.auth

# --- CONFIGURACIÓN DE RUTAS ---
# ID de la Unidad Compartida (Nivel raíz de la unidad)
ID_UNIDAD_COMPARTIDA = "0AEU0RHjR-mDOUk9PVA"

# ID de la carpeta "Tasaciones2" (Donde se colgarán las carpetas de los vendedores)
ID_CARPETA_RAIZ = "1jHfVRjC6I0qPV9ArDIkhoKCYP7Iepmt9"

# ID del fichero vendedores.txt (En la raíz de la unidad compartida)
ID_FICHERO_VENDEDORES = "0AEU0RHjR-mDOUk9PVA" 

SCOPES = ["https://www.googleapis.com/auth/drive"]

logger = logging.getLogger(__name__)

def _escape_drive_query_value(s: str) -> str:
    return str(s).replace("'", "\\'").strip()

def _get_drive_service(creds_dict=None):
    """
    Obtiene el servicio de Drive. 
    Compatible con Local (Service Account) y Cloud Run (ADC).
    """
    try:
        if creds_dict is None:
            # MODO CLOUD RUN (ADC)
            creds, _ = google.auth.default()
            creds = google.auth.credentials.with_scopes_if_required(creds, SCOPES)
        else:
            # MODO LOCAL / STREAMLIT (Service Account)
            pk = str(creds_dict.get("private_key", "")).strip().replace("\\n", "\n")
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
        print(f"❌ Error al crear servicio Drive: {e}", file=sys.stderr, flush=True)
        return None

# --- FUNCIONES PARA GESTIÓN DE VENDEDORES (vendedores.txt) ---

def leer_vendedores(creds_dict):
    """
    Lee el archivo vendedores.txt usando su ID fijo desde la Unidad Compartida.
    """
    try:
        service = _get_drive_service(creds_dict)
        if not service: return []

        request = service.files().get_media(fileId=ID_FICHERO_VENDEDORES)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        
        done = False
        while done is False:
            status, done = downloader.next_chunk()
        
        # Decodificar y limpiar
        contenido = fh.getvalue().decode('utf-8')
        nombres = [line.strip() for line in contenido.splitlines() if line.strip()]
        return sorted(list(set(nombres))) # Únicos y ordenados
    except Exception as e:
        print(f"⚠️ Aviso: No se pudo leer vendedores.txt o está vacío: {e}", file=sys.stderr)
        return []

def actualizar_vendedores(creds_dict, lista_nombres):
    """
    Sobrescribe el archivo vendedores.txt con la nueva lista.
    """
    try:
        service = _get_drive_service(creds_dict)
        if not service: return False

        # Preparar contenido: un nombre por línea, ordenado y sin duplicados
        nuevo_contenido = "\n".join(sorted(list(set(lista_nombres))))
        fh = io.BytesIO(nuevo_contenido.encode('utf-8'))
        media = MediaIoBaseUpload(fh, mimetype='text/plain', resumable=False)
        
        service.files().update(
            fileId=ID_FICHERO_VENDEDORES,
            media_body=media,
            supportsAllDrives=True
        ).execute()
        
        print(f"✅ Lista de vendedores actualizada en Drive.", flush=True)
        return True
    except Exception as e:
        print(f"❌ Error actualizando vendedores.txt: {e}", file=sys.stderr)
        return False

# --- FUNCIONES DE CARPETAS E INFORMES ---

def _get_or_create_folder(service, folder_name: str, parent_folder_id: str) -> str:
    """
    Busca o crea una carpeta dentro de parent_folder_id en la Unidad Compartida.
    """
    safe_name = _escape_drive_query_value(folder_name)

    query = (
        f"name = '{safe_name}' and "
        f"mimeType = 'application/vnd.google-apps.folder' and "
        f"'{parent_folder_id}' in parents and "
        f"trashed = false"
    )

    resp = service.files().list(
        q=query,
        corpora="drive",
        driveId=ID_UNIDAD_COMPARTIDA,
        includeItemsFromAllDrives=True,
        supportsAllDrives=True,
        fields="files(id, name)",
        pageSize=1
    ).execute()

    files = resp.get("files", [])
    if files:
        return files[0]["id"]

    folder_metadata = {
        "name": folder_name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_folder_id],
    }

    created = service.files().create(
        body=folder_metadata,
        supportsAllDrives=True,
        fields="id",
    ).execute()

    return created.get("id")

def subir_informe(creds_dict, nombre_archivo, contenido_html, folder_name="General"):
    """
    Sube el HTML a: Unidad Compartida -> Tasaciones2 -> Carpeta Vendedor.
    """
    try:
        service = _get_drive_service(creds_dict)
        if not service:
            return None

        # 1. Obtener/Crear la carpeta del vendedor dentro de "Tasaciones2"
        folder_id = _get_or_create_folder(service, folder_name, ID_CARPETA_RAIZ)

        # 2. Preparar el contenido binario
        if isinstance(contenido_html, str):
            fh = io.BytesIO(contenido_html.encode("utf-8"))
        else:
            fh = io.BytesIO(contenido_html)

        media = MediaIoBaseUpload(fh, mimetype="text/html", resumable=False)
        file_metadata = {
            "name": nombre_archivo,
            "parents": [folder_id]
        }

        # 3. Subida final
        created = service.files().create(
            body=file_metadata,
            media_body=media,
            supportsAllDrives=True,
            fields="id, webViewLink",
        ).execute()

        print(f"✅ Informe subido con éxito: {nombre_archivo} (ID: {created.get('id')})", flush=True)
        return created.get("id")

    except Exception as e:
        tb = traceback.format_exc()
        print("❌ Error en subida a Drive (repr):", repr(e), file=sys.stderr, flush=True)
        print("❌ Traceback completo:\n" + tb, file=sys.stderr, flush=True)
        return None
