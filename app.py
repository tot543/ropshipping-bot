"""
app.py — Archivo Principal y Dashboard (Fase de Producción OAuth)
==============================================================================
Punto de entrada de la aplicación Streamlit para automatizar dropshipping en eBay.
Gestiona la selección dinámica de tiendas desde secrets.toml y persiste el
ID de la tienda activa en st.session_state para que la capa OAuth auto-renueve los tokens.
"""

import streamlit as st
from datetime import datetime, timedelta
import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from utils.ebay_auth import get_valid_token, refresh_access_token
from skills.ebay_metrics import EbayMetricsAgent
import requests


# ──────────────────────────────────────────────────────────────────────────────
# CONFIGURACIÓN GLOBAL DE LA PÁGINA
# ──────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="eBay Dropshipping Hub",
    page_icon="🛒",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ──────────────────────────────────────────────────────────────────────────────
# FUNCIONES AUXILIARES
# ──────────────────────────────────────────────────────────────────────────────
def cargar_tiendas() -> dict:
    """
    Carga el diccionario de tiendas de forma dinámica desde secrets.toml.
    Returns: dict {tienda_id: diccionario_de_configuracion}
    """
    try:
        return st.secrets["tiendas"]
    except KeyError:
        st.error("❌ No se encontró la sección [tiendas] en secrets.toml")
        st.stop()
        return {}


def inicializar_session_state(tiendas: dict) -> None:
    """Inicializa la sesión con el ID de la primera tienda."""
    if "tienda_activa_id" not in st.session_state:
        primer_id = list(tiendas.keys())[0]
        st.session_state["tienda_activa_id"] = primer_id
        st.session_state["config_tienda"] = tiendas[primer_id]

    if "producto_aprobado" not in st.session_state:
        st.session_state["producto_aprobado"] = None


def renderizar_sidebar(tiendas: dict) -> None:
    """Renderiza la barra lateral con el selector dinámico de tiendas."""
    with st.sidebar:
        st.image("https://upload.wikimedia.org/wikipedia/commons/1/1b/EBay_logo.svg", width=120)
        st.title("🛒 eBay Hub")
        st.markdown("---")

        st.subheader("🏪 Tienda Activa")
        
        # Mapeo de nombre visual a ID de tienda
        mapa_nombres = {cfg["nombre"]: t_id for t_id, cfg in tiendas.items()}
        nombres_opciones = list(mapa_nombres.keys())
        
        # Obtener el nombre de la tienda actual
        id_actual = st.session_state["tienda_activa_id"]
        nombre_actual = tiendas[id_actual]["nombre"]

        nombre_seleccionado = st.selectbox(
            label="Selecciona una tienda:",
            options=nombres_opciones,
            index=nombres_opciones.index(nombre_actual),
            key="selector_tienda",
            help="El sistema usará el token OAuth (y lo renovará) para esta tienda.",
        )

        id_seleccionado = mapa_nombres[nombre_seleccionado]

        # Si el usuario cambia de tienda en el UI
        if id_seleccionado != st.session_state["tienda_activa_id"]:
            st.session_state["tienda_activa_id"] = id_seleccionado
            st.session_state["config_tienda"] = tiendas[id_seleccionado]
            st.session_state["producto_aprobado"] = None 
            st.rerun()

        # Validación visual del token OAuth
        token_valido = get_valid_token(id_seleccionado)
        if token_valido:
            token_preview = token_valido[:20] + "..." if token_valido else "Token Invalido"
            st.success(f"✅ Token OAuth validado:\n`{token_preview}`")
        else:
            st.error("❌ Token Inválido o Tienda no Conectada")
            from utils.ebay_auth import get_auth_url
            url_auth = get_auth_url()
            if url_auth:
                st.sidebar.link_button("🔐 Conectar cuenta de eBay", url_auth)
                st.sidebar.info("Por favor, conecta tu cuenta de eBay para usar la aplicación. Luego pásale el código de la URL a tu administrador.")

        st.markdown("---")
        st.subheader("📌 Módulos")
        st.page_link("app.py",                    label="🏠 Dashboard",            icon="🏠")
        st.page_link("pages/1_cazador.py",         label="🎯 Cazador & Calculadora", icon="🎯")
        st.page_link("pages/2_publicador.py",      label="🚀 Publicador Automático", icon="🚀")
        st.page_link("pages/3_mensajes.py",        label="💬 Bandeja de Mensajes",   icon="💬")
        st.page_link("pages/4_ordenes.py",         label="📦 Despachos",            icon="📦")
        st.markdown("---")
        st.caption(f"🕐 Sesión: {datetime.now().strftime('%H:%M:%S')}")


@st.cache_data(show_spinner=False, ttl=300)
def obtener_metricas_dashboard(tienda_id: str) -> dict:
    """Extrae métricas reales (Órdenes Activas y Ganancia/Ventas) usando EbayMetricsAgent."""
    try:
        token = get_valid_token(tienda_id)
        agente = EbayMetricsAgent()
        return agente.get_weekly_stats(token)
    except Exception as e:
        return {"ordenes": 0, "ventas": 0.0, "error": str(e)}


# ──────────────────────────────────────────────────────────────────────────────
# DASHBOARD
# ──────────────────────────────────────────────────────────────────────────────
def renderizar_dashboard(tiendas: dict) -> None:
    tienda_cfg = st.session_state["config_tienda"]

    col_titulo, col_tienda = st.columns([3, 1])
    with col_titulo:
        st.title("🛒 eBay Dropshipping Hub")
        st.markdown("Plataforma Multi-Tenant protegida por OAuth. Cada tienda gestiona sus propios Refresh Tokens automáticamente.")
    with col_tienda:
        st.metric("Tienda Activa", tienda_cfg["nombre"], delta="OAuth 2.0 ✅")

    st.divider()
    st.subheader("📊 Resumen de Hoy (Real-Time)")
    
    # Extraemos el ID de la tienda (no el nombre) para el token OAuth
    metricas = obtener_metricas_dashboard(st.session_state["tienda_activa_id"])
    
    k1, k2, k3, k4 = st.columns(4)
    if metricas.get("error"):
        st.error(f"Error al cargar métricas: {metricas['error'][:100]}")
        k1.metric("Órdenes (7 días)", "Err")
        k2.metric("Bruto (7 días)", "Err")
    else:
        k1.metric("Órdenes (últimos 7 días)", str(metricas.get("ordenes", 0)), "Actualizado")
        k2.metric("Ventas (últimos 7 días)", f"${metricas.get('ventas', 0.00):,.2f}")
        
    k3.metric("Mensajes Pendientes", "API", "-")
    k4.metric("Listings Activos", "API", "-")

    st.divider()
    st.subheader("🏪 Bóveda de Tiendas (secrets.toml)")
    
    # Tabla censurando tokens sensibles
    datos_tiendas = []
    for t_id, cfg in tiendas.items():
        o_token = cfg.get('oauth_token', '')
        r_token = cfg.get('refresh_token', '')
        datos_tiendas.append({
            "Tienda ID": t_id,
            "Nombre": cfg["nombre"],
            "Site Mode": cfg.get("site_id", "EBAY_US"),
            "OAuth Token": f"{o_token[:8]}...{o_token[-4:]}" if len(o_token) > 12 else "Vacío",
            "Refresh Configurado": "✅" if len(r_token) > 10 else "❌"
        })
        
    st.dataframe(datos_tiendas, use_container_width=True)

    st.info("📌 **Configuración de Llaves**: Pega tus tokens reales de eBay en el archivo `.streamlit/secrets.toml`. "
            "El archivo ya fue agregado a `.gitignore` para máxima seguridad.")


def main() -> None:
    # === TEMPORARY OAUTH EXCHANGE SNIPPET ===
    if "code" in st.query_params:
        import urllib.parse
        import requests
        import base64
        
        auth_code = st.query_params["code"]
        
        app_id = st.secrets["ebay"]["app_id"]
        cert_id = st.secrets["ebay"]["cert_id"]
        runame = st.secrets["ebay"]["runame"]
        
        auth_str = f"{app_id}:{cert_id}"
        b64_auth = base64.b64encode(auth_str.encode("utf-8")).decode("utf-8")
        
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {b64_auth}"
        }
        
        payload = {
            "grant_type": "authorization_code",
            "code": auth_code,
            "redirect_uri": runame
        }
        
        st.warning("🔄 Intercambiando código por tokens (esto ocurre en el servidor de Streamlit para evadir el bloqueo 503 local)...")
        try:
            resp = requests.post("https://api.ebay.com/identity/v1/oauth2/token", headers=headers, data=payload)
            if resp.status_code == 200:
                st.success("✅ ¡ÉXITO! Copia estos tokens y pégalos en secrets.toml (sección tienda_chica_1):")
                st.json(resp.json())
            else:
                st.error(f"❌ Error HTTP {resp.status_code}")
                try:
                    st.json(resp.json())
                except:
                    st.write(resp.text)
        except Exception as e:
            st.error(f"Excepción en el servidor: {str(e)}")
            
        st.info("⚠️ Una vez copiados, borra todo lo que sigue al '?' en la URL (incluido el 'code=') para volver al Dashboard normal.")
        st.stop() # Detenemos el renderizado del dashboard para no sobrecargar
    # ========================================

    tiendas = cargar_tiendas()
    inicializar_session_state(tiendas)
    renderizar_sidebar(tiendas)
    renderizar_dashboard(tiendas)

if __name__ == "__main__":
    main()
