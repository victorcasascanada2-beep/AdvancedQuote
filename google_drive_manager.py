import io
import sys
import json
from typing import List, Any, Optional
from datetime import datetime

import google.auth
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload
from google.oauth2 import service_account

# --- CONFIGURACIÓN ---
ID_UNIDAD_COMPARTIDA = "0AEU0RHjR-mDOUk9PVA"
ID_CARPETA_RAIZ = "1jHfVRjC6I0qPV9ArDIkhoKCYP7Iepmt9"
ID_EXCEL_HISTORIAL = "1fzedPLwRX4T0sG860ITmcYHp3nHu3GGkxW--y8Qs4v4"
NOMBRE_FICHERO_USUARIOS = "usuarios.txt"  # Centralizamos el nombre aquí


def _get_credentials(creds_dict=None):
    """Gestión de credenciales para Local (Secrets) y Cloud Run."""
    scopes = ["https://www.googleapis.com/auth/drive", "https://www.googleapis.com/auth/spreadsheets"]
    try:
        if creds_dict is None:
            creds, _ = google.auth.default()
            return google.auth.credentials.with_scopes_if_required(creds, scopes)

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
        return service_account.Credentials.from_service_account_info(auth_info, scopes=scopes)
    except Exception as e:
        print(f"❌ Error en credenciales: {e}", file=sys.stderr)
        return None


def _get_drive_service(creds_dict):
    creds = _get_credentials(creds_dict)
    return build("drive", "v3", credentials=creds, static_discovery=False)


def _get_sheets_service(creds_dict):
    creds = _get_credentials(creds_dict)
    return build("sheets", "v4", credentials=creds, static_discovery=False)


def _escape_query(s: str) -> str:
    return (s or "").replace("'", r"\'")


# --- FUNCIONES DE LECTURA ---

def leer_texto_por_nombre(creds_dict, filename: str) -> str:
    """Busca y descarga el contenido de un archivo de texto/json."""
    try:
        service = _get_drive_service(creds_dict)
        fn = _escape_query(filename)
        query = f"name = '{fn}' and trashed = false"
        resp = service.files().list(
            q=query, corpora="drive", driveId=ID_UNIDAD_COMPARTIDA,
            includeItemsFromAllDrives=True, supportsAllDrives=True, fields="files(id)"
        ).execute()

        files = resp.get("files", [])
        if not files: return ""

        request = service.files().get_media(fileId=files[0]["id"], supportsAllDrives=True)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        return fh.getvalue().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"⚠️ Error leyendo {filename}: {e}")
        return ""


def leer_vendedores(creds_dict) -> List[str]:
    """Carga la lista de usuarios desde el archivo configurado."""
    texto = leer_texto_por_nombre(creds_dict, NOMBRE_FICHERO_USUARIOS)
    if not texto:
        print(f"⚠️ Usando lista de respaldo para {NOMBRE_FICHERO_USUARIOS}")
        return ["Vendedor 1", "Vendedor 2", "Administrador"]
    return sorted({n.strip() for n in texto.splitlines() if n.strip()})


def leer_coeficientes(creds_dict) -> dict:
    """Carga los coeficientes de tasación."""
    texto = leer_texto_por_nombre(creds_dict, "coeficientes_tasacion.json")
    try:
        return json.loads(texto) if texto else {}
    except:
        return {}


# --- FUNCIONES DE ESCRITURA ---

def escribir_texto_por_nombre(creds_dict, filename: str, contenido: str) -> bool:
    """Sobrescribe un archivo existente en Drive."""
    try:
        service = _get_drive_service(creds_dict)
        fn = _escape_query(filename)
        query = f"name = '{fn}' and trashed = false"
        resp = service.files().list(
            q=query, corpora="drive", driveId=ID_UNIDAD_COMPARTIDA,
            includeItemsFromAllDrives=True, supportsAllDrives=True, fields="files(id)"
        ).execute()

        files = resp.get("files", [])
        if not files: return False

        media = MediaIoBaseUpload(io.BytesIO(contenido.encode("utf-8")), mimetype="text/plain")
        service.files().update(fileId=files[0]["id"], media_body=media, supportsAllDrives=True).execute()
        return True
    except Exception as e:
        print(f"❌ Error escribiendo {filename}: {e}")
        return False


def actualizar_vendedores(creds_dict, lista_nombres: List[str]) -> bool:
    """Actualiza el archivo de usuarios."""
    contenido = "\n".join(sorted({n.strip() for n in lista_nombres if n.strip()}))
    return escribir_texto_por_nombre(creds_dict, NOMBRE_FICHERO_USUARIOS, contenido)


def registrar_en_historial_excel(creds_dict, fila: List[Any]) -> bool:
    """Guarda la fila en Google Sheets."""
    try:
        service = _get_sheets_service(creds_dict)
        body = {'values': [fila]}
        service.spreadsheets().values().append(
            spreadsheetId=ID_EXCEL_HISTORIAL,
            range="Hoja 1!A:J",
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body=body
        ).execute()
        print("✅ Registro en Excel completado.")
        return True
    except Exception as e:
        print(f"❌ Error Excel: {e}")
        return False


# --- GESTIÓN DE INFORMES ---

def _get_or_create_folder(service, folder_name: str, parent_id: str) -> Optional[str]:
    name_q = _escape_query(folder_name)
    query = f"name = '{name_q}' and mimeType = 'application/vnd.google-apps.folder' and '{parent_id}' in parents and trashed = false"
    resp = service.files().list(
        q=query, corpora="drive", driveId=ID_UNIDAD_COMPARTIDA,
        includeItemsFromAllDrives=True, supportsAllDrives=True, fields="files(id)"
    ).execute()
    files = resp.get("files", [])
    if files: return files[0]["id"]

    meta = {"name": folder_name, "mimeType": "application/vnd.google-apps.folder", "parents": [parent_id]}
    return service.files().create(body=meta, supportsAllDrives=True, fields="id").execute().get("id")


def subir_informe(creds_dict, nombre_archivo: str, contenido_html, folder_name: str = "General") -> Optional[str]:
    try:
        service = _get_drive_service(creds_dict)
        folder_id = _get_or_create_folder(service, folder_name, ID_CARPETA_RAIZ)
        data = contenido_html.encode("utf-8") if isinstance(contenido_html, str) else contenido_html
        media = MediaIoBaseUpload(io.BytesIO(data), mimetype="text/html")
        meta = {"name": nombre_archivo, "parents": [folder_id]}
        return service.files().create(body=meta, media_body=media, supportsAllDrives=True).execute().get("id")
    except Exception as e:
        print(f"❌ Error subiendo informe: {e}")
        return None
