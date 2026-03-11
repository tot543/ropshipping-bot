"""
pages/2_publicador.py — Módulo Publicador (eBay Inventory API)
==============================================================================
Toma el paquete completo del producto aprobado por el Cazador y lo publica en
eBay a través de la Inventory API (CreateOrReplaceInventoryItem + CreateOffer).
Usa OAuth con Auto-Renovación en cada petición HTTP.
Incluye Promoted Listings Standard (Sell Marketing API) y Stock Dinámico.
"""

import sys
import os
import uuid
import json
import streamlit as st
import requests
import re
from datetime import datetime, timezone

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.ebay_auth import get_valid_token, refresh_access_token

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


def interpretar_error_categoria_ia(titulo: str = "") -> str:
    """
    Usa Groq para sugerir un Category ID numérico de eBay basado en el título.
    """
    try:
        api_key = st.secrets["groq"]["api_key"]
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        
        sys_prompt = (
            "Eres un experto en taxonomía de eBay US.\n"
            "Dada la descripción o título de un producto, debes devolver el CATEGORY ID (numérico) más apropiado.\n"
            "INSTRUCCIONES:\n"
            "1) Responde ÚNICAMENTE con el número del category ID.\n"
            "2) No incluyas texto, markdown ni explicaciones.\n"
            "3) Si no estás seguro, usa una categoría general como '172008' (Cámaras) o similar según el contexto."
        )
        
        user_prompt = f"Título del producto: {titulo}"
        
        payload = {
            "model": "openai/gpt-oss-120b",
            "messages": [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user_prompt}
            ]
        }
        
        resp = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload, timeout=20)
        if resp.status_code == 200:
            res = resp.json()['choices'][0]['message']['content'].strip()
            # Extraer solo el número por si la IA se puso habladora
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
    payload: dict | None = None
) -> requests.Response:
    """
    Wrapper HTTP con auto-renovación OAuth en errores 401.
    """
    # Recuperar marketplace_id para las cabeceras
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
        print(f"DEBUG EBAY API | Response: {respuesta.text[:500]}")

    return respuesta


@st.cache_data(show_spinner=False, ttl=3600)
def obtener_politicas_ebay(tienda_id: str, tipo: str) -> dict:
    """
    Obtiene las políticas reales de la cuenta de eBay (fulfillment, payment, return).
    Cacheado por 1 hora por tipo y tienda para no saturar la API.
    Retorna: dict { "Nombre Política": "ID_Politica" }
    """
    url = f"{EBAY_ACCOUNT_BASE_URL}/{tipo}_policy?marketplace_id=EBAY_US"
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


def construir_payload_oferta(
    producto: dict, 
    sku: str, 
    config_tienda: dict,
    pol_fulfillment_id: str,
    pol_payment_id: str,
    pol_return_id: str,
    merchant_location_key: str,
    descripcion_html: str,
    cantidad: int = 2
) -> dict:
    """Paso B — CreateOffer: vincula el inventario a la tienda con precio, políticas y ubicación dinámicas."""
    precio_sugerido = float(producto.get("precio_sugerido", producto["precio_ebay"]))

    return {
        "sku":               sku,
        "marketplaceId":     config_tienda.get("site_id", "EBAY_US"),
        "format":            "FIXED_PRICE",
        "availableQuantity": cantidad,
        "categoryId":        str(producto["category_id"]),
        "listingDescription": descripcion_html,
        "listingPolicies": {
            "fulfillmentPolicyId": pol_fulfillment_id,
            "paymentPolicyId":     pol_payment_id,
            "returnPolicyId":      pol_return_id,
        },
        "merchantLocationKey": merchant_location_key,
        "pricingSummary": {
            "price": {
                "currency": "USD",
                "value":    str(round(precio_sugerido, 2))
            }
        },
        "tax": {
            "applyTax":               True,
            "thirdPartyTaxCategory":  "Electronics"
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
    sku = f"DS-{str(uuid.uuid4())[:8].upper()}"

    try:
        from skills.groq_agent import GroqAssistant
        agente_groq = GroqAssistant()
        
        with st.spinner('🧠 Groq redactando descripción y specs...'):
            titulo = producto['titulo']
            bullets = producto.get('bullets_amazon', [])
            
            descripcion_html_generada = agente_groq.generar_descripcion(titulo, bullets)
            
            aspectos_json = agente_groq.generar_aspectos(titulo, bullets)
            try:
                aspectos_dict = json.loads(aspectos_json)
            except Exception:
                aspectos_dict = {
                    "Brand": ["Unbranded"],
                    "MPN": ["Does Not Apply"],
                    "Country/Region of Manufacture": ["United States"],
                    "Type": ["Does Not Apply"]
                }

        # ── Paso A: CreateOrReplaceInventoryItem (Con Auto-Healing) ──
        url_item = f"{EBAY_INVENTORY_BASE_URL}/inventory_item/{sku}"
        max_reintentos = 3
        intento = 0
        exito_item = False
        
        while intento <= max_reintentos and not exito_item:
            payload_item = construir_payload_inventory_item(producto, descripcion_html_generada, aspectos_dict, cantidad)
            
            if intento == 0:
                st.markdown(f"**Paso A** — `PUT {url_item}`")
                with st.expander("📋 Ver payload Inventory Item", expanded=False):
                    st.json(payload_item)
            else:
                st.warning(f"🔄 Auto-Healing Action: Reintento {intento}/{max_reintentos} para Inventory Item...")
                
            req_item = hacer_peticion_con_reintento("PUT", url_item, tienda_id, payload_item)
            
            try:
                req_item.raise_for_status()
                exito_item = True
                st.success(f"✅ Inventory Item creado — SKU: `{sku}` | Cantidad: {cantidad}")
            except requests.exceptions.HTTPError as e:
                # Intentar auto-healing si el error es de cliente (400)
                if req_item.status_code == 400:
                    try:
                        errores = req_item.json().get("errors", [])
                        errores_25002 = [err for err in errores if err.get("errorId") == 25002]
                        if errores_25002:
                            with st.spinner("🧠 IA interpretando requisitos de eBay..."):
                                try:
                                    dict_ia = interpretar_error_aspectos_ia(req_item.text, titulo, bullets)
                                    if dict_ia:
                                        aspectos_dict.update(dict_ia)
                                        st.info(f"🛠️ Super Intelligence: IA sugiriendo valores corregidos: {', '.join(dict_ia.keys())}. Aplicando...")
                                        intento += 1
                                        continue
                                    else:
                                        st.warning("⚠️ La IA no pudo identificar qué aspectos faltan.")
                                except Exception as ia_err:
                                    st.warning(f"⚠️ Error en IA de recuperación: {ia_err}")
                    except Exception as ex:
                        st.warning(f"Error parseando auto-healing: {str(ex)}")
                raise e

        # ── Paso B: CreateOffer (Con Auto-Healing para Categoría) ──
        url_offer = f"{EBAY_INVENTORY_BASE_URL}/offer"
        max_reintentos_offer = 3
        intento_offer = 0
        offer_id = None
        
        while intento_offer <= max_reintentos_offer and offer_id is None:
            payload_oferta = construir_payload_oferta(
                producto, sku, config_tienda, 
                pol_fulfillment_id, pol_payment_id, pol_return_id, merchant_location_key,
                descripcion_html_generada, cantidad
            )

            if intento_offer == 0:
                st.markdown(f"**Paso B** — `POST {url_offer}`")
                with st.expander("📋 Ver payload Offer", expanded=False):
                    st.json(payload_oferta)
            else:
                st.warning(f"🔄 Auto-Healing Category: Reintento {intento_offer}/{max_reintentos_offer}...")

            req_offer = hacer_peticion_con_reintento("POST", url_offer, tienda_id, payload_oferta)
            
            if req_offer.status_code in (200, 201):
                offer_id = req_offer.json().get("offerId", "")
                st.success(f"✅ Offer creada — Offer ID: `{offer_id}`")
                break
            
            # Manejo de error de categoría (25005)
            if req_offer.status_code == 400:
                try:
                    errores = req_offer.json().get("errors", [])
                    if any(err.get("errorId") == 25005 for err in errores):
                        with st.spinner("🧠 IA buscando una categoría válida para eBay..."):
                            nueva_cat = interpretar_error_categoria_ia(titulo)
                            if nueva_cat and nueva_cat != str(producto.get("category_id")):
                                st.info(f"🛠️ IA sugiriendo nueva categoría: `{nueva_cat}`. Reintentando...")
                                producto["category_id"] = nueva_cat
                                intento_offer += 1
                                continue
                            else:
                                st.error("❌ La IA no pudo encontrar una categoría alternativa válida.")
                except Exception as ex:
                    st.warning(f"Error en auto-healing de categoría: {ex}")
            
            # Si no es error de categoría o fallaron los reintentos
            st.error(f"❌ Error {req_offer.status_code} al crear oferta.")
            with st.expander("🔍 Detalles del error (Paso B)"):
                st.code(req_offer.text, language="json")
            req_offer.raise_for_status()

        # ── Paso C: PublishOffer (Con Auto-Healing para Aspectos) ──
        url_publish = f"{EBAY_INVENTORY_BASE_URL}/offer/{offer_id}/publish"
        st.markdown(f"**Paso C** — `POST {url_publish}`")

        max_reintentos_publish = 3
        intento_publish = 0
        listing_id = None

        while intento_publish <= max_reintentos_publish and listing_id is None:
            req_publish = hacer_peticion_con_reintento("POST", url_publish, tienda_id, {})

            if req_publish.status_code in (200, 201):
                listing_id = req_publish.json().get("listingId", "N/A")
                break

            # Auto-Healing: Si PublishOffer falla con 25002, parchear el Inventory Item
            if req_publish.status_code == 400:
                try:
                    errores = req_publish.json().get("errors", [])
                    errores_25002 = [err for err in errores if err.get("errorId") == 25002]
                    if errores_25002 and intento_publish < max_reintentos_publish:
                        with st.spinner("🧠 IA interpretando requisitos faltantes (Paso C)..."):
                            dict_ia = interpretar_error_aspectos_ia(req_publish.text, titulo, bullets)
                        
                        if dict_ia:
                            intento_publish += 1
                            aspectos_dict.update(dict_ia)
                            st.warning(f"🔄 Super Intelligence: IA sugiriendo valores para **{', '.join(dict_ia.keys())}**. Parcheando (Intento {intento_publish}/{max_reintentos_publish})...")

                            # Re-construir y re-enviar el Inventory Item con los aspectos nuevos
                            payload_item_fix = construir_payload_inventory_item(producto, descripcion_html_generada, aspectos_dict, cantidad)
                            req_fix = hacer_peticion_con_reintento("PUT", url_item, tienda_id, payload_item_fix)
                            if req_fix.status_code in (200, 201, 204):
                                st.info(f"✅ Inventory Item parcheado con: {', '.join(dict_ia.keys())}")
                                continue
                            else:
                                st.error(f"❌ No se pudo parchear el Inventory Item: {req_fix.text[:200]}")
                                req_publish.raise_for_status()
                        else:
                            st.error("❌ Faltan aspectos pero no se pudieron auto-detectar.")
                except Exception as ex:
                    st.warning(f"Error parseando auto-healing en Paso C: {str(ex)}")
            
            # Si falló y no hubo auto-healing exitoso
            st.error(f"❌ Error {req_publish.status_code} al publicar oferta.")
            with st.expander("🔍 Ver Detalles Técnicos (Paso C)"):
                st.write(f"**URL:** `{url_publish}`")
                st.write(f"**Respuesta de eBay:**")
                st.code(req_publish.text, language="json")
            req_publish.raise_for_status()

        if listing_id is None:
            return False, "❌ No se pudo publicar después de múltiples intentos de auto-healing."

        mensaje_exito = (
            f"✅ **Publicado exitosamente**\n\n"
            f"🎫 **SKU:** `{sku}`\n\n"
            f"📌 **Listing ID:** [`{listing_id}`](https://www.ebay.com/itm/{listing_id})"
        )

        # ── Paso D: Promoted Listings (Opcional) ──
        if promocionar and listing_id != "N/A":
            st.markdown(f"**Paso D** — Promoted Listings Standard (Ad Rate: {ad_rate_pct}%)")
            with st.spinner("📢 Promocionando producto..."):
                campaign_id = buscar_o_crear_campana(tienda_id, ad_rate_pct)
                if campaign_id:
                    exito_ad = agregar_ad_a_campana(tienda_id, campaign_id, listing_id, ad_rate_pct)
                    if exito_ad:
                        st.success(f"📢 Producto promocionado — Ad Rate: {ad_rate_pct}% | Campaña: `{campaign_id}`")
                        mensaje_exito += f"\n\n📢 **Promoted Listings:** Ad Rate {ad_rate_pct}%"
                    else:
                        st.warning("⚠️ Producto publicado exitosamente, pero no se pudo añadir a Promoted Listings.")
                else:
                    st.warning("⚠️ Producto publicado exitosamente, pero no se pudo crear/encontrar la campaña de Promoted Listings.")

        return (True, mensaje_exito)

    except requests.exceptions.HTTPError as e:
        codigo = e.response.status_code
        detalle = e.response.text[:400]
        return False, f"❌ Error HTTP {codigo} en eBay API:\n```\n{detalle}\n```"
    except requests.exceptions.Timeout:
        return False, "❌ Timeout: eBay no respondió a tiempo. Intenta de nuevo."
    except requests.exceptions.ConnectionError:
        return False, "❌ Sin conexión de red hacia eBay."
    except Exception as e:
        return False, f"❌ Error inesperado: {str(e)}"


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
        st.markdown(f"**Category ID:** `{producto['category_id']}`")
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
    
    with st.spinner("Cargando información de tu cuenta de eBay..."):
        politicas_envio = obtener_politicas_ebay(tienda_id, "fulfillment")
        politicas_pago  = obtener_politicas_ebay(tienda_id, "payment")
        politicas_devol = obtener_politicas_ebay(tienda_id, "return")
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

    # ── Botón Principal ──────────────────────────────────
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
