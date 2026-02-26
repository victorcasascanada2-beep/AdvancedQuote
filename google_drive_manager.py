import io
import json
import sys
from typing import List, Optional, Dict, Any

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload
from google.oauth2 import service_account
import google.auth

# --- TU UNIDAD COMPARTIDA ---
ID_UNIDAD_COMPARTIDA = "0AEU0RHjR-mDOUk9PVA"  # driveId (Shared Drive)
ID_CARPETA_RAIZ_TASACIONES = "1jHfVRjC6I0qPV9ArDIkhoKCYP7Iepmt9"  # carpeta raíz donde cuelgan las carpetas vendedor

NOMBRE_FICHERO_VENDEDORES = "usuarios.txt"
NOMBRE_FICHERO_COEFS = "coeficientes_tasacion.json"  # <--- necesario para leer coeficientes

SCOPES = ["https://www.googleapis.com/auth/drive"]


def _get_drive_service(creds_dict=None):
    """
    - creds_dict=None: Cloud Run (ADC)
    - creds_dict!=None: local/Streamlit (service account en secrets)
    """
    try:
        if creds_dict is None:
            creds, _ = google.auth.default()
            creds = google.auth.credentials.with_scopes_if_required(creds, SCOPES)
        else:
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
        print(f"❌ Error creando servicio Drive: {e}", file=sys.stderr)
        return None


def _escape_drive_query_value(s: str) -> str:
    return (s or "").replace("'", r"\'")


def _find_file_id_in_shared_drive(service, filename: str) -> Optional[str]:
    """
    Busca filename dentro de la unidad compartida (driveId).
    Devuelve fileId o None.
    """
    try:
        fn = _escape_drive_query_value(filename)
        query = f"name = '{fn}' and trashed = false"

        resp = service.files().list(
            q=query,
            corpora="drive",
            driveId=ID_UNIDAD_COMPARTIDA,
            includeItemsFromAllDrives=True,
            supportsAllDrives=True,
            fields="files(id,name,mimeType,parents),nextPageToken",
            pageSize=50,
        ).execute()

        files = resp.get("files", [])
        if not files:
            return None

        # Si hay varios con el mismo nombre, nos quedamos con el primero
        return files[0]["id"]
    except Exception as e:
        print(f"⚠️ Error buscando {filename} en unidad compartida: {e}", file=sys.stderr)
        return None


# ------------------------------------------------------------
# LECTURA/ESCRITURA GENÉRICA (útil para coefs)
# ------------------------------------------------------------
def leer_texto_por_nombre(creds_dict=None, filename: str = "") -> str:
    service = _get_drive_service(creds_dict)
    if not service or not filename:
        return ""

    file_id = _find_file_id_in_shared_drive(service, filename)
    if not file_id:
        return ""

    try:
        request = service.files().get_media(fileId=file_id, supportsAllDrives=True)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()

        return fh.getvalue().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"⚠️ Error leyendo {filename}: {e}", file=sys.stderr)
        return ""


def escribir_texto_por_nombre(creds_dict, filename: str, contenido: str, mimetype: str = "text/plain") -> bool:
    """
    Sobrescribe un archivo existente (por nombre) dentro de la Shared Drive.
    Si no existe, devuelve False (evita duplicados por error).
    """
    service = _get_drive_service(creds_dict)
    if not service or not filename:
        return False

    file_id = _find_file_id_in_shared_drive(service, filename)
    if not file_id:
        print(f"⚠️ {filename} no encontrado; no se puede sobrescribir.", file=sys.stderr)
        return False

    try:
        fh = io.BytesIO((contenido or "").encode("utf-8"))
        media = MediaIoBaseUpload(fh, mimetype=mimetype, resumable=False)

        service.files().update(
            fileId=file_id,
            media_body=media,
            supportsAllDrives=True,
        ).execute()
        return True
    except Exception as e:
        print(f"❌ Error escribiendo {filename}: {e}", file=sys.stderr)
        return False


# ------------------------------------------------------------
# VENDEDORES
# ------------------------------------------------------------

def leer_vendedores(creds_dict) -> List[str]:
    """Carga la lista de usuarios desde el archivo configurado."""
    texto = leer_texto_por_nombre(creds_dict, NOMBRE_FICHERO_USUARIOS)
    if not texto:
        print(f"⚠️ Usando lista de respaldo para {NOMBRE_FICHERO_USUARIOS}")
        return ["Vendedor 1", "Vendedor 2", "Administrador"]
    return sorted({n.strip() for n in texto.splitlines() if n.strip()})


def actualizar_vendedores(creds_dict, lista_nombres: List[str]) -> bool:
    contenido = "\n".join(sorted({n.strip() for n in (lista_nombres or []) if n and n.strip()}))
    return escribir_texto_por_nombre(creds_dict, NOMBRE_FICHERO_VENDEDORES, contenido, mimetype="text/plain")


# ------------------------------------------------------------
# COEFICIENTES
# ------------------------------------------------------------
def leer_coeficientes(creds_dict=None) -> Dict[str, Any]:
    """
    Lee coeficientes_tasacion.json desde la Shared Drive.
    Debe contener un JSON tipo:
      { "pala_eur_por_cv": 41.6, "neumaticos": {...}, ... }
    """
    texto = leer_texto_por_nombre(creds_dict, NOMBRE_FICHERO_COEFS)
    if not texto:
        return {}
    try:
        data = json.loads(texto)
        return data if isinstance(data, dict) else {}
    except Exception as e:
        print(f"⚠️ JSON inválido en {NOMBRE_FICHERO_COEFS}: {e}", file=sys.stderr)
        return {}


# ------------------------------------------------------------
# SUBIDA INFORME (HTML) A CARPETA POR VENDEDOR
# ------------------------------------------------------------
def _get_or_create_folder(service, folder_name: str, parent_id: str) -> Optional[str]:
    folder_name_q = _escape_drive_query_value(folder_name)

    query = (
        f"name = '{folder_name_q}' and "
        f"mimeType = 'application/vnd.google-apps.folder' and "
        f"'{parent_id}' in parents and trashed = false"
    )

    resp = service.files().list(
        q=query,
        corpora="drive",
        driveId=ID_UNIDAD_COMPARTIDA,
        includeItemsFromAllDrives=True,
        supportsAllDrives=True,
        fields="files(id,name)",
    ).execute()

    files = resp.get("files", [])
    if files:
        return files[0]["id"]

    meta = {"name": folder_name, "mimeType": "application/vnd.google-apps.folder", "parents": [parent_id]}
    created = service.files().create(body=meta, supportsAllDrives=True, fields="id").execute()
    return created.get("id")


def subir_informe(creds_dict, nombre_archivo: str, contenido_html, folder_name: str = "General") -> Optional[str]:
    try:
        service = _get_drive_service(creds_dict)
        if not service:
            return None

        folder_id = _get_or_create_folder(service, folder_name, ID_CARPETA_RAIZ_TASACIONES)
        if not folder_id:
            return None

        data = contenido_html.encode("utf-8") if isinstance(contenido_html, str) else contenido_html
        fh = io.BytesIO(data)
        media = MediaIoBaseUpload(fh, mimetype="text/html", resumable=False)

        meta = {"name": nombre_archivo, "parents": [folder_id]}
        created = service.files().create(
            body=meta,
            media_body=media,
            supportsAllDrives=True,
            fields="id",
        ).execute()

        return created.get("id")
    except Exception as e:
        print(f"❌ Error subiendo informe: {e}", file=sys.stderr)
        return None
