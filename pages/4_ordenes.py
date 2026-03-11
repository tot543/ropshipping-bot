import sys
import os
import urllib.parse
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
        ordenes_data = agente.get_orders_response(token, limit=20)
        
    orders_list = ordenes_data.get("orders", [])
    if not orders_list:
        st.warning("⚠️ No se encontraron órdenes recientes pendientes de envío.")
        st.stop()
        
    st.markdown(f"### 📋 Órdenes Pendientes ({len(orders_list)})")
    
    for order in orders_list:
        with st.container(border=True):
            col_img, col_info, col_addr = st.columns([1, 2, 2])
            
            line_items = order.get("lineItems", [])
            line_item = line_items[0] if line_items else {}
            item_id = line_item.get("legacyItemId", "N/A")
            order_id = order.get("orderId")
            
            # --- COLUMNA 1: IMAGEN ---
            with col_img:
                img_url = line_item.get("image", {}).get("imageUrl")
                if not img_url and item_id != "N/A":
                    img_url = agente.get_item_image_fallback(token, item_id)
                
                if img_url:
                    st.image(img_url, use_container_width=True)
                else:
                    st.info("📦 Imagen no disponible")
                    
            # --- COLUMNA 2: INFO, PAYOUT REAL Y BOTONES ---
            with col_info:
                titulo = line_item.get("title", "Producto sin título")
                
                # Extraer Total Pagado por el cliente desde Fulfillment
                pricing = order.get("pricingSummary", {})
                total_bruto = float(pricing.get("total", {}).get("value", "0.00"))
                
                st.markdown(f"**{titulo[:60]}...**")
                st.markdown(f"💰 **Total Cobrado (Cliente):** USD ${total_bruto:.2f}")
                
                # === OBTENER EL PAYOUT EXACTO USANDO LA API DE FINANZAS ===
                # Llama a la función que me mandaste en tu script `EbayOrdersAgent`
                payout_real = agente.get_order_payout(token, order_id)
                
                if payout_real is not None:
                    # ¡Este es el número exacto que te envía eBay a Payoneer!
                    st.markdown(f"🏦 **Payout Real:** :green[USD ${payout_real:.2f}]")
                    st.caption("*(Validado con Finances API)*")
                else:
                    # Fallback matemático por si el pago está procesándose
                    precio_sin_tax = total_bruto / 1.08
                    costo_fees = (total_bruto * 0.15) + (precio_sin_tax * 0.12) + 0.30
                    payout_estimado = total_bruto - costo_fees
                    st.markdown(f"🏦 **Payout Estimado:** :orange[USD ${payout_estimado:.2f}]")
                    st.caption("*(Aún procesando comisiones en eBay)*")
                
                status_pago = order.get("orderPaymentStatus", "N/A")
                buyer_user = order.get("buyer", {}).get("username", "")
                
                c1, c2 = st.columns(2)
                with c1:
                    titulo_encodeado = urllib.parse.quote(titulo[:40])
                    amazon_url = f"https://www.amazon.com/s?k={titulo_encodeado}"
                    st.link_button("🛒 Buscar en Amazon", url=amazon_url, use_container_width=True)
                with c2:
                    contact_url = f"https://www.ebay.com/usr/{buyer_user}"
                    st.link_button("📧 Contactar Comprador", url=contact_url, use_container_width=True)
                    
            # --- COLUMNA 3: DIRECCIÓN DE ENVÍO ---
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
                
                address_lines = [full_name, line1]
                if line2: address_lines.append(line2)
                address_lines.append(f"{city}, {state} {zip_code}")
                address_text = "\n".join(address_lines)
                
                st.markdown("**📍 Dirección de Envío:**")
                st.code(address_text, language="text")
                
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
