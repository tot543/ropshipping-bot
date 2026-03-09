import base64
import requests
import streamlit as st
import json
import urllib.parse

def generar_tokens():
    print("=" * 60)
    print("🔑 Generador de Tokens de eBay (URL Completa -> Tokens)")
    print("=" * 60)

    # 1. Leer app_id, cert_id y runame de secrets.toml
    try:
        ebay_keys = st.secrets["ebay"]
        app_id = ebay_keys["app_id"]
        cert_id = ebay_keys["cert_id"]
        redirect_uri = ebay_keys["runame"]
        
        if app_id == "MI_APP_ID" or cert_id == "MI_CERT_ID":
            print("❌ ERROR: Aún tienes los placeholders. Configura tus verdaderos app_id y cert_id en .streamlit/secrets.toml")
            return
    except KeyError as e:
        print(f"❌ ERROR: Faltan llaves en secrets.toml: {e}")
        return

    # 2. Pedir por consola la URL COMPLETA
    print("\n👉 Pega aquí la URL COMPLETA que te devolvió eBay en el navegador:")
    print("(Ejemplo: https://auth2.ebay.com/oauth2/ThirdPartyAuthSuccessFailure?isAuthSuccessful=true&code=v%5E1.1%23...&expires_in=299)")
    url_completa = input("> ").strip()

    if not url_completa:
        print("❌ No ingresaste ninguna URL. Cancelando.")
        return

    # 3. Extraer y decodificar el Authorization Code de forma segura
    try:
        parsed_url = urllib.parse.urlparse(url_completa)
        query_params = urllib.parse.parse_qs(parsed_url.query)
        
        if 'code' not in query_params:
            print("❌ ERROR: La URL proporcionada no contiene el parámetro 'code'. Asegúrate de copiar la URL correcta después de autorizar.")
            return
            
        # parse_qs devuelve una lista para cada clave, tomamos el primer elemento (decodificado automáticamente)
        auth_code = query_params['code'][0]
        print(f"✅ Código extraído y decodificado exitosamente.")
        
    except Exception as e:
        print(f"❌ ERROR al procesar la URL: {str(e)}")
        return

    # 4. Codificar en Base64 la cadena app_id:cert_id
    auth_string = f"{app_id}:{cert_id}"
    base64_str = base64.b64encode(auth_string.encode('utf-8')).decode('utf-8')

    # 5. Preparar Headers y URL para el POST
    url = "https://api.ebay.com/identity/v1/oauth2/token"
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Authorization": f"Basic {base64_str}"
    }

    # 6. Preparar el Payload
    payload = {
        "grant_type": "authorization_code",
        "code": auth_code,
        "redirect_uri": redirect_uri
    }

    print("\n⏳ Intercambiando código con eBay...\n")

    # Hacer el POST request
    try:
        response = requests.post(url, headers=headers, data=payload)
        response.raise_for_status()
        
        datos = response.json()
        
        access_token = datos.get("access_token", "")
        refresh_token = datos.get("refresh_token", "")
        
        # 7. Imprimir de forma muy clara el access_token y el refresh_token
        print("✅ ¡EXITO! Aquí están tus tokens reales:\n")
        print("-" * 60)
        print("OAUTH TOKEN (Access Token - Dura 2 horas):")
        print(f"{access_token}")
        print("-" * 60)
        print("REFRESH TOKEN (Dura meses - Copia esto a tu secrets.toml):")
        print(f"{refresh_token}")
        print("-" * 60)
        
        print("\n📌 Instrucciones:")
        print("Copia los dos tokens generados arriba y pégalos en tu archivo '.streamlit/secrets.toml'")
        print("dentro de la sección de tu tienda [tiendas.tienda_carlos_principal] "
              "(o la tienda que estés usando).")
              
    except requests.exceptions.HTTPError as e:
        print(f"❌ ERROR HTTP: {e.response.status_code}")
        try:
            print(json.dumps(e.response.json(), indent=2))
        except:
            print(e.response.text)
        print("\nSi recibes un error 'invalid_grant', tu Authorization Code ya expiró (dura solo ~5 mins) o ya fue usado. "
              "Debes autorizar la app de nuevo en el navegador y obtener una URL nueva.")
    except Exception as e:
        print(f"❌ Error al conectar: {str(e)}")


if __name__ == "__main__":
    generar_tokens()
