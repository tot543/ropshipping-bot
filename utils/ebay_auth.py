"""
utils/ebay_auth.py — Módulo de Autorización OAuth
==============================================================================
Maneja la lógica de obtención y auto-renovación de tokens OAuth de eBay.
Lee credenciales desde secrets.toml, mantiene la vida del token en session_state,
y solicita un nuevo access_token mediante el refresh_token cuando expira o 
cuando recibe un error 401.
"""

import time
import base64
import requests
import streamlit as st
import urllib.parse


def get_auth_url() -> str:
    """
    Genera la URL de autorización de eBay (User Consent URL) usando las
    credenciales de st.secrets["ebay"].
    """
    try:
        ebay_keys = st.secrets["ebay"]
        app_id = ebay_keys.get("app_id", "")
        runame = ebay_keys.get("runame", "")
    except KeyError:
        return ""
        
    scopes = (
        "https://api.ebay.com/oauth/api_scope "
        "https://api.ebay.com/oauth/api_scope/sell.inventory "
        "https://api.ebay.com/oauth/api_scope/sell.fulfillment "
        "https://api.ebay.com/oauth/api_scope/sell.account "
        "https://api.ebay.com/oauth/api_scope/sell.marketing"
    )
    
    url = "https://auth.ebay.com/oauth2/authorize"
    params = {
        "client_id": app_id,
        "response_type": "code",
        "redirect_uri": runame,
        "scope": scopes
    }
    
    return f"{url}?{urllib.parse.urlencode(params)}"


def refresh_access_token(tienda_id: str):
    """
    Fuerza la renovación del access_token utilizando el refresh_token 
    y el cert_id al endpoint de eBay /identity/v1/oauth2/token
    """
    try:
        ebay_keys = st.secrets["ebay"]
        tienda_config = st.secrets["tiendas"][tienda_id]
    except KeyError as e:
        st.error(f"Falta configuración en secrets.toml: {e}")
        return False
    
    app_id = ebay_keys.get("app_id", "")
    cert_id = ebay_keys.get("cert_id", "")
    refresh_token = tienda_config.get("refresh_token", "")
    
    if not refresh_token:
        # No intentamos renovar si el refresh_token está vacío
        return False
    
    # eBay requiere las credenciales del cliente en formato Base64 (app_id:cert_id)
    auth_str = f"{app_id}:{cert_id}"
    b64_auth = base64.b64encode(auth_str.encode("utf-8")).decode("utf-8")
    
    url = "https://api.ebay.com/identity/v1/oauth2/token"
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Authorization": f"Basic {b64_auth}"
    }
    
    # Scopes solicitados (Deben coincidir o ser un subconjunto de los originales)
    scopes = (
        "https://api.ebay.com/oauth/api_scope "
        "https://api.ebay.com/oauth/api_scope/sell.inventory "
        "https://api.ebay.com/oauth/api_scope/sell.fulfillment "
        "https://api.ebay.com/oauth/api_scope/sell.account "
        "https://api.ebay.com/oauth/api_scope/sell.marketing"
    )
    
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "scope": scopes
    }
    
    try:
        respuesta = requests.post(url, headers=headers, data=data, timeout=15)
        respuesta.raise_for_status()
        
        token_data = respuesta.json()
        nuevo_token = token_data.get("access_token", "")
        expires_in = token_data.get("expires_in", 7200)  # eBay suele dar 2h
        
        # Guardar en session_state con margen de seguridad (60 seg antes de expiración real)
        st.session_state[f"token_{tienda_id}"] = nuevo_token
        st.session_state[f"token_expires_{tienda_id}"] = time.time() + expires_in - 60
        
        return nuevo_token
        
    except requests.exceptions.RequestException as e:
        err_msg = f"Error conectando con API Identity de eBay: {str(e)}"
        if hasattr(e, 'response') and e.response is not None:
            err_msg += f". Respuesta: {e.response.text}"
        print(err_msg)
        st.error("Error renovando token o credenciales inválidas. Por favor, vuelve a autorizar.")
        return False


def get_valid_token(tienda_id: str):
    """
    Obtiene un token de acceso válido para la tienda.
    Prioriza Session State, si caducó o no existe usa refresh_access_token().
    """
    if "tiendas" not in st.secrets or tienda_id not in st.secrets["tiendas"]:
        st.error(f"La tienda {tienda_id} no está configurada en secrets.toml")
        return False

    tienda_config = st.secrets["tiendas"][tienda_id]
    oauth_token = tienda_config.get("oauth_token", "")
    refresh_token = tienda_config.get("refresh_token", "")
    
    if not oauth_token and not refresh_token:
        return False

    token_key = f"token_{tienda_id}"
    expires_key = f"token_expires_{tienda_id}"
    
    # 1. Si existe en sesión y NO ha expirado, úsalo (Caché en BD en memoria)
    if token_key in st.session_state and expires_key in st.session_state:
        if time.time() < st.session_state[expires_key]:
            return st.session_state[token_key]
            
    # 2. Si llegamos aquí: no está en sesión o ya expiró -> Llamamos a la API real.
    return refresh_access_token(tienda_id)
