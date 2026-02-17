import io
import sys
from typing import List, Optional

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload
from google.oauth2 import service_account
import google.auth

# --- TU UNIDAD COMPARTIDA ---
ID_UNIDAD_COMPARTIDA = "0AEU0RHjR-mDOUk9PVA"  # driveId (Shared Drive)
ID_CARPETA_RAIZ_TASACIONES = "1jHfVRjC6I0qPV9ArDIkhoKCYP7Iepmt9"  # carpeta raíz donde cuelgan las carpetas vendedor
NOMBRE_FICHERO_VENDEDORES = "vendedores.txt"

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


def leer_vendedores(creds_dict=None) -> List[str]:
    service = _get_drive_service(creds_dict)
    if not service:
        return []

    file_id = _find_file_id_in_shared_drive(service, NOMBRE_FICHERO_VENDEDORES)
    if not file_id:
        print("⚠️ vendedores.txt no encontrado en la unidad compartida.", file=sys.stderr)
        return []

    try:
        request = service.files().get_media(fileId=file_id, supportsAllDrives=True)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()

        texto = fh.getvalue().decode("utf-8", errors="replace")
        vendedores = sorted({n.strip() for n in texto.splitlines() if n.strip()})
        return vendedores
    except Exception as e:
        print(f"⚠️ Error leyendo vendedores.txt: {e}", file=sys.stderr)
        return []


def actualizar_vendedores(creds_dict, lista_nombres: List[str]) -> bool:
    service = _get_drive_service(creds_dict)
    if not service:
        return False

    file_id = _find_file_id_in_shared_drive(service, NOMBRE_FICHERO_VENDEDORES)
    if not file_id:
        print("⚠️ vendedores.txt no encontrado; no se puede actualizar.", file=sys.stderr)
        return False

    try:
        contenido = "\n".join(sorted({n.strip() for n in lista_nombres if n and n.strip()}))
        fh = io.BytesIO(contenido.encode("utf-8"))
        media = MediaIoBaseUpload(fh, mimetype="text/plain", resumable=False)

        service.files().update(
            fileId=file_id,
            media_body=media,
            supportsAllDrives=True,
        ).execute()
        return True
    except Exception as e:
        print(f"❌ Error actualizando vendedores.txt: {e}", file=sys.stderr)
        return False


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
