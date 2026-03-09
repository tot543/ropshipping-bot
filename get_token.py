"""
get_token.py — Utilidad para intercambiar el Authorization Code por Tokens Reales
================================================================================
Ejecuta este archivo individualmente en la terminal:
    python get_token.py
"""

import base64
import requests
import streamlit as st
import json

def obtener_tokens_definitivos():
    print("=" * 60)
    print("🚀 Utilidad de Intercambio de OAuth Code - eBay API")
    print("=" * 60)
    
    # 1. Leer credenciales desde secrets.toml usando st.secrets
    try:
        ebay_keys = st.secrets["ebay"]
        app_id = ebay_keys["app_id"]
        cert_id = ebay_keys["cert_id"]
        redirect_uri = ebay_keys["runame"]
        
        if app_id == "MI_APP_ID" or cert_id == "MI_CERT_ID":
            print("❌ ERROR: Primero debes colocar tu 'app_id' y 'cert_id' reales en '.streamlit/secrets.toml'.")
            return
            
    except KeyError as e:
        print(f"❌ ERROR: Falla al leer credentials desde secrets.toml. Llave faltante: {e}")
        return

    # 2. Pedir al usuario el código de autorización
    print("\n👉 Ingresa el 'Authorization Code' que obtuviste de la URL al aceptar los permisos:")
    print("(Suele ser una cadena muy larga que empieza con 'v^1.1#iQ...')")
    auth_code = input("Código: ").strip()
    
    if not auth_code:
        print("❌ Operación cancelada, no introdujiste ningún código.")
        return

    # 3. Preparar los Headers (Base64 Encoding)
    auth_str = f"{app_id}:{cert_id}"
    b64_auth = base64.b64encode(auth_str.encode("utf-8")).decode("utf-8")
    
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Authorization": f"Basic {b64_auth}"
    }

    # 4. Preparar el Payload
    payload = {
        "grant_type": "authorization_code",
        "code": auth_code,
        "redirect_uri": redirect_uri
    }

    url = "https://api.ebay.com/identity/v1/oauth2/token"

    print("\n⏳ Enviando petición a eBay...")
    
    # 5. Hacer el POST Request
    try:
        respuesta = requests.post(url, headers=headers, data=payload)
        respuesta.raise_for_status()  # Lanza excepción si hay error HTTP
        
        datos = respuesta.json()
        
        print("\n" + "=" * 60)
        print("✅ ¡ÉXITO! Intercambio completado correctamente.")
        print("=" * 60)
        print("\nCopia y pega estos valores en tu '.streamlit/secrets.toml' bajo la tienda deseada:\n")
        
        print(f"oauth_token   = \"{datos.get('access_token', '')}\"\n")
        print(f"refresh_token = \"{datos.get('refresh_token', '')}\"\n")
        
        print("=" * 60)
        print(f"Vida del Access Token: {datos.get('expires_in', 0)} segundos.")
        print(f"Vida del Refresh Token: {datos.get('refresh_token_expires_in', 0)} segundos.")
        print("El flujo de auto-renovación de app.py y utils/ebay_auth.py se encargará del resto.")
        
    except requests.exceptions.HTTPError as e:
        print(f"\n❌ ERROR HTTP {e.response.status_code}")
        try:
            print(json.dumps(e.response.json(), indent=2))
        except:
            print(e.response.text)
        print("\nAsegúrate de que el código no haya expirado (dura aprox 5 minutos) y que no le falten caracteres.")
    except Exception as e:
        print(f"\n❌ Error inesperado: {str(e)}")


if __name__ == "__main__":
    obtener_tokens_definitivos()
