import sys
import os
import time
import pandas as pd
import streamlit as st

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.ebay_auth import get_valid_token, refresh_access_token
from skills.ebay_orders import EbayOrdersAgent

st.set_page_config(page_title="Órdenes y Despachos | eBay Hub", page_icon="📦", layout="wide")

def renderizar_sidebar() -> None:
    with st.sidebar:
        st.title("📦 Despachos")
        st.markdown("---")
        
        if "tienda_activa_id" not in st.session_state:
            st.warning("⚠️ Selecciona una tienda en el Dashboard.")
            st.page_link("app.py", label="Ir al Dashboard")
            st.stop()
            
        t_id = st.session_state.get("tienda_activa_id")
        t_nombre = st.session_state.get("config_tienda", {}).get("nombre", "")
        st.info(f"**Tienda:** {t_nombre}\n**ID:** `{t_id}`")
        if st.button("Forzar Renovación OAuth"):
            refresh_access_token(t_id)
            st.success("Renovado!")
        st.markdown("---")
        st.page_link("pages/3_mensajes.py", label="← Ir a Mensajes")


def main() -> None:
    renderizar_sidebar()

    st.title("📦 Panel Central de Órdenes y Despachos")
    
    tienda_id = st.session_state.get("tienda_activa_id")
    tienda_cfg = st.session_state.get("config_tienda")
    
    if not tienda_id:
        st.error("No hay tienda seleccionada.")
        st.stop()

    st.info(f"🏪 Gestionando despachos de: **{tienda_cfg['nombre']}**")
    st.divider()

    token = get_valid_token(tienda_id)
    agente = EbayOrdersAgent()

    with st.spinner("Conectando con eBay Fulfillment API..."):
        ordenes = agente.get_recent_orders(token, limit=20)

    if not ordenes:
        st.warning("⚠️ La API de eBay no devolvió órdenes recientes o está temporalmente inactiva. Intenta más tarde.")
        st.stop()
        
    # Procesar URLs de origen basadas en SKU
    for orden in ordenes:
        sku = orden.get("SKU", "")
        if sku.startswith("DS-"):
            asin = sku.replace("DS-", "")
            orden["Link de Origen"] = f"https://amazon.com/dp/{asin}"
        else:
            orden["Link de Origen"] = None

    df = pd.DataFrame(ordenes)
    
    st.markdown("### 📋 Órdenes Pendientes")
    
    evento = st.dataframe(
        df, 
        use_container_width=True, 
        hide_index=True,
        on_select="rerun", 
        selection_mode="single-row"
    )

    if len(evento.selection.rows) > 0:
        fila_seleccionada = evento.selection.rows[0]
        orden_seleccionada = df.iloc[fila_seleccionada]
        order_id = orden_seleccionada.get("Order ID", "")
        comprador = orden_seleccionada.get("Comprador", "")
        link_extraido = orden_seleccionada.get("Link de Origen")
        
        st.divider()
        
        if link_extraido:
            st.link_button("🛒 Comprar en Amazon", url=link_extraido)
            
        st.subheader(f"🚚 Formulario de Despacho MANUAL")
        st.markdown(f"**Orden Seleccionada:** `{order_id}` (Comprador: {comprador})")
        
        col1, col2 = st.columns([1, 1])
        
        with col1:
            tracking_number = st.text_input("Número de Rastreo (Tracking Number):", placeholder="Ej: TBA123456789012")
        with col2:
            carrier = st.selectbox("Transportista (Carrier):", ["Amazon Logistics", "USPS", "UPS", "FedEx", "DHL"])

        if st.button("Subir Rastreo a eBay", type="primary"):
            if not tracking_number.strip():
                st.error("Por favor, ingresa un número de rastreo válido.")
            else:
                with st.spinner(f"Subiendo tracking {tracking_number} a eBay..."):
                    exito, mensaje = agente.upload_tracking(token, order_id, tracking_number.strip(), carrier)
                
                if exito:
                    st.success(mensaje)
                else:
                    st.error(mensaje)
    else:
        st.info("👆 Selecciona una orden de la tabla para abrir el panel de Subida de Rastreo.")

if __name__ == "__main__":
    main()
