import streamlit as st
import requests
import re
import os
import sys
import uuid
import json
from datetime import datetime, timezone
from urllib.parse import quote

# El root ya debe estar en el path por app.py, pero por seguridad:
if os.getcwd() not in sys.path:
    sys.path.insert(0, os.getcwd())

from utils.ebay_auth import get_valid_token, refresh_access_token, get_app_token

st.set_page_config(page_title="Publicador Automático | eBay Hub", page_icon="🚀", layout="wide")
EBAY_INVENTORY_BASE_URL  = "https://api.ebay.com/sell/inventory/v1"
EBAY_ACCOUNT_BASE_URL    = "https://api.ebay.com/sell/account/v1"
EBAY_MARKETING_BASE_URL  = "https://api.ebay.com/sell/marketing/v1"
def interpretar_error_aspectos_ia(error_json: str, titulo: str = "", bullets: list = []) -> dict:
    """
    Analiza el JSON de error de eBay usando Groq de forma directa.
    Extrae los nombres faltantes y SUGIERE un valor real basado en el título del producto.
    Retorna un diccionario: {"NombreAspecto": ["ValorSugerido"]}
    """
    try:
        api_key = st.secrets["groq"]["api_key"]
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        
        sys_prompt = (
            "Eres un analista técnico de eBay. Tu misión es corregir errores de 'Item Specifics'.\n"
            "INSTRUCCIONES:\n"
            "1) Lee el JSON de error para identificar los aspectos que faltan o están mal.\n"
            "2) Lee el Título y Características del producto para ADIVINAR el valor real de ese aspecto.\n"
            "3) Si eBay dice 'should contain only one', asegúrate de devolver SOLO un valor en la lista.\n"
            "4) Si no puedes adivinar el valor, usa ['N/A'] o ['Other'].\n"
            "\nEjemplo de entrada:\n"
            "Error: {'message': 'Material should contain only one'}\n"
            "Producto: 'Camiseta de Algodón Azul'\n"
            "Salida esperada: {'Material': ['Cotton']}\n"
            "\nDevuelve SOLO un diccionario JSON válido de Python, sin markdown."
        )
        
        user_prompt = (
            f"PRODUCTO: {titulo}\n"
            f"CARACTERISTICAS: {', '.join(bullets)}\n"
            f"ERROR EBAY: {error_json}"
        )
        
        payload = {
            "model": "openai/gpt-oss-120b",
            "messages": [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user_prompt}
            ]
        }
        
        resp = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload, timeout=20)
        if resp.status_code == 200:
            texto = resp.json()['choices'][0]['message']['content']
            texto = texto.replace('```python', '').replace('```json', '').replace('```', '').strip()
            import ast
            res = ast.literal_eval(texto)
            if isinstance(res, dict):
                return res
    except Exception as e:
        print(f"DEBUG IA LOCAL | Error: {e}")
    return {}
def obtener_sugerencias_ebay_taxonomy(titulo: str, tienda_id: str, marketplace_id: str = "EBAY_US") -> str:
    """
    Consulta la Taxonomy API de eBay para obtener sugerencias oficiales de categorías.
    Retorna una cadena formateada con las sugerencias para pasarle a la IA.
    """
    try:
        app_token = get_app_token()
        headers = construir_headers_ebay(app_token, marketplace_id)
        
        # 1. Obtener el ID del árbol de categorías para el marketplace
        url_tree = f"https://api.ebay.com/commerce/taxonomy/v1/get_default_category_tree_id?marketplace_id={marketplace_id}"
        resp_tree = requests.get(url_tree, headers=headers, timeout=15)
        if resp_tree.status_code != 200:
            return ""
        
        tree_id = resp_tree.json().get("categoryTreeId")
        if not tree_id:
            return ""
        # 2. Obtener sugerencias basadas en el título
        url_sug = f"https://api.ebay.com/commerce/taxonomy/v1/category_tree/{tree_id}/get_category_suggestions?q={quote(titulo)}"
        resp_sug = requests.get(url_sug, headers=headers, timeout=15)
        
        if resp_sug.status_code == 200:
            suggestions = resp_sug.json().get("categorySuggestions", [])
            output = []
            for s in suggestions[:5]:
                cat = s.get("category", {})
                output.append(f"ID: {cat.get('categoryId')} | Nombre: {cat.get('categoryName')}")
            return "\n".join(output)
    except Exception as e:
        print(f"DEBUG TAXONOMY | Error: {e}")
    return ""
def detectar_categoria_por_keywords(titulo: str, bullets: list = []) -> str:
    """
    Detección rápida de categoría por palabras clave del producto.
    Evita depender de la Taxonomy API para productos comunes.
    Retorna category_id como string, o "" si no detecta nada.
    """
    texto = (titulo + " " + " ".join(bullets[:3])).lower()
    
    MAPA_CATEGORIAS = [
        # ── eBay Motors Parts ──
        (["mirror assembly", "side mirror", "espejo lateral", "retrovisor", "espejo del lado",
          "passenger mirror", "driver mirror", "mirror replacement"], "262161"),
        (["headlight", "head light", "faro delantero", "headlamp"], "262241"),
        (["tail light", "taillight", "faro trasero", "rear light"], "262244"),
        (["bumper", "parachoque", "parachoques", "front bumper", "rear bumper"], "262200"),
        (["brake pad", "brake shoe", "freno", "pastilla de freno"], "33559"),
        (["rotor", "brake rotor", "disco de freno"], "33563"),
        (["hood", "capó", "capo"], "33640"),
        (["fender", "guardabarros", "guardafango"], "33643"),
        (["grille", "parrilla delantera", "front grille"], "33649"),
        (["door handle", "manija", "manilla de puerta"], "33642"),
        (["window regulator", "regulador de ventana"], "42612"),
        (["strut", "shock absorber", "amortiguador"], "33596"),
        (["control arm", "brazo de control"], "38635"),
        (["alternator", "alternador", "starter", "arrancador"], "33590"),
        (["wiper blade", "limpiaparabrisas"], "33558"),
        (["radiator", "radiador"], "42435"),
        (["cv axle", "axle shaft", "eje"], "40564"),
        (["catalytic converter", "catalizador"], "33606"),
        (["window visor", "rain guard", "vent visor", "wind deflector",
          "visera", "viseras de ventana", "deflector de viento", 
          "deflector de lluvia", "protector de lluvia",
          "wrangler", "jeep", "gladiator", "tacoma", "tundra",
          "4runner", "ram", "sierra", "f150", "mustang", "camaro",
          "sun shade", "sunshade visor", "windshield visor"], "33637"),
        # ── Electrónica ──
        (["bluetooth headphone", "wireless headphone", "auricular", "audifonos"], "112529"),
        (["laptop", "notebook"], "177"),
        (["tablet", "ipad"], "171"),
        (["smartphone", "iphone", "android phone", "celular"], "9355"),
        (["smart watch", "smartwatch", "reloj inteligente"], "178893"),
        (["wireless charger", "cargador inalámbrico"], "183071"),
        (["security camera", "camara seguridad", "cámara de seguridad"], "114722"),
        # ── Hogar ──
        (["gaming chair", "silla gaming", "office chair", "silla de oficina"], "20625"),
        (["standing desk", "escritorio"], "23347"),
        (["air purifier", "purificador de aire"], "43514"),
        (["coffee maker", "cafetera"], "20676"),
        (["vacuum cleaner", "aspiradora"], "43569"),
        # ── Herramientas ──
        (["power drill", "taladro", "drill bit"], "631"),
        (["wrench", "llave inglesa", "socket set"], "631"),
    ]
    
    for keywords, cat_id in MAPA_CATEGORIAS:
        if any(kw in texto for kw in keywords):
            return cat_id
    
    return ""
def obtener_categoria_hoja_taxonomy(titulo: str, tienda_id: str, marketplace_id: str = "EBAY_US", excluir: set = set(), bullets: list = [], descripcion: str = "", forzar_tree_id: str = None) -> str:
    
    # PASO 1: Detección por keywords (fuente más confiable, sin APIs)
    # Usar título + bullets + descripción para máxima cobertura
    cat_rapida = detectar_categoria_por_keywords(titulo, bullets)
    if cat_rapida and cat_rapida not in excluir:
        st.success(f"⚡ Categoría detectada por keywords: `{cat_rapida}`")
        return cat_rapida
    
    # PASO 2: Si no hubo match por keywords, intentar Taxonomy API
    from urllib.parse import quote
    import base64
    import re as _re

    def limpiar_query(texto: str) -> str:
        # Eliminar emojis, caracteres unicode especiales, brackets japoneses, etc.
        texto = _re.sub(r'[^\x00-\x7F\u00C0-\u024F\u00C0-\u017E]', ' ', texto)
        # Eliminar símbolos sueltos como 【】〔〕「」
        texto = _re.sub(r'[【】〔〕「」『』（）［］｛｝]', ' ', texto)
        # Eliminar múltiples espacios
        texto = _re.sub(r'\s+', ' ', texto).strip()
        return texto

    # Usar el título de eBay en español directamente (eBay lo soporta)
    query_taxonomy = limpiar_query(titulo)
    st.info(f"🔍 Taxonomy query: '{query_taxonomy[:80]}'")

    # Obtener App Token
    try:
        app_id  = st.secrets["ebay"]["app_id"]
        cert_id = st.secrets["ebay"]["cert_id"]
        credencial = base64.b64encode(f"{app_id}:{cert_id}".encode()).decode()
        r_token = requests.post(
            "https://api.ebay.com/identity/v1/oauth2/token",
            headers={"Authorization": f"Basic {credencial}", "Content-Type": "application/x-www-form-urlencoded"},
            data="grant_type=client_credentials&scope=https%3A%2F%2Fapi.ebay.com%2Foauth%2Fapi_scope",
            timeout=15
        )
        if r_token.status_code != 200:
            return ""
        app_token = r_token.json().get("access_token", "")
    except Exception:
        return ""

    headers_tax = {"Authorization": f"Bearer {app_token}", "Accept": "application/json"}

    # Determinar tree_id
    if forzar_tree_id:
        tree_id = forzar_tree_id
        st.info(f"🚗 Tree ID forzado: {tree_id}")
    else:
        KEYWORDS_MOTORS = ["mirror","espejo","retrovisor","bumper","fender","headlight",
                           "taillight","faro","parachoque","brake","freno","rotor","strut",
                           "shock","alternator","radiator","chevy","ford","toyota","honda",
                           "gmc","dodge","chevrolet","passenger side","driver side"]
        texto_check = (titulo + " " + " ".join(bullets[:2])).lower()
        es_autoparte = any(kw in texto_check for kw in KEYWORDS_MOTORS)
        tree_id = "100" if es_autoparte else "0"

    try:
        url_sug = f"https://api.ebay.com/commerce/taxonomy/v1/category_tree/{tree_id}/get_category_suggestions?q={quote(query_taxonomy)}"
        r_sug = requests.get(url_sug, headers=headers_tax, timeout=10)
        if r_sug.status_code != 200:
            return ""

        CATEGORIAS_INVALIDAS = {
            "12","20081","550","625","30090","30097","1","64482","15724",
            "11450","2984","6000","4","353","11233","15709","99697",
            "260308","20710","50445","14936","3270","175716",
            "45794",  # Home Windows
            "180113", # Windows & Window Hardware
            "3187",   # Building & Hardware
            "11700"   # Home & Garden
        }

        for s in r_sug.json().get("categorySuggestions", []):
            cat_id = str(s.get("category", {}).get("categoryId", ""))
            if cat_id and cat_id not in excluir and cat_id not in CATEGORIAS_INVALIDAS:
                st.success(f"✅ TAXONOMY: `{cat_id}` ({s.get('category',{}).get('categoryName','')})")
                return cat_id
    except Exception as e:
        st.error(f"❌ Taxonomy excepción: {e}")

    return ""

def interpretar_error_categoria_ia(titulo: str = "", marketplace_id: str = "EBAY_US", sugerencias_ebay: str = "", extra_prompt: str = "", bullets: list = [], excluir_categorias: set = set()) -> str:
    """
    Usa Groq para sugerir un Category ID numérico de eBay basado en el título, marketplace 
    y opcionalmente sugerencias oficiales de la Taxonomy API.
    """
    try:
        api_key = st.secrets["groq"]["api_key"]
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        
        contexto_sugerencias = ""
        if sugerencias_ebay:
            contexto_sugerencias = (
                f"\n\nSugerencias oficiales de eBay:\n{sugerencias_ebay}\n\n"
                "Por favor, elige la mejor de esta lista si es apropiada."
            )
        
        sys_prompt = (
            f"Eres un experto en taxonomía de eBay ({marketplace_id}).\n"
            "Tu única tarea: devolver el CATEGORY ID numérico más específico y correcto "
            "para el producto dado.\n\n"
            "REGLAS ESTRICTAS:\n"
            "1) Analiza el título cuidadosamente antes de decidir.\n"
            "2) Si el producto es una autoparte (espejo, retrovisor, bumper, faro, etc.), "
            "usa categorías de eBay Motors Parts, ejemplo: 33637 (Mirrors), 33566 (Exterior), etc.\n"
            "3) NUNCA uses categorías de ropa (Clothing, Shoes, Apparel) para productos que NO son ropa.\n"
            "4) NUNCA uses categorías de Vehículos completos, Real Estate, Tickets.\n"
            "5) PRIORIZA categorías con envío postal estándar. Evita 'Local Pickup Only'.\n"
            f"{extra_prompt}\n"
            f"{contexto_sugerencias}\n"
            "6) Para productos de consumo general usa: Consumer Electronics, Home & Garden, "
            "Sporting Goods, Toys & Hobbies, Health & Beauty.\n"
            "7) Devuelve ÚNICAMENTE el número del Category ID. Sin explicaciones, sin texto extra.\n"
            f"8) NUNCA uses estos Category IDs que ya fallaron antes: {excluir_categorias}.\n" if excluir_categorias else ""
            "9) SIEMPRE elige la categoría más ESPECÍFICA (hoja del árbol), nunca una categoría padre o intermedia. "
            "Ejemplos correctos: Retrovisores → 262161 (Mirror Assemblies), Faros → 262241 (Headlights), "
            "Parachoques → 262200 (Bumpers), Frenos → 33559. NUNCA uses 33637 como categoría final.\n"
        )
        
        bullets_str = "\n".join(f"- {b}" for b in bullets[:5]) if bullets else "No disponible"
        user_prompt = (
            f"Título: {titulo}\n\n"
            f"Características del producto (Amazon):\n{bullets_str}\n\n"
            "Basándote en el título Y las características, devuelve el Category ID más específico y correcto."
        )
        
        payload = {
            "model": "openai/gpt-oss-120b",
            "messages": [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user_prompt}
            ]
        }
        
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers=headers, json=payload, timeout=20
        )
        if resp.status_code == 200:
            res = resp.json()['choices'][0]['message']['content'].strip()
            match = re.search(r"(\d+)", res)
            if match:
                return match.group(1)
    except Exception as e:
        print(f"DEBUG IA CATEGORIA | Error: {e}")
    return ""
# ─────────────────────────────────────────────────────────
# HELPERS HTTP
# ─────────────────────────────────────────────────────────
def construir_headers_ebay(token: str, marketplace_id: str = "EBAY_US") -> dict:
    """
    Retorna las cabeceras requeridas para la API de eBay.
    """
    return {
        "Authorization":           f"Bearer {token}",
        "Content-Type":            "application/json",
        "Content-Language":        "en-US",
        "Accept":                  "application/json",
        "X-EBAY-C-MARKETPLACE-ID": marketplace_id
    }
def hacer_peticion_con_reintento(
    metodo: str,
    url: str,
    tienda_id: str,
    payload: dict | None = None,
    marketplace_id: str | None = None
) -> requests.Response:
    """
    Wrapper HTTP con auto-renovación OAuth en errores 401.
    """
    if marketplace_id is None:
        # Recuperar marketplace_id default si no se provee
        config_tienda = st.session_state.get("config_tienda", {})
        marketplace_id = config_tienda.get("site_id", "EBAY_US")
    token = get_valid_token(tienda_id)
    headers = construir_headers_ebay(token, marketplace_id)
    kwargs = {"url": url, "headers": headers, "timeout": 20}
    if payload is not None:
        kwargs["json"] = payload
    respuesta = requests.request(metodo, **kwargs)
    # 1. Manejo de renovación de token (401)
    if respuesta.status_code == 401:
        st.warning("🔄 Token expirado. Auto-renovando...")
        nuevo_token = refresh_access_token(tienda_id)
        kwargs["headers"] = construir_headers_ebay(nuevo_token, marketplace_id)
        respuesta = requests.request(metodo, **kwargs)
    # 2. Log de depuración para errores críticos
    if respuesta.status_code >= 400:
        print(f"DEBUG EBAY API | {metodo} {url} | Status: {respuesta.status_code}")
        print(f"DEBUG EBAY API | Response: {respuesta.text}")
    return respuesta
@st.cache_data(show_spinner=False, ttl=3600)
def obtener_politicas_ebay(tienda_id: str, tipo: str, marketplace_id: str = "EBAY_US") -> dict:
    """
    Obtiene las políticas reales de la cuenta de eBay (fulfillment, payment, return).
    Cacheado por 1 hora por tipo, tienda y marketplace.
    Retorna: dict { "Nombre Política": "ID_Politica" }
    """
    url = f"{EBAY_ACCOUNT_BASE_URL}/{tipo}_policy?marketplace_id={marketplace_id}"
    # Llamamos a nuestro wrapper que maneja OAuth y reintentos automáticos
    req = hacer_peticion_con_reintento("GET", url, tienda_id)
    
    if req.status_code != 200:
        st.error(f"Error obteniendo políticas de {tipo}: {req.text}")
        return {}
    datos = req.json()
    diccionario = {}
    
    llave_lista = f"{tipo}Policies"
    if llave_lista in datos:
        for pol in datos[llave_lista]:
            nombre = pol.get("name", f"Política sin nombre ({pol.get('categoryTypes', [{'name': 'ALL'}])[0].get('name')})")
            pol_id = pol.get(f"{tipo}PolicyId")
            if pol_id:
                diccionario[nombre] = pol_id
                
    return diccionario
@st.cache_data(show_spinner=False, ttl=3600)
def obtener_ubicaciones_ebay(tienda_id: str) -> dict:
    """
    Obtiene las ubicaciones (locations) configuradas en la cuenta de eBay.
    """
    url = f"{EBAY_INVENTORY_BASE_URL}/location"
    req = hacer_peticion_con_reintento("GET", url, tienda_id)
    
    if req.status_code != 200:
        return {}
    datos = req.json()
    diccionario = {}
    
    if "locations" in datos:
        for loc in datos["locations"]:
            nombre = loc.get("name", "")
            postal = loc.get("location", {}).get("address", {}).get("postalCode", "Sin C.P.")
            pais = loc.get("location", {}).get("address", {}).get("country", "")
            
            if not nombre:
                nombre = f"Ubicación {pais} - {postal}"
            else:
                nombre = f"{nombre} ({pais} {postal})"
                
            loc_key = loc.get("merchantLocationKey")
            if loc_key:
                diccionario[nombre] = loc_key
                
    return diccionario
def crear_ubicacion_default(tienda_id: str) -> bool:
    """
    Crea una ubicación por defecto (USA Warehouse) con máxima transparencia.
    """
    location_key = "ALMACEN_USA_1"
    url = f"{EBAY_INVENTORY_BASE_URL}/location/{location_key}"
    
    payload = {
        "location": {
            "address": {
                "addressLine1": "123 Main St",
                "city": "Miami",
                "stateOrProvince": "FL",
                "postalCode": "33101",
                "country": "US"
            }
        },
        "name": "Almacén Principal USA",
        "merchantLocationStatus": "ENABLED",
        "locationTypes": ["WAREHOUSE"]
    }
    
    st.info(f"📡 Intentando crear ubicación en: `{url}`")
    
    resp = hacer_peticion_con_reintento("POST", url, tienda_id, payload)
    
    if resp.status_code in (200, 201, 204):
        st.success(f"✅ ¡Éxito! Ubicación '{location_key}' creada.")
        st.cache_data.clear() # Limpiar cache para que aparezca la nueva ubicación
        return True
    else:
        st.error(f"❌ Error {resp.status_code} al crear ubicación.")
        with st.expander("🔍 Ver Detalles Técnicos para Soporte"):
            st.write(f"**URL intentada:** `{url}`")
            st.write(f"**Headers enviados:** `{resp.request.headers}`")
            st.write(f"**Cuerpo de respuesta:**")
            st.code(resp.text, language="json")
        return False
# ─────────────────────────────────────────────────────────
# CONSTRUCTORES DE PAYLOAD
# ─────────────────────────────────────────────────────────
def construir_payload_inventory_item(producto: dict, descripcion_html: str, aspectos: dict, cantidad: int = 2) -> dict:
    """Paso A — CreateOrReplaceInventoryItem"""
    imagenes = producto.get("imagenes_amazon", [])
    # eBay requiere al menos una imagen, y un máximo de 12
    if not imagenes:
        imagenes = ["https://via.placeholder.com/800x800?text=Product+Image"]
    else:
        imagenes = imagenes[:12]
    return {
        "availability": {
            "shipToLocationAvailability": {"quantity": cantidad}
        },
        "condition": "NEW",
        "product": {
            "title":       producto["titulo"],
            "description": descripcion_html,
            "aspects": aspectos,
            "imageUrls": imagenes,
        },
    }

CATEGORIAS_EBAY_MOTORS = {
    "262161","262160","262241","262244","262200","33559","33563",
    "33640","33642","33643","33649","38635","33596","42612","33590",
    "33558","42435","40564","33606","33637","33566","33638","33639",
    "9886","50445","6030","179637","179638","10063"
}

def es_categoria_motors(category_id: str) -> bool:
    return str(category_id) in CATEGORIAS_EBAY_MOTORS

def construir_payload_oferta(
    producto: dict, 
    sku: str, 
    config_tienda: dict,
    id_envio: str,
    id_pago: str,
    id_devol: str,
    merchant_location_key: str,
    descripcion_html: str,
    cantidad: int = 2,
    marketplace_id: str = "EBAY_US"
) -> dict:
    """Paso B — CreateOffer: vincula el inventario a la tienda con precio, políticas y ubicación dinámicas."""
    precio_sugerido = float(producto.get("precio_sugerido", producto["precio_ebay"]))
    return {
        "sku":               sku,
        "listingTitle":      str(producto.get("titulo", ""))[:80],
        "marketplaceId":     marketplace_id,
        "format":            "FIXED_PRICE",
        "availableQuantity": cantidad,
        "categoryId":        str(producto["category_id"]),
        "listingDescription": descripcion_html,
        "listingPolicies": {
            "fulfillmentPolicyId": id_envio,
            "paymentPolicyId":     id_pago,
            "returnPolicyId":      id_devol,
        },
        "merchantLocationKey": merchant_location_key,
        "pricingSummary": {
            "price": {
                "currency": "USD",
                "value":    str(round(precio_sugerido, 2))
            }
        },
    }
# ─────────────────────────────────────────────────────────
# PROMOTED LISTINGS — SELL MARKETING API
# ─────────────────────────────────────────────────────────
NOMBRE_CAMPANA = "Auto_Dropshipping_Campaign"
def buscar_o_crear_campana(tienda_id: str, ad_rate_pct: float) -> str | None:
    """
    Busca una campaña RUNNING llamada 'Auto_Dropshipping_Campaign'.
    Si no existe, la crea. Retorna el campaignId o None si falla.
    """
    try:
        # 1. Buscar campaña existente
        url_buscar = f"{EBAY_MARKETING_BASE_URL}/ad_campaign?campaign_status=RUNNING&limit=100"
        resp = hacer_peticion_con_reintento("GET", url_buscar, tienda_id)
        
        if resp.status_code == 200:
            campanas = resp.json().get("campaigns", [])
            for camp in campanas:
                if camp.get("campaignName") == NOMBRE_CAMPANA:
                    return camp.get("campaignId")
        
        # 2. Si no existe, crearla
        # eBay requiere que la fecha de inicio no esté en el pasado en su reloj UTC.
        # En vez de floor a 00:00:00, mandaremos la hora UTC exacta actual + 10 segundos
        from datetime import timedelta
        ahora_iso = (datetime.now(timezone.utc) + timedelta(seconds=10)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        
        payload_campana = {
            "campaignName": NOMBRE_CAMPANA,
            "marketplaceId": "EBAY_US",
            "fundingStrategy": {
                "fundingModel": "COST_PER_SALE",
                "bidPercentage": str(round(ad_rate_pct, 1))
            },
            "startDate": ahora_iso
        }
        
        resp_crear = hacer_peticion_con_reintento("POST", f"{EBAY_MARKETING_BASE_URL}/ad_campaign", tienda_id, payload_campana)
        
        if resp_crear.status_code in (201, 200):
            # campaignId puede venir en el body o en el header Location
            body = resp_crear.json() if resp_crear.text else {}
            campaign_id = body.get("campaignId", "")
            if not campaign_id:
                location = resp_crear.headers.get("Location", "")
                if location:
                    campaign_id = location.rstrip("/").split("/")[-1]
            return campaign_id if campaign_id else None
        else:
            try:
                err_detalle = resp_crear.json()
            except Exception:
                err_detalle = resp_crear.text
            st.warning(f"⚠️ No se pudo crear la campaña de Promoted Listings ({resp_crear.status_code}): {err_detalle}")
            return None
            
    except Exception as e:
        st.warning(f"⚠️ Error buscando/creando campaña: {str(e)[:200]}")
        return None
def agregar_ad_a_campana(tienda_id: str, campaign_id: str, listing_id: str, bid_pct: float) -> bool:
    """
    Añade un listingId a una campaña de Promoted Listings Standard.
    Retorna True si tiene éxito, False si falla (sin lanzar excepción).
    """
    try:
        url_ad = f"{EBAY_MARKETING_BASE_URL}/ad_campaign/{campaign_id}/ad"
        payload_ad = {
            "listingId": str(listing_id),
            "bidPercentage": str(round(bid_pct, 1))
        }
        resp = hacer_peticion_con_reintento("POST", url_ad, tienda_id, payload_ad)
        
        if resp.status_code in (200, 201):
            return True
        else:
            st.warning(f"⚠️ No se pudo añadir el ad a la campaña ({resp.status_code}): {resp.text[:200]}")
            return False
    except Exception as e:
        st.warning(f"⚠️ Error al añadir ad: {str(e)[:200]}")
        return False
# ─────────────────────────────────────────────────────────
# FUNCIÓN PRINCIPAL DE PUBLICACIÓN
# ─────────────────────────────────────────────────────────
def publicar_en_ebay(
    producto: dict, 
    tienda_id: str, 
    config_tienda: dict,
    pol_fulfillment_id: str,
    pol_payment_id: str,
    pol_return_id: str,
    merchant_location_key: str,
    cantidad: int = 2,
    promocionar: bool = False,
    ad_rate_pct: float = 12.0
) -> tuple[bool, str]:
    max_reintentos_globales = 5
    intento_global = 0
    # Prioridad al marketplace detectado por el Cazador
    marketplace_id = producto.get("marketplace_id") or config_tienda.get("site_id", "EBAY_US")
    
    # Corrección preventiva de categoría ANTES de publicar
    titulo_prev = producto.get("titulo", "")
    bullets_prev = producto.get("bullets_amazon", [])

    BLACKLIST_CATEGORIAS = {
        "122773",  # Eye Drops & Wash
        "31414",   # Vision Care
        "26395",   # Health & Beauty
        "15709",   # Athletic Shoes
        "99697",   # Washer & Dryer Parts
        "45794",   # Home Windows
        "12",      # Other Antiques
        "50445",   # Decals & Vinyls
        "14936",   # Car Speakers
        "6007",    # eBay Motors ROOT subcategory genérica
        "6005",    # eBay Motors ROOT subcategory genérica
        "6006",    # eBay Motors ROOT subcategory genérica
    }

    # DIAGNÓSTICO
    st.info(f"📋 Título eBay: '{titulo_prev}'")
    st.info(f"📋 Categoría original: '{producto['category_id']}'")

    es_motors = st.session_state.get("es_motors", False)

    if es_motors:
        marketplace_id = "EBAY_MOTORS"
        st.info("🚗 Marketplace: EBAY_MOTORS (activado por usuario)")
        # Corregir categoría con Taxonomy árbol 100
        cat_taxonomy = obtener_categoria_hoja_taxonomy(
            titulo_prev, tienda_id, "EBAY_MOTORS",
            excluir={str(producto["category_id"])},
            bullets=bullets_prev,
            forzar_tree_id="100"
        )
        if cat_taxonomy:
            producto["category_id"] = cat_taxonomy
            st.success(f"✅ Categoría Motors: `{cat_taxonomy}`")
    else:
        # Si es_motors=False → no tocar nada, respetar categoría original del Cazador
        st.info(f"🛒 Marketplace: {marketplace_id}")
        # Solo corregir si la categoría original está en blacklist
        if str(producto["category_id"]) in BLACKLIST_CATEGORIAS:
            st.warning(f"⚠️ Categoría `{producto['category_id']}` en blacklist. Buscando alternativa...")
            cat_taxonomy = obtener_categoria_hoja_taxonomy(
                titulo_prev, tienda_id, marketplace_id,
                excluir=BLACKLIST_CATEGORIAS,
                bullets=bullets_prev
            )
            if cat_taxonomy:
                producto["category_id"] = cat_taxonomy
                st.success(f"✅ Categoría corregida: `{cat_taxonomy}`")


    categorias_intentadas = set()
    while intento_global < max_reintentos_globales:
        sku = f"DS-{str(uuid.uuid4())[:8].upper()}"
        try:
            from skills.groq_agent import GroqAssistant
            agente_groq = GroqAssistant()
            
            # Solo generamos descripción y aspectos en el primer intento global
            if intento_global == 0:
                with st.spinner('🧠 Groq redactando descripción y specs...'):
                    titulo = producto['titulo']
                    bullets = producto.get('bullets_amazon', [])
                    descripcion_html_generada = agente_groq.generar_descripcion(titulo, bullets)
                    aspectos_json = agente_groq.generar_aspectos(titulo, bullets)
                    try:
                        aspectos_dict = json.loads(aspectos_json)
                    except Exception:
                        aspectos_dict = {"Brand": ["Unbranded"], "MPN": ["Does Not Apply"]}
            
            # ── Paso A: CreateOrReplaceInventoryItem ──
            url_item = f"{EBAY_INVENTORY_BASE_URL}/inventory_item/{sku}"
            payload_item = construir_payload_inventory_item(producto, descripcion_html_generada, aspectos_dict, cantidad)
            
            st.markdown(f"**Paso A (Intento {intento_global+1})** — `PUT {url_item}`")
            req_item = hacer_peticion_con_reintento("PUT", url_item, tienda_id, payload_item, marketplace_id=marketplace_id)
            req_item.raise_for_status()
            st.success(f"✅ Inventory Item creado — SKU: `{sku}`")
            # ── Paso B: CreateOffer ──
            url_offer = f"{EBAY_INVENTORY_BASE_URL}/offer"
            # Ajustar marketplace según categoría
            marketplace_oferta = "EBAY_MOTORS" if es_categoria_motors(str(producto["category_id"])) else marketplace_id
            payload_oferta = construir_payload_oferta(
                producto, sku, config_tienda, 
                pol_fulfillment_id, pol_payment_id, pol_return_id, 
                merchant_location_key,
                descripcion_html_generada, cantidad,
                marketplace_id=marketplace_oferta
            )
            
            st.markdown(f"**Paso B** — `POST {url_offer}`")
            req_offer = hacer_peticion_con_reintento("POST", url_offer, tienda_id, payload_oferta, marketplace_id=marketplace_id)
            
            if req_offer.status_code == 400:
                errores = req_offer.json().get("errors", [])
                # 1. Error de Categoría (25005)
                if any(err.get("errorId") == 25005 for err in errores):
                    st.warning("⚠️ Categoría inválida (25005). Consultando Taxonomy API...")
                    categorias_intentadas.add(str(producto["category_id"]))
                    
                    # Primero: intentar con Taxonomy API directamente (más confiable)
                    nueva_cat = obtener_categoria_hoja_taxonomy(
                        titulo, tienda_id, marketplace_id,
                        excluir=categorias_intentadas,
                        bullets=bullets,
                        descripcion=producto.get("descripcion_amazon", "")
                    )
                    
                    # Segundo: si Taxonomy no devuelve nada, usar IA como fallback
                    if not nueva_cat:
                        st.warning("⚠️ Taxonomy API sin resultados. Usando IA como fallback...")
                        sugerencias = obtener_sugerencias_ebay_taxonomy(titulo, tienda_id, marketplace_id)
                        nueva_cat = interpretar_error_categoria_ia(titulo, marketplace_id, sugerencias, bullets=bullets, excluir_categorias=categorias_intentadas)
                    
                    if nueva_cat:
                        st.warning(f"🔄 Categoría corregida: `{nueva_cat}`. Reintentando...")
                        producto["category_id"] = nueva_cat
                        intento_global += 1
                        continue
                    else:
                        return False, "❌ Error 25005: No se encontró una categoría válida tras agotar todas las estrategias."
                
                # 2. Error de Cantidad (25006)
                if any(err.get("errorId") == 25006 for err in errores):
                    st.warning("⚠️ eBay solo permite cantidad de 1 en esta categoría. Ajustando stock a 1 y reintentando...")
                    cantidad = 1
                    intento_global += 1
                    continue
                # CAMBIO 1 — Manejar errorId 25008 en Paso B (CreateOffer)
                if any(err.get("errorId") == 25008 for err in errores):
                    with st.spinner("🔍 Categoría fuerza Local Pickup. Buscando alternativa postal..."):
                        sugerencias = obtener_sugerencias_ebay_taxonomy(titulo, tienda_id, marketplace_id)
                        extra = (
                            "CRÍTICO: La categoría anterior obliga a 'Local Pickup Only'. "
                            "DEBES elegir una categoría que permita envío postal estándar (USPS, FedEx, UPS). "
                            "EXCLUYE: Vehículos, Motocicletas, Botes, Maquinaria pesada, Real Estate, Tickets, "
                            "Artículos de gran tamaño (más de 150 lbs), y cualquier categoría que no permita shipping."
                        )
                        categorias_intentadas.add(str(producto["category_id"]))
                        nueva_cat = interpretar_error_categoria_ia(titulo, marketplace_id, sugerencias, extra_prompt=extra, bullets=bullets, excluir_categorias=categorias_intentadas)
                        if nueva_cat and nueva_cat != str(producto["category_id"]):
                            st.warning(f"🔄 Categoría corregida (Local Pickup → Postal): `{nueva_cat}`")
                            producto["category_id"] = nueva_cat
                            intento_global += 1
                            continue
                        else:
                            return False, "❌ Error 25008: No se encontró categoría compatible con envío postal."
                # LUGAR 1 — Mano de error 25002 en Paso B (CreateOffer)
                if any(err.get("errorId") == 25002 for err in errores):
                    error_json_str = json.dumps(req_offer.json())
                    ASPECTOS_ROPA = {"sleeve length", "size type", "size", "department", 
                                     "style", "pattern", "fabric type", "gender", "age group",
                                     "neckline", "fit", "occasion", "season", "theme"}
                    aspectos_requeridos = set()
                    for err in errores:
                        if err.get("errorId") == 25002:
                            params = err.get("parameters", [])
                            for p in params:
                                if p.get("name") == "2":
                                    aspectos_requeridos.add(p.get("value", "").lower())
                    
                    es_categoria_ropa = bool(aspectos_requeridos & ASPECTOS_ROPA)
                    
                    if es_categoria_ropa:
                        st.warning("⚠️ eBay detectó categoría de ropa para un producto que no es ropa. Cambiando categoría...")
                        sugerencias = obtener_sugerencias_ebay_taxonomy(titulo, tienda_id, marketplace_id)
                        extra = (
                            "CRÍTICO: La categoría asignada es de ROPA pero el producto NO es ropa. "
                            "eBay está pidiendo 'Sleeve Length', 'Size Type' u otros aspectos de vestimenta. "
                            "DEBES elegir la categoría correcta para este producto ignorando completamente "
                            "las categorías de Clothing, Shoes, Accessories, Apparel o Fashion."
                        )
                        categorias_intentadas.add(str(producto["category_id"]))
                        nueva_cat = interpretar_error_categoria_ia(titulo, marketplace_id, sugerencias, extra_prompt=extra, bullets=bullets, excluir_categorias=categorias_intentadas)
                        if nueva_cat and nueva_cat != str(producto["category_id"]):
                            st.warning(f"🔄 Categoría corregida (Ropa → Correcta): `{nueva_cat}`")
                            producto["category_id"] = nueva_cat
                            intento_global += 1
                            continue
                        else:
                            return False, "❌ Error 25002: No se pudo asignar una categoría correcta para este producto."
                    else:
                        st.warning("⚠️ eBay requiere más especificaciones. Corrigiendo con IA...")
                        nuevos_aspectos = interpretar_error_aspectos_ia(error_json_str, titulo, bullets)
                        if nuevos_aspectos:
                            aspectos_dict.update(nuevos_aspectos)
                            st.info(f"🔧 Aspectos corregidos: {list(nuevos_aspectos.keys())}")
                            intento_global += 1
                            continue
                        else:
                            return False, "❌ Error 25002: No se pudieron completar los Item Specifics requeridos."
            
            req_offer.raise_for_status()
            offer_id = req_offer.json().get("offerId", "")
            st.success(f"✅ Offer creada — Offer ID: `{offer_id}`")
            # ── Paso C: PublishOffer ──
            url_publish = f"{EBAY_INVENTORY_BASE_URL}/offer/{offer_id}/publish"
            st.markdown(f"**Paso C** — `POST {url_publish}`")
            req_publish = hacer_peticion_con_reintento("POST", url_publish, tienda_id, {}, marketplace_id=marketplace_id)
            if req_publish.status_code == 400:
                errores = req_publish.json().get("errors", [])
                # 1. Error de Categoría (25005)
                if any(err.get("errorId") == 25005 for err in errores):
                    st.warning("⚠️ Categoría inválida (25005). Consultando Taxonomy API...")
                    categorias_intentadas.add(str(producto["category_id"]))
                    
                    # Primero: intentar con Taxonomy API directamente (más confiable)
                    nueva_cat = obtener_categoria_hoja_taxonomy(
                        titulo, tienda_id, marketplace_id,
                        excluir=categorias_intentadas,
                        bullets=bullets,
                        descripcion=producto.get("descripcion_amazon", "")
                    )
                    
                    # Segundo: si Taxonomy no devuelve nada, usar IA como fallback
                    if not nueva_cat:
                        st.warning("⚠️ Taxonomy API sin resultados. Usando IA como fallback...")
                        sugerencias = obtener_sugerencias_ebay_taxonomy(titulo, tienda_id, marketplace_id)
                        nueva_cat = interpretar_error_categoria_ia(titulo, marketplace_id, sugerencias, bullets=bullets, excluir_categorias=categorias_intentadas)
                    
                    if nueva_cat:
                        st.warning(f"🔄 Categoría corregida: `{nueva_cat}`. Reintentando...")
                        producto["category_id"] = nueva_cat
                        intento_global += 1
                        continue
                    else:
                        return False, "❌ Error 25005: No se encontró una categoría válida tras agotar todas las estrategias."
                
                # 2. Error de Cantidad (25006)
                if any(err.get("errorId") == 25006 for err in errores):
                    st.warning("⚠️ eBay solo permite cantidad de 1 (detectado en Publish). Ajustando stock a 1 y reintentando...")
                    cantidad = 1
                    intento_global += 1
                    continue
                # CAMBIO 2 — Mismo manejo en Paso C (PublishOffer)
                if any(err.get("errorId") == 25008 for err in errores):
                    with st.spinner("🔍 Categoría fuerza Local Pickup. Buscando alternativa postal..."):
                        sugerencias = obtener_sugerencias_ebay_taxonomy(titulo, tienda_id, marketplace_id)
                        extra = (
                            "CRÍTICO: La categoría anterior obliga a 'Local Pickup Only'. "
                            "DEBES elegir una categoría que permita envío postal estándar (USPS, FedEx, UPS). "
                            "EXCLUYE: Vehículos, Motocicletas, Botes, Maquinaria pesada, Real Estate, Tickets, "
                            "Artículos de gran tamaño (más de 150 lbs), y cualquier categoría que no permita shipping."
                        )
                        categorias_intentadas.add(str(producto["category_id"]))
                        nueva_cat = interpretar_error_categoria_ia(titulo, marketplace_id, sugerencias, extra_prompt=extra, bullets=bullets, excluir_categorias=categorias_intentadas)
                        if nueva_cat and nueva_cat != str(producto["category_id"]):
                            st.warning(f"🔄 Categoría corregida (Local Pickup → Postal): `{nueva_cat}`")
                            producto["category_id"] = nueva_cat
                            intento_global += 1
                            continue
                        else:
                            return False, "❌ Error 25008: No se encontró categoría compatible con envío postal."
                
                # Manejo de error 25604: Product not in catalog
                if any(err.get("errorId") == 25604 for err in errores):
                    st.warning("⚠️ Error 25604: eBay no encontró el producto en catálogo. Reintentando...")
                    intento_global += 1
                    continue

                # LUGAR 2 — Manejo de error 25002 en Paso C (PublishOffer)
                if any(err.get("errorId") == 25002 for err in errores):
                    error_json_str = json.dumps(req_publish.json())
                    ASPECTOS_ROPA = {"sleeve length", "size type", "size", "department", 
                                     "style", "pattern", "fabric type", "gender", "age group",
                                     "neckline", "fit", "occasion", "season", "theme"}
                    aspectos_requeridos = set()
                    for err in errores:
                        if err.get("errorId") == 25002:
                            params = err.get("parameters", [])
                            for p in params:
                                if p.get("name") == "2":
                                    aspectos_requeridos.add(p.get("value", "").lower())
                    
                    es_categoria_ropa = bool(aspectos_requeridos & ASPECTOS_ROPA)
                    
                    if es_categoria_ropa:
                        st.warning("⚠️ eBay detectó categoría de ropa para un producto que no es ropa. Cambiando categoría...")
                        sugerencias = obtener_sugerencias_ebay_taxonomy(titulo, tienda_id, marketplace_id)
                        extra = (
                            "CRÍTICO: La categoría asignada es de ROPA pero el producto NO es ropa. "
                            "eBay está pidiendo 'Sleeve Length', 'Size Type' u otros aspectos de vestimenta. "
                            "DEBES elegir la categoría correcta para este producto ignorando completamente "
                            "las categorías de Clothing, Shoes, Accessories, Apparel o Fashion."
                        )
                        categorias_intentadas.add(str(producto["category_id"]))
                        nueva_cat = interpretar_error_categoria_ia(titulo, marketplace_id, sugerencias, extra_prompt=extra, bullets=bullets, excluir_categorias=categorias_intentadas)
                        if nueva_cat and nueva_cat != str(producto["category_id"]):
                            st.warning(f"🔄 Categoría corregida (Ropa → Correcta): `{nueva_cat}`")
                            producto["category_id"] = nueva_cat
                            intento_global += 1
                            continue
                        else:
                            return False, "❌ Error 25002: No se pudo asignar una categoría correcta para este producto."
                    else:
                        st.warning("⚠️ eBay requiere más especificaciones (Publish). Corrigiendo con IA...")
                        nuevos_aspectos = interpretar_error_aspectos_ia(error_json_str, titulo, bullets)
                        if nuevos_aspectos:
                            aspectos_dict.update(nuevos_aspectos)
                            st.info(f"🔧 Aspectos corregidos: {list(nuevos_aspectos.keys())}")
                            intento_global += 1
                            continue
                        else:
                            return False, "❌ Error 25002: No se pudieron completar los Item Specifics requeridos."
            # Manejo de error 500 — eBay server error (25001)
            if req_publish.status_code == 500:
                try:
                    errores_500 = req_publish.json().get("errors", [])
                except Exception:
                    errores_500 = []
                if any(err.get("errorId") == 25001 for err in errores_500):
                    st.warning("⚠️ Error interno de eBay (25001). Reintentando en 3 segundos...")
                    import time
                    time.sleep(3)
                    intento_global += 1
                    continue
            req_publish.raise_for_status()
            listing_id = req_publish.json().get("listingId", "N/A")
            
            mensaje_exito = (
                f"✅ **Publicado exitosamente**\n\n"
                f"🎫 **SKU:** `{sku}`\n\n"
                f"📌 **Listing ID:** [`{listing_id}`](https://www.ebay.com/itm/{listing_id})"
            )
            # ── Paso D: Promoted Listings ──
            if promocionar and listing_id != "N/A":
                st.markdown(f"**Paso D** — Promoted Listings Standard")
                campaign_id = buscar_o_crear_campana(tienda_id, ad_rate_pct)
                if campaign_id:
                    if agregar_ad_a_campana(tienda_id, campaign_id, listing_id, ad_rate_pct):
                        st.success(f"📢 Producto promocionado: {ad_rate_pct}%")
                        mensaje_exito += f"\n\n📢 **Promoted Listings:** Ad Rate {ad_rate_pct}%"
            return (True, mensaje_exito)
        except requests.exceptions.HTTPError as e:
            if intento_global >= max_reintentos_globales - 1:
                return False, f"❌ Error HTTP {e.response.status_code} tras varios intentos:\n{e.response.text}"
            intento_global += 1
            st.warning(f"⚠️ Error eBay. Reintentando flujo completo con SKU nuevo ({intento_global}/{max_reintentos_globales})...")
        except Exception as e:
            if intento_global >= max_reintentos_globales - 1:
                return False, f"❌ Error inesperado tras varios intentos: {str(e)}"
            intento_global += 1
            st.warning(f"⚠️ Reintentando flujo global por error: {str(e)[:100]}")
    
    return False, "❌ No se pudo publicar tras agotar todos los reintentos y estrategias de recuperación."
# ─────────────────────────────────────────────────────────
# UI
# ─────────────────────────────────────────────────────────
def renderizar_sidebar() -> None:
    with st.sidebar:
        st.title("🚀 Publicador")
        st.markdown("---")
        if "tienda_activa_id" not in st.session_state:
            st.warning("⚠️ Selecciona una tienda en el Dashboard.")
            st.page_link("app.py", label="Ir al Dashboard")
            st.stop()
        t_id_sidebar = st.session_state.get("tienda_activa_id")
        t_nombre = st.session_state.get("config_tienda", {}).get("nombre", "")
        st.info(f"**Usuario:** {t_nombre}\n**ID:** `{t_id_sidebar}`")
        if st.button("Forzar Renovación OAuth"):
            with st.spinner("Renovando..."):
                refresh_access_token(t_id_sidebar)
                st.success("Renovado!")
        st.markdown("---")
        st.page_link("pages/1_cazador.py", label="← Ir al Cazador")
def main() -> None:
    renderizar_sidebar()
    st.title("🚀 Publicador Automático — eBay Inventory API")
    # ── Guardianes de Session State ──────────────────────
    if "tienda_activa_id" not in st.session_state:
        st.warning("⚠️ Sin tienda activa. Selecciona una en el Dashboard.")
        st.stop()
    tienda_id = st.session_state["tienda_activa_id"]
    cfg       = st.session_state["config_tienda"]
    producto  = st.session_state.get("producto_aprobado")
    st.info(f"🏪 **Sesión activa:** {cfg['nombre']} | API: eBay Inventory v1")
    st.divider()
    if not producto:
        st.warning("⚠️ **No hay producto aprobado.** Ve al Cazador y aprueba un producto primero.")
        st.page_link("pages/1_cazador.py", label="→ Ir al Cazador")
        st.stop()
    if producto.get("tienda_origen") != tienda_id:
        st.warning("⚠️ El producto fue cazado en otra tienda. Cambia de tienda o vuelve a cazar.")
        st.stop()
    # ── Panel de Revisión del Producto ───────────────────
    st.subheader("📦 Resumen del Producto a Publicar")
    col_info, col_img = st.columns([2, 1])
    with col_info:
        st.markdown(f"**Título:** {producto['titulo']}")
        categoria_editada = st.text_input(
            "✏️ Category ID (editable — usa la categoría hoja más específica)",
            value=str(producto["category_id"]),
            help="Corrígelo si es necesario. Ejemplo para retrovisores: 262161 (Mirror Assemblies)"
        )
        producto["category_id"] = categoria_editada.strip()
        precio_sugerido = producto.get("precio_sugerido", producto["precio_ebay"])
        m1, m2, m3 = st.columns(3)
        m1.metric("Precio Original eBay", f"${producto['precio_ebay']:.2f}")
        m2.metric("🏷️ Precio Sugerido (-$0.05)", f"${precio_sugerido:.2f}", delta="-$0.05 undercut")
        m3.metric("💰 Ganancia Neta Estimada", f"${producto['ganancia_neta']:.2f}", delta=f"{producto['margen_pct']}%")
    with col_img:
        imagenes = producto.get("imagenes_amazon", [])
        if imagenes:
            st.image(imagenes[0], caption="Imagen Principal (Amazon)", use_container_width=True)
        else:
            st.info("Sin imagen extraída.")
    # ── Expanders informativos ───────────────────────────
    with st.expander("🖼️ Todas las imágenes del producto", expanded=False):
        if imagenes:
            cols = st.columns(min(len(imagenes), 4))
            for i, img in enumerate(imagenes):
                cols[i % 4].image(img, use_container_width=True)
        else:
            st.info("No hay imágenes en el paquete.")
    with st.expander("📝 Bullets y descripción que se publicarán", expanded=False):
        bullets = producto.get("bullets_amazon", [])
        st.markdown("**Características:**")
        for b in bullets:
            st.markdown(f"- {b}")
        st.markdown("**Descripción principal:**")
        st.info(producto.get("descripcion_amazon", "Sin descripción."))
    with st.expander("🔍 Preview del HTML que irá a eBay", expanded=False):
        st.info("La descripción HTML final y las especificaciones técnicas serán generadas en tiempo real por la Inteligencia Artificial (Groq) al momento de publicar.")
    st.divider()
    # ── Selector Dinámico de Políticas y Ubicaciones ────────────────
    st.subheader("⚙️ Configuración de Listado (eBay Account & Inventory API)")
    
    current_marketplace = producto.get("marketplace_id") or cfg.get("site_id", "EBAY_US")
    
    with st.spinner(f"Cargando información de tu cuenta ({current_marketplace})..."):
        politicas_envio = obtener_politicas_ebay(tienda_id, "fulfillment", current_marketplace)
        politicas_pago  = obtener_politicas_ebay(tienda_id, "payment", current_marketplace)
        politicas_devol = obtener_politicas_ebay(tienda_id, "return", current_marketplace)
        ubicaciones     = obtener_ubicaciones_ebay(tienda_id)
        
    if not politicas_envio or not politicas_pago or not politicas_devol:
        st.error("No se pudieron cargar todas las políticas de la cuenta. Verifica que tu cuenta de eBay tenga políticas configuradas (Fulfillment, Payment, Return).")
        st.stop()
        
    if not ubicaciones:
        st.warning("⚠️ **Tu cuenta de eBay no tiene ninguna 'Ubicación' configurada.**")
        st.info("eBay necesita saber desde dónde envías tus productos. ¿Quieres crear una ubicación por defecto en Miami, FL?")
        
        if st.button("📍 Crear Ubicación por Defecto (USA)"):
            with st.spinner("Creando ubicación en eBay..."):
                if crear_ubicacion_default(tienda_id):
                    st.success("✅ Ubicación creada con éxito. Refrescando...")
                    st.rerun()
        st.stop()
        
    p1, p2 = st.columns(2)
    p3, p4 = st.columns(2)
    
    sel_envio_nombre = p1.selectbox("📦 Política de Envío", options=list(politicas_envio.keys()))
    sel_pago_nombre  = p2.selectbox("💳 Política de Pago", options=list(politicas_pago.keys()))
    sel_devol_nombre = p3.selectbox("🔄 Política de Devolución", options=list(politicas_devol.keys()))
    sel_ubicacion_nombre = p4.selectbox("📍 Ubicación del Artículo", options=list(ubicaciones.keys()))
    
    id_envio = politicas_envio[sel_envio_nombre]
    id_pago  = politicas_pago[sel_pago_nombre]
    id_devol = politicas_devol[sel_devol_nombre]
    id_ubicacion = ubicaciones[sel_ubicacion_nombre]
    st.divider()
    # ── Configuración Avanzada: Stock y Promoción ────────────────
    st.subheader("📊 Stock y Promoción")
    col_stock, col_promo = st.columns(2)
    
    with col_stock:
        cantidad_stock = st.number_input(
            "📦 Cantidad de Stock a Listar",
            min_value=1, max_value=100, value=2, step=1,
            help="Cantidad que aparecerá como disponible en tu listing de eBay."
        )
    
    with col_promo:
        promocionar = st.checkbox("📢 Promocionar este listado (Promoted Listings)", value=True)
        if promocionar:
            ad_rate_pct = st.number_input(
                "📊 Ad Rate (%)",
                min_value=1.0, max_value=50.0, value=12.0, step=0.5,
                help="Porcentaje del precio final que pagarás como tarifa publicitaria a eBay."
            )
        else:
            ad_rate_pct = 12.0
    st.divider()
    # ── Toggle eBay Motors ───────────────────────────────────────
    es_motors = st.toggle(
        "🚗 Producto de eBay Motors (autopartes)",
        value=False,
        help="Activa esto si el producto es una autoparte. Usa el árbol de categorías eBay Motors (tree_id=100) y ajusta el marketplace automáticamente."
    )
    st.session_state["es_motors"] = es_motors
    if es_motors:
        st.info("🚗 Modo Motors activo: se usará tree_id=100 y marketplaceId=EBAY_MOTORS")
    st.divider()
    # ── Botón Principal ────────────────────────────────────────────
    col_btn, _ = st.columns([1, 3])
    with col_btn:
        botton_pub = st.button("🚀 Publicar en eBay AHORA", type="primary", use_container_width=True)
    if botton_pub:
        st.divider()
        st.subheader("📡 Progreso de la publicación")
        with st.spinner("Comunicando con eBay Inventory API..."):
            exito, mensaje = publicar_en_ebay(
                producto, tienda_id, cfg, 
                id_envio, id_pago, id_devol, id_ubicacion,
                cantidad=cantidad_stock,
                promocionar=promocionar,
                ad_rate_pct=ad_rate_pct
            )
        st.divider()
        if exito:
            st.success(mensaje)
            st.balloons()
            st.session_state["producto_aprobado"] = None  # Limpiar después de publicar
        else:
            st.error(mensaje)
            st.info("💡 Si el error es 401, usa el botón 'Forzar Renovación OAuth' en la barra lateral.")
if __name__ == "__main__":
    main()
