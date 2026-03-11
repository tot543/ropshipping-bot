import sys
import os
import time
import pandas as pd
import streamlit as st
import urllib.parse

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
        ordenes_data = agente.get_orders_response(token, limit=20)

    orders_list = ordenes_data.get("orders", [])
    if not orders_list:
        st.warning("⚠️ No se encontraron órdenes recientes.")
        st.stop()

    st.markdown(f"### 📋 Órdenes Pendientes ({len(orders_list)})")

    for order in orders_list:
        with st.container(border=True):
            col_img, col_info, col_addr = st.columns([1, 2, 2])
            
            # --- Columna 1: Imagen ---
            item_id = "N/A"
            line_items = order.get("lineItems", [])
            img_url = ""
            
            if line_items:
                item_id = line_items[0].get("legacyItemId", "N/A")
                img_url = line_items[0].get("image", {}).get("imageUrl", "")
            
            with col_img:
                if img_url:
                    st.image(img_url, use_container_width=True)
                elif item_id != "N/A":
                    # Fallback URL
                    st.image(f"https://i.ebayimg.com/images/i/{item_id}-0-1/s-l300/p.jpg", use_container_width=True)
                else:
                    st.image("https://via.placeholder.com/300?text=No+Image", use_container_width=True)

            # --- Columna 2: Info y Enlace ---
            with col_info:
                line_item = line_items[0] if line_items else {}
                titulo = line_item.get("title", "Producto sin título")
                total_pagado = order.get("pricingSummary", {}).get("total", {}).get("value", "0.00")
                payout_neto = order.get("paymentSummary", {}).get("totalDueSeller", {}).get("value", "0.00")
                status_pago = order.get("paymentSummary", {}).get("payments", [{}])[0].get("paymentStatus", "N/A")
                buyer_user = order.get("buyer", {}).get("username", "Desconocido")
                
                st.markdown(f"**{titulo}**")
                st.markdown(f"💰 **Total Cobrado:** USD {total_pagado}")
                st.markdown(f"🏦 **Payout (Neto):** :green[USD {payout_neto}] *(Después de fees)*")
                st.markdown(f"💳 **Estado Pago:** `{status_pago}`")
                
                c1, c2 = st.columns(2)
                with c1:
                    titulo_encodeado = urllib.parse.quote(titulo)
                    amazon_url = f"https://www.amazon.com/s?k={titulo_encodeado}"
                    st.link_button("🛒 Buscar en Amazon", url=amazon_url, use_container_width=True)
                with c2:
                    contact_url = f"https://www.ebay.com/cnt/interact?requested={buyer_user}&itemid={item_id}"
                    st.link_button("📧 Contactar Comprador", url=contact_url, use_container_width=True)

            # --- Columna 3: Dirección de Envío ---
            with col_addr:
                shipping_step = order.get("fulfillmentStartInstructions", [{}])[0].get("shippingStep", {})
                ship_to = shipping_step.get("shipTo", {})
                addr = ship_to.get("contactAddress", {})
                
                full_name = ship_to.get("fullName", "Comprador Desconocido")
                line1 = addr.get("addressLine1", "")
                line2 = addr.get("addressLine2", "")
                city = addr.get("city", "")
                state = addr.get("stateOrProvince", "")
                zip_code = addr.get("postalCode", "")
                
                address_text = f"{full_name}\n{line1}\n{line2}\n{city}, {state} {zip_code}".replace("\n\n", "\n").strip()
                
                st.markdown("**📍 Dirección de Envío:**")
                st.code(address_text, language="text")
                
                # --- Gestión de Envío ---
                with st.expander("🚚 Gestionar Envío", expanded=False):
                    track_key = f"track_{order.get('orderId')}"
                    carrier_key = f"carrier_{order.get('orderId')}"
                    
                    tracking_number = st.text_input("Nº Seguimiento:", placeholder="Ej: TBA...", key=track_key)
                    carrier = st.selectbox("Transportista:", ["Amazon Logistics", "USPS", "UPS", "FedEx", "DHL"], key=carrier_key)
                    
                    if st.button("Subir Rastreo", type="primary", key=f"btn_send_{order.get('orderId')}"):
                        if not tracking_number.strip():
                            st.error("Ingresa un número de rastreo.")
                        else:
                            with st.spinner("Subiendo..."):
                                exito, mensaje = agente.upload_tracking(token, order.get('orderId'), tracking_number.strip(), carrier)
                            if exito:
                                st.success("✅ ¡Rastreo Subido!")
                            else:
                                st.error(mensaje)

if __name__ == "__main__":
    main()
