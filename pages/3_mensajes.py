import streamlit as st
import pandas as pd
import os
import sys

# El root ya debe estar en el path por app.py, pero por seguridad:
if os.getcwd() not in sys.path:
    sys.path.append(os.getcwd())

from utils.ebay_auth import get_valid_token
from skills.ebay_orders import EbayOrdersAgent

st.title("💬 Bandeja de Mensajes (OAuth)")

# Configuración de la tienda activa
tienda_id = st.session_state.get("tienda_activa_id")
tienda_cfg = st.session_state.get("config_tienda")

if not tienda_id:
    st.error("No hay tienda seleccionada.")
    st.stop()

st.info(f"🏪 Viendo órdenes y mensajes de: **{tienda_cfg['nombre']}**")

# Obtener token y llamar al agente
token = get_valid_token(tienda_id)

if not token:
    st.error(f"❌ No se pudo obtener un token válido para **{tienda_id}**. Por favor, verifica la configuración o vuelve a autorizar la tienda.")
    st.stop()

agente = EbayOrdersAgent()

with st.spinner("Conectando con eBay..."):
    # El agente maneja errores y devuelve una lista vacía si falla la API (ej. 503)
    ordenes = agente.get_recent_orders(token)

if ordenes is None:
    # Caso de error crítico en el agente (si decidimos que devuelva None en vez de [])
    st.error("❌ Hubo un error al conectar con la API de eBay.")
elif len(ordenes) == 0:
    st.warning("📭 No tienes órdenes recientes con estado 'Pendiente' o 'En Proceso' en esta tienda.")
    st.info("Nota: Si tienes órdenes pero ya están enviadas, no aparecerán aquí con el filtro actual.")
else:
    # Convertir las órdenes en un DataFrame de Pandas
    df = pd.DataFrame(ordenes)
    
    st.markdown("### 📋 Órdenes Recientes")
    # Generar tabla interactiva
    evento = st.dataframe(
        df, 
        use_container_width=True, 
        hide_index=True,
        on_select="rerun", 
        selection_mode="single-row"
    )

    # Lógica de Interacción al seleccionar una fila
    if len(evento.selection.rows) > 0:
        fila_seleccionada = evento.selection.rows[0]
        orden_seleccionada = df.iloc[fila_seleccionada]
        
        st.divider()
        col1, col2 = st.columns([1, 1])
        
        with col1:
            st.subheader("📦 Detalles del Envío")
            st.write(f"**Order ID:** `{orden_seleccionada.get('Order ID', 'N/A')}`")
            st.write(f"**Comprador:** {orden_seleccionada.get('Comprador', 'N/A')}")
            st.write(f"**Dirección:** {orden_seleccionada.get('Direccion', 'N/A')}")
            
        with col2:
            st.subheader("💬 Nota del Comprador")
            nota = orden_seleccionada.get('Notas del Cliente', 'Sin notas del cliente')
            if nota and nota != "Sin notas del cliente":
                st.info(f"_{nota}_")
            else:
                st.markdown("*El cliente no dejó ninguna nota en esta compra.*")
                
        st.markdown("### ✍️ Responder al Cliente")
        st.text_area("Escribe tu respuesta aquí:", height=100)
        if st.button(f"Enviar Mensaje a {orden_seleccionada.get('Comprador', 'Cliente')}", type="primary"):
            st.success("Esta función se conectará a la API de mensajería en la próxima actualización.")
    else:
        st.info("👆 Selecciona una orden de la tabla para ver los detalles y mensajes.")
