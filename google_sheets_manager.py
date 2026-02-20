import os
import sys
from typing import Optional, List, Any, Dict
import datetime

from googleapiclient.discovery import build
from google.oauth2 import service_account
import google.auth

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def _get_sheets_service(creds_dict: Optional[Dict[str, Any]] = None):
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

        return build("sheets", "v4", credentials=creds, static_discovery=False)
    except Exception as e:
        print(f"❌ Error creando servicio Sheets: {e}", file=sys.stderr)
        return None


def _now_es() -> str:
    # Si quieres timezone España “perfecto”, lo afinamos luego con zoneinfo.
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def append_row(
    creds_dict: Optional[Dict[str, Any]],
    spreadsheet_id: str,
    row: List[Any],
    sheet_name: str = "Hoja 1",
) -> bool:
    service = _get_sheets_service(creds_dict)
    if not service or not spreadsheet_id:
        return False

    try:
        service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range=f"{sheet_name}!A:Z",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": [row]},
        ).execute()
        return True
    except Exception as e:
        print(f"❌ append_row error: {e}", file=sys.stderr)
        return False


def build_row_for_header(
    vendedor: str,
    marca: str,
    modelo: str,
    cv: str,
    precio_mercado: Optional[float],
    precio_compra: Optional[float],
    precio_venta: Optional[float],
) -> List[Any]:
    """
    Orden EXACTO según tu cabecera:
    Vendedor | Fecha | Marca | Modelo | CV | PrecioMercado | PrecioCompra | PrecioVenta
    """
    def _to_int(x: Optional[float]) -> str:
        if x is None:
            return ""
        try:
            return str(int(round(float(x))))
        except Exception:
            return ""

    return [
        vendedor or "",
        _now_es(),
        marca or "",
        modelo or "",
        str(cv or ""),
        _to_int(precio_mercado),
        _to_int(precio_compra),
        _to_int(precio_venta),
    ]
