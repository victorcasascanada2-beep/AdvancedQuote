import io
import sys
import traceback
import logging
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload
from google.oauth2 import service_account

# --- CONFIGURACIÓN DE IDs ---
# ID de la Unidad Compartida (DriveId)
ID_UNIDAD_COMPARTIDA = "0AEU0RHjR-mDOUk9PVA"

# ID de la carpeta "Tasaciones2" (Donde se crean las carpetas de vendedores)
ID_CARPETA_RAIZ_TASACIONES = "1jHfVRjC6I0qPV9ArDIkhoKCYP7Iepmt9"

# ID del fichero vendedores.txt (En la raíz de la unidad compartida)
ID_FICHERO_VENDEDORES = "0AEU0RHjR-mDOUk9PVA"

SCOPES = ["https://www.googleapis.com/auth/drive"]
logger = logging.getLogger(__name__)

def _get_drive_service(creds_dict):
    """
    Crea el cliente de la API de Drive a partir del diccionario de secretos.
    """
    if not creds_dict:
        return None
    try:
        # Limpieza de la clave privada (arreglo de secrets)
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
        print(f"❌ Error al crear servicio Drive: {e}", file=sys.stderr)
        return None

def _escape_drive_query_value(s: str) -> str:
    return str(s).replace("'", "\\'").strip()

# --- GESTIÓN DE VENDEDORES (vendedores.txt) ---

def leer_vendedores(creds_dict):
    """Lee el archivo vendedores.txt y devuelve una lista de nombres."""
    service = _get_drive_service(creds_dict)
    if not service:
        return []
    try:
        request = service.files().get_media(fileId=ID_FICHERO_VENDEDORES)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        
        done = False
        while not done:
            status, done = downloader.next_chunk()
        
        contenido = fh.getvalue().decode('utf-8')
        nombres = [line.strip() for line in contenido.splitlines() if line.strip()]
        return sorted(list(set(nombres)))
    except Exception as e:
        print(f"⚠️ No se pudo leer vendedores.txt: {e}")
        return []

def actualizar_vendedores(creds_dict, lista_nombres):
    """Sobrescribe vendedores.txt con la lista actualizada."""
    service = _get_drive_service(creds_dict)
    if not service:
        return False
    try:
        # Asegurar nombres únicos y ordenados
        texto_final = "\n".join(sorted(list(set(lista_nombres))))
        fh = io.BytesIO(texto_final.encode('utf-8'))
        media = MediaIoBaseUpload(fh, mimetype='text/plain', resumable=False)
        
        service.files().update(
            fileId=ID_FICHERO_VENDEDORES,
            media_body=media,
            supportsAllDrives=True
        ).execute()
        return True
    except Exception as e:
        print(f"❌ Error actualizando vendedores.txt: {e}")
        return False

# --- GESTIÓN DE INFORMES Y CARPETAS ---

def _get_or_create_folder(service, folder_name: str, parent_folder_id: str) -> str:
    """Busca o crea una carpeta de vendedor dentro de Tasaciones2."""
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

    # Crear si no existe
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
    """Sube el informe final a la carpeta del vendedor en la Unidad Compartida."""
    try:
        service = _get_drive_service(creds_dict)
        if not service:
            return None

        # 1. Obtener carpeta del vendedor
        folder_id = _get_or_create_folder(service, folder_name, ID_CARPETA_RAIZ_TASACIONES)

        # 2. Preparar archivo
        if isinstance(contenido_html, str):
            fh = io.BytesIO(contenido_html.encode("utf-8"))
        else:
            fh = io.BytesIO(contenido_html)

        media = MediaIoBaseUpload(fh, mimetype="text/html", resumable=False)
        file_metadata = {
            "name": nombre_archivo,
            "parents": [folder_id]
        }

        # 3. Subir
        created = service.files().create(
            body=file_metadata,
            media_body=media,
            supportsAllDrives=True,
            fields="id, webViewLink",
        ).execute()

        print(f"✅ Informe guardado: {nombre_archivo} (ID: {created.get('id')})")
        return created.get("id")

    except Exception as e:
        print(f"❌ Error en subir_informe: {e}")
        return None
