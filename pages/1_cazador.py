"""
pages/1_cazador.py — Cazador de Productos (Producción)
==============================================================================
FASE PRODUCCIÓN: Sin datos simulados. Toda la información proviene de APIs reales:
  - eBay Browse API (OAuth) → título, precio, categoryId
  - ScraperAPI + BeautifulSoup → precio Amazon, imágenes, bullets, descripción

Configuración requerida en .streamlit/secrets.toml:
  [ebay] app_id, cert_id, runame
  [tiendas.<id>] oauth_token, refresh_token
  [amazon] scraper_api_key
"""

import sys
import os
import re
import requests
import streamlit as st
from bs4 import BeautifulSoup

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.ebay_auth import get_valid_token, refresh_access_token

st.set_page_config(page_title="Cazador | eBay Hub", page_icon="🎯", layout="wide")

UMBRAL_GANANCIA_MIN = 0.01  # Umbral mínimo de aprobación


# ─────────────────────────────────────────────────────────
# EXTRACCIÓN eBay BROWSE API (PRODUCCIÓN)
# ─────────────────────────────────────────────────────────

def extraer_datos_ebay(item_id: str, tienda_id: str) -> dict:
    """
    Llama a la eBay Browse API con token OAuth válido.
    Lanza Exception en caso de error. Nunca retorna datos inventados.
    """
    token = get_valid_token(tienda_id)
    url = f"https://api.ebay.com/buy/browse/v1/item/get_item_by_legacy_id?legacy_item_id={item_id}"

    headers = {
        "Authorization":           f"Bearer {token}",
        "Content-Type":            "application/json",
        "X-EBAY-C-MARKETPLACE-ID": st.secrets.get("ebay_api", {}).get("marketplace_id", "EBAY_US"),
    }

    try:
        respuesta = requests.get(url, headers=headers, timeout=15)

        # Auto-renovación en 401
        if respuesta.status_code == 401:
            st.warning("🔄 Token expirado, renovando con Refresh Token...")
            token = refresh_access_token(tienda_id)
            headers["Authorization"] = f"Bearer {token}"
            respuesta = requests.get(url, headers=headers, timeout=15)

        respuesta.raise_for_status()
        datos = respuesta.json()
        
    except requests.exceptions.HTTPError as e:
        # Fallback si el Item es un Grupo (variaciones)
        if e.response.status_code == 400 and "get_items_by_item_group" in e.response.text:
            st.info(f"📌 El artículo {item_id} tiene variaciones. Obteniendo el ítem principal del grupo...")
            
            url_grupo = f"https://api.ebay.com/buy/browse/v1/item/get_items_by_item_group?item_group_id={item_id}"
            resp_grupo = requests.get(url_grupo, headers=headers, timeout=15)
            resp_grupo.raise_for_status()
            
            datos_grupo = resp_grupo.json()
            items = datos_grupo.get("items", [])
            
            if not items:
                raise ValueError(f"El grupo de variaciones para {item_id} está vacío.")
                
            # Tomamos el primer ítem de la variación como base
            datos = items[0]
        else:
            raise e

    titulo       = datos.get("title", "").strip()
    category_path = datos.get("categoryPath", "")
    category_id  = datos.get("categoryId", "")
    
    # Si categoryId está vacío o no es puramente numérico, intentamos extraer del path
    if not category_id or not str(category_id).isdigit():
        if "|" in category_path:
            raw_id = category_path.split("|")[-1].strip()
            # Extraer solo dígitos por si viene con nombre
            id_match = re.search(r"(\d+)", raw_id)
            category_id = id_match.group(1) if id_match else raw_id
        else:
            category_id = category_path

    # Limpieza final: asegurarnos de que sea solo el número
    if isinstance(category_id, str):
        id_match = re.search(r"(\d+)", category_id)
        if id_match:
            category_id = id_match.group(1)

    precio_str   = datos.get("price", {}).get("value", "0")
    precio       = float(precio_str)

    if not titulo:
        raise ValueError(f"eBay no devolvió un título para el Item ID {item_id}")
    if precio <= 0:
        raise ValueError(f"eBay devolvió un precio de $0 para el Item ID {item_id}")

    return {
        "titulo":      titulo,
        "precio_ebay": precio,
        "category_id": category_id,
    }


# ─────────────────────────────────────────────────────────
# EXTRACCIÓN AMAZON — ScraperAPI + BeautifulSoup (PRODUCCIÓN)
# ─────────────────────────────────────────────────────────

def extraer_datos_amazon(amazon_url: str, tienda_id: str = None) -> dict:
    """
    Usa ScraperAPI con autoparse='true' para obtener datos estructurados JSON.
    Busca la API Key en:
    1. st.secrets["tiendas"][tienda_id]["scraper_api_key"] (si existe)
    2. st.secrets["amazon"]["scraper_api_key"] (fallback global)
    """
    api_key = None
    
    # 1. Intentar buscar en la tienda específica
    if tienda_id:
        tienda_cfg = st.secrets.get("tiendas", {}).get(tienda_id, {})
        api_key = tienda_cfg.get("scraper_api_key")

    # 2. Intentar buscar en el bloque global [amazon] si no se encontró
    if not api_key:
        api_key = st.secrets.get("amazon", {}).get("scraper_api_key")

    if not api_key or api_key in ("TU_SCRAPERAPI_KEY_AQUI", "", "AMAZON_ACCESS_KEY_HERE"):
        raise ValueError(
            "❌ No se encontró 'scraper_api_key'. \n"
            "Asegúrate de tenerlo en [amazon] o dentro de tu tienda en secrets.toml."
        )

    scraper_url = "http://api.scraperapi.com"
    params = {
        "api_key":   api_key,
        "url":       amazon_url,
        "autoparse": "true",
    }

    respuesta = requests.get(scraper_url, params=params, timeout=45)
    respuesta.raise_for_status()

    # Como usamos autoparse='true', la respuesta debe ser un JSON
    try:
        data = respuesta.json()
    except Exception as e:
        raise ValueError(f"La respuesta de ScraperAPI no es un JSON válido (verifique su consumo/créditos o la URL): {str(e)}")

    # ── Precio ──────────────────────────────────────────
    precio = 0.0
    precio_str = data.get("pricing", "")
    if precio_str:
        try:
            # Eliminar símbolos de divisa y comas
            precio_limpio = precio_str.replace('$', '').replace(',', '').strip()
            precio = float(re.search(r"[\d.]+", precio_limpio).group())
        except (AttributeError, ValueError):
            pass

    if precio <= 0:
        raise ValueError(
            "No se encontró el precio en la respuesta JSON estructurada de Amazon. "
            "Es posible que el producto esté agotado o no tenga precio visible."
        )

    # ── Imágenes ─────────────────────────────────────────
    imagenes = data.get("images", [])
    if not isinstance(imagenes, list):
        imagenes = [str(imagenes)] if imagenes else []

    # ── Bullets (Feature List) ────────────────────────────
    bullets = data.get("feature_bullets", [])
    if not isinstance(bullets, list):
        bullets = [str(bullets)] if bullets else []

    # ── Top Reviews ───────────────────────────────────────
    reviews = []
    reviews_data = data.get("reviews", [])
    if isinstance(reviews_data, list):
        for rv in reviews_data:
            if isinstance(rv, str):
                reviews.append(rv)
            elif isinstance(rv, dict) and "body" in rv:
                reviews.append(rv["body"])

    # La descripción a veces la traen como product_description o description
    descripcion = data.get("product_description") or data.get("description") or ""
    if isinstance(descripcion, list):
        descripcion = " ".join(descripcion)

    return {
        "precio":      precio,
        "imagenes":    imagenes,
        "bullets":     bullets,
        "descripcion": descripcion,
        "reviews":     reviews,
    }


# ─────────────────────────────────────────────────────────
# CALCULADORA DE RENTABILIDAD
# ─────────────────────────────────────────────────────────

def calcular_rentabilidad(
    precio_final_venta: float, 
    costo_amazon_base: float,
    tax_proveedor_pct: float = 8.0,
    tax_comprador_pct: float = 8.0,
    mi_ad_rate_pct: float = 12.0,
) -> dict:
    """
    Fórmula desglosada basada en el Precio Final de Venta dictado por el usuario.
    - Costo Real Compra: Lo que pagas en Amazon (Precio Lista + Sales Tax Estimado).
    - Fees de eBay Base: 15% sobre el total que paga el comprador (Precio Venta + Taxes eBay).
    - Tarifa Fija: $0.30.
    """
    tarifa_fija = 0.30
    
    # 1. Desglose de Costos de Adquisición
    costo_real_compra = costo_amazon_base * (1 + (tax_proveedor_pct / 100))
    
    # 2. Desglose de Gastos de Venta (eBay)
    precio_con_tax_ebay = precio_final_venta * (1 + (tax_comprador_pct / 100))
    fees_ebay_base      = precio_con_tax_ebay * 0.15
    costo_promoted      = precio_final_venta * (mi_ad_rate_pct / 100)
    descuento_total     = fees_ebay_base + costo_promoted + tarifa_fija

    # 3. Ganancia y ROI
    ganancia_neta = precio_final_venta - costo_real_compra - descuento_total
    # Margen/ROI calculado sobre el costo real de inversión (Costo Proveedor + Tax)
    margen_pct    = (ganancia_neta / costo_real_compra * 100) if costo_real_compra > 0 else 0

    return {
        "precio_sugerido":   precio_final_venta, # Mantenemos key para el publicador
        "costo_amazon":      round(costo_real_compra, 2), # Ahora incluye tax
        "tax_amazon_dolares": round(costo_real_compra - costo_amazon_base, 2),
        "fees_ebay_base":    round(fees_ebay_base, 2),
        "costo_promoted":    round(costo_promoted, 2),
        "tarifa_fija":       tarifa_fija,
        "descuento_total":   round(descuento_total, 2),
        "ganancia_neta":     round(ganancia_neta, 2),
        "margen_pct":        round(margen_pct, 1),
        "aprobado":          ganancia_neta > UMBRAL_GANANCIA_MIN,
    }


# ─────────────────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────────────────

def renderizar_sidebar() -> None:
    with st.sidebar:
        st.title("🎯 Cazador")
        st.markdown("---")

        if "tienda_activa_id" not in st.session_state:
            st.warning("⚠️ Selecciona una tienda en el Dashboard.")
            st.page_link("app.py", label="Ir al Dashboard")
            st.stop()

        tienda_id = st.session_state["tienda_activa_id"]
        nombre    = st.session_state.get("config_tienda", {}).get("nombre", "")
        st.info(f"**Usuario:** {nombre}\n\n**ID:** `{tienda_id}`")

        if st.button("🔄 Forzar Renovación OAuth"):
            with st.spinner("Renovando..."):
                refresh_access_token(tienda_id)
            st.success("¡Token renovado!")

        st.markdown("---")
        st.page_link("app.py",               label="← Dashboard")
        st.page_link("pages/2_publicador.py", label="→ Publicador")


# ─────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────

def main() -> None:
    renderizar_sidebar()
    st.title("🎯 Cazador de Productos — Producción")

    if "tienda_activa_id" not in st.session_state:
        st.warning("⚠️ No hay tienda activa. Regresa al Dashboard.")
        st.stop()

    tienda_id = st.session_state["tienda_activa_id"]
    nombre    = st.session_state["config_tienda"]["nombre"]

    st.info(f"🔌 Conectado a **eBay Browse API** (OAuth) | Tienda: **{nombre}**")
    st.divider()

    # ── Inicialización de variables de sesión para persistencia -----
    if "datos_ebay_crudos" not in st.session_state:
        st.session_state["datos_ebay_crudos"] = None
    if "datos_amazon_crudos" not in st.session_state:
        st.session_state["datos_amazon_crudos"] = None
    if "item_id_cazado" not in st.session_state:
        st.session_state["item_id_cazado"] = None
    if "amazon_url_cazada" not in st.session_state:
        st.session_state["amazon_url_cazada"] = None

    # ── Inputs del usuario ───────────────────────────────
    col_ebay, col_amazon = st.columns(2)
    with col_ebay:
        item_id = st.text_input(
            "📌 Item ID de eBay",
            placeholder="Ej: 336361278746",
            help="El número que aparece en la URL de eBay: ebay.com/itm/XXXXXXXXXX"
        )
    with col_amazon:
        amazon_url = st.text_input(
            "🛒 URL del Producto en Amazon (fuente de sourcing)",
            placeholder="Ej: https://www.amazon.com/dp/B09XXXXXX",
            help="URL completa del producto Amazon equivalente que usarás como proveedor."
        )

    st.subheader("⚙️ Opciones de Calculadora")
    col_c1, col_c2, col_c3 = st.columns(3)
    with col_c1:
        tax_proveedor_pct = st.number_input("💸 Tax pagado a Amazon (%)", value=8.0, step=0.5, help="Estimación del Sales Tax que tú pagas al comprar en Amazon.")
    with col_c2:
        tax_comprador_pct = st.number_input("💸 Tax del cliente eBay (%)", value=8.0, step=0.5, help="Estimación del Sales Tax que eBay cobra al cliente (afecta fees).")
    with col_c3:
        mi_ad_rate_pct    = st.number_input("📈 Promoted Listings (%)", value=12.0, step=0.5, help="Tarifa pagada en anuncios de eBay para esta publicación.")

        st.markdown("<br>", unsafe_allow_html=True) # Espaciador
        competidor_sin_ads = st.checkbox(
            "⚠️ El competidor NO usa Ads (Inflar precio de venta)", 
            value=False,
            help="Activa esto si copiaste la URL de forma orgánica. Inflará tu precio sugerido para que la venta absorba tu Ad Rate automáticamente sin perder tu margen en dólares."
        )

    st.markdown("<br>", unsafe_allow_html=True)
    boton_extraer = st.button("🚀 Extraer Datos y Calcular Rentabilidad", type="primary")

    if boton_extraer:
        if not item_id.strip():
            st.error("❌ Ingresa un Item ID de eBay válido.")
            st.stop()
        if not amazon_url.strip():
            st.error("❌ Ingresa la URL del producto de Amazon.")
            st.stop()

        # Limpiamos sesión anterior al intentar uno nuevo
        st.session_state["datos_ebay_crudos"] = None
        st.session_state["datos_amazon_crudos"] = None

        # ── 1. Extraer datos de eBay ─────────────────────
        producto_ebay_temp = None
        with st.spinner("🔍 Consultando eBay Browse API..."):
            try:
                producto_ebay_temp = extraer_datos_ebay(item_id.strip(), tienda_id)
            except requests.exceptions.HTTPError as e:
                cod = e.response.status_code
                if cod == 404:
                    st.error(f"❌ El Item ID `{item_id}` no existe en eBay.")
                else:
                    st.error(f"❌ Error eBay API ({cod}): {e.response.text[:300]}")
            except Exception as e:
                st.error(f"❌ Error al consultar eBay: {str(e)}")

        if not producto_ebay_temp:
            st.stop()

        # ── 2. Extraer datos de Amazon ───────────────────
        datos_amazon_temp = None
        with st.spinner("🛒 Scrapeando Amazon con ScraperAPI..."):
            try:
                datos_amazon_temp = extraer_datos_amazon(amazon_url.strip(), tienda_id)
            except ValueError as e:
                st.error(str(e))
            except requests.exceptions.Timeout:
                st.error("❌ ScraperAPI no respondió a tiempo (timeout 45s). Intenta de nuevo.")
            except requests.exceptions.HTTPError as e:
                st.error(f"❌ Error ScraperAPI ({e.response.status_code}): {e.response.text[:200]}")
            except Exception as e:
                st.error(f"❌ Error al scrape Amazon: {str(e)}")

        if not datos_amazon_temp:
            st.stop()

        # Guardamos en sesión todo el lote extraído
        st.session_state["datos_ebay_crudos"] = producto_ebay_temp
        st.session_state["datos_amazon_crudos"] = datos_amazon_temp
        st.session_state["item_id_cazado"] = item_id.strip()
        st.session_state["amazon_url_cazada"] = amazon_url.strip()


    # ── Renderizado Persistente (No depende del botón) ──────────
    if st.session_state.get("datos_ebay_crudos") and st.session_state.get("datos_amazon_crudos"):
        producto_ebay = st.session_state["datos_ebay_crudos"]
        datos_amazon = st.session_state["datos_amazon_crudos"]
        costo_amazon = datos_amazon["precio"]
        item_id_actual = st.session_state["item_id_cazado"]
        amazon_url_actual = st.session_state["amazon_url_cazada"]

        st.success(f"✅ eBay: **{producto_ebay['titulo']}** — ${producto_ebay['precio_ebay']:.2f}")
        st.success(f"✅ Amazon: Precio encontrado — **${costo_amazon:.2f}**")

        # ── 3. Calcular Precio Base/Automático ─────────────────────
        if competidor_sin_ads:
            precio_automatico = (producto_ebay["precio_ebay"] - 0.05) / (1 - (mi_ad_rate_pct / 100))
        else:
            precio_automatico = producto_ebay["precio_ebay"] - 0.05
        precio_automatico = round(precio_automatico, 2)

        st.divider()
        st.subheader("💵 Ajuste Manual de Precio")
        precio_final_venta = st.number_input(
            "Tu Precio Final de Venta (Override Manual)",
            value=precio_automatico,
            step=0.50,
            help="Modifica este valor para establecer tu propio precio. Todo el desglose inferior se recalculará automáticamente basado en este número."
        )

        # ── 4. Calcular Rentabilidad ──────────────────────────────
        calc = calcular_rentabilidad(
            precio_final_venta=precio_final_venta, 
            costo_amazon_base=costo_amazon,
            tax_proveedor_pct=tax_proveedor_pct,
            tax_comprador_pct=tax_comprador_pct,
            mi_ad_rate_pct=mi_ad_rate_pct
        )

        st.divider()

        # ── Panel de datos eBay ─────────────────────────
        st.subheader("📦 Origen: Artículo Competidor en eBay")
        eb1, eb2, eb3 = st.columns([4, 1, 1])
        eb1.markdown(f"**Título:** {producto_ebay['titulo']}")
        eb2.metric("Precio Competidor", f"${producto_ebay['precio_ebay']:.2f}")
        eb3.metric("Category ID", producto_ebay["category_id"])

        # ── Panel de datos Amazon ────────────────────────
        st.subheader("🛒 Fuente: Producto Amazon (ScraperAPI)")
        am1, am2 = st.columns([3, 1])
        am1.markdown(f"🔗 [Ver en Amazon]({amazon_url_actual})")
        am2.metric(
            "Costo Inicial (Sin Tax)", 
            f"${costo_amazon:.2f}",
            delta=f"Costo con Tax: ${calc['costo_amazon']:.2f}",
            delta_color="off"
        )

        with st.expander("🖼️ Imágenes extraídas de Amazon", expanded=False):
            imgs = datos_amazon.get("imagenes", [])
            if imgs:
                cols = st.columns(min(len(imgs), 4))
                for i, img_url in enumerate(imgs):
                    cols[i % 4].image(img_url, use_container_width=True)
            else:
                st.warning("No se encontraron imágenes en la página. Amazon puede haberlas cargado dinámicamente.")

        with st.expander("📝 Descripción y Bullets (Amazon)", expanded=False):
            bullets = datos_amazon.get("bullets", [])
            if bullets:
                st.markdown("**Características:**")
                for b in bullets:
                    st.markdown(f"- {b}")
            else:
                st.info("No se encontraron bullets en la página.")
            desc = datos_amazon.get("descripcion", "")
            if desc:
                st.markdown("**Descripción Principal:**")
                st.info(desc)

        # ── Calculadora ───────────────────────────────────
        st.divider()
        st.subheader("💰 Calculadora Financiera Desglosada")
        
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("🏷️ Tu Precio de Venta", f"${calc['precio_sugerido']:.2f}",
                  delta="Override Manual" if round(calc['precio_sugerido'], 2) != round(precio_automatico, 2) else "Calculado auto",
                  delta_color="normal")
        m2.metric("🛒 Costo Amazon",      f"-${calc['costo_amazon']:.2f}", delta_color="off")
        m3.metric("🏦 eBay Base (15%+Tax)", f"-${calc['fees_ebay_base']:.2f}", delta_color="off")
        m4.metric("📢 Promoted Ads",        f"-${calc['costo_promoted']:.2f}", delta_color="off")
        m5.metric("💵 Ganancia Neta",       f"${calc['ganancia_neta']:.2f}",
                  delta=f"ROI: {calc['margen_pct']}%", delta_color="normal")

        # ── Resultado y guardado ──────────────────────────
        if calc["aprobado"]:
            st.success(
                f"✅ **PRODUCTO APROBADO** — Ganancia Neta: **${calc['ganancia_neta']:.2f}** | "
                f"🏷️ Precio de Venta Sugerido: **${calc['precio_sugerido']:.2f}**"
            )
            st.session_state["producto_aprobado"] = {
                # Datos eBay
                "item_id":      item_id_actual,
                "titulo":       producto_ebay["titulo"],
                "precio_ebay":  producto_ebay["precio_ebay"],
                "precio_sugerido": calc["precio_sugerido"],
                "category_id":  producto_ebay["category_id"],
                # Datos Amazon (Costo Real con Tax)
                "costo_amazon":       calc["costo_amazon"],
                "imagenes_amazon":    datos_amazon.get("imagenes", []),
                "bullets_amazon":     datos_amazon.get("bullets", []),
                "descripcion_amazon": datos_amazon.get("descripcion", ""),
                # Financieros
                "ganancia_neta":  calc["ganancia_neta"],
                "margen_pct":     calc["margen_pct"],
                # Metadata
                "tienda_origen":  tienda_id,
            }
            st.info("📌 Paquete completo guardado en memoria. Ve al **Publicador** para subir a eBay.")
            st.page_link("pages/2_publicador.py", label="→ Ir al Publicador ahora")
        else:
            st.error(
                f"❌ **PRODUCTO RECHAZADO** — Ganancia: **${calc['ganancia_neta']:.2f}** "
                f"(mínimo requerido: ${UMBRAL_GANANCIA_MIN:.2f})"
            )
            st.session_state["producto_aprobado"] = None


if __name__ == "__main__":
    main()
