import requests
import streamlit as st

class EbayOrdersAgent:
    """
    Agente especializado en extraer Órdenes de la API de Fulfillment de eBay.
    Diseñado con tolerancia a fallos extrema (Zero-Trust al JSON devuelto).
    """

    def __init__(self):
        self.base_url = "https://api.ebay.com/sell/fulfillment/v1/order"

    def get_recent_orders(self, token: str, limit: int = 10) -> list[dict]:
        if not token:
            return []
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        try:
            url = f"{self.base_url}?limit={limit}&filter=orderfulfillmentstatus:{{NOT_STARTED|IN_PROGRESS}}"
            resp = requests.get(url, headers=headers, timeout=10)
            resp.raise_for_status()
            datos = resp.json()
            ordenes_procesadas = []
            
            for orden in datos.get("orders", []):
                fecha_cruda = orden.get("creationDate", "")
                fecha = fecha_cruda[:10] if fecha_cruda else ""
                comprador = orden.get("buyer", {}).get("username", "Comprador Desconocido")
                estado_pago = orden.get("paymentSummary", {}).get("totalDueSeller", {}).get("value", "Pagado")
                if str(estado_pago) == "0.0":
                    estado_pago = "Pagado"
                notas = orden.get("buyerCheckoutNotes", "") or "Sin notas del cliente."
                shipping_instructions = orden.get("fulfillmentStartInstructions", [])
                shipping = {}
                if shipping_instructions and isinstance(shipping_instructions, list):
                    shipping = shipping_instructions[0].get("shippingStep", {}).get("shipTo", {})
                contact = shipping.get("contactAddress", {}) if isinstance(shipping, dict) else {}
                full_name = shipping.get("fullName", "") if isinstance(shipping, dict) else ""
                sku = "Sin SKU"
                line_items = orden.get("lineItems", [])
                if line_items and isinstance(line_items, list) and len(line_items) > 0:
                    sku = line_items[0].get("sku", "Sin SKU")
                addr1 = contact.get("addressLine1", "") if isinstance(contact, dict) else ""
                city = contact.get("city", "") if isinstance(contact, dict) else ""
                direccion = f"{full_name}, {addr1}, {city}".strip(", ")
                if not direccion or direccion == ",":
                    direccion = "Dirección no disponible"
                ordenes_procesadas.append({
                    "Order ID":         orden.get("orderId", "Sin ID"),
                    "Fecha":            fecha,
                    "Comprador":        comprador,
                    "Estado del Pago":  f"USD {estado_pago}" if estado_pago != "Pagado" else "Pagado ✅",
                    "Notas del Cliente": notas,
                    "Direccion":        direccion,
                    "SKU":              sku
                })
            return ordenes_procesadas

        except Exception as e:
            st.error(f"❌ Error al cargar órdenes de eBay: {str(e)}")
            if 'resp' in locals():
                with st.expander("Detalles del Error"):
                    st.code(resp.text)
            return None

    def get_orders_response(self, token: str, limit: int = 10) -> dict:
        if not token:
            return {}
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json"
        }
        try:
            url = f"{self.base_url}?limit={limit}&filter=orderfulfillmentstatus:{{NOT_STARTED|IN_PROGRESS}}&fieldGroups=TAX_BREAKDOWN"
            resp = requests.get(url, headers=headers, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            st.error(f"Error cargando órdenes: {e}")
            return {}

    def send_buyer_message(self, token: str, order_id: str, message_text: str) -> tuple[bool, str]:
        if not token or not order_id or not message_text:
            return False, "Faltan datos para enviar el mensaje."
        return True, "Mensaje enviado (Simulado vía API)"

    # ============================================================
    # FUNCIÓN CORREGIDA: Suma TODAS las transacciones del pedido
    # SALE (+) + FEE (-) + TAX (-) = Payout Neto Real
    # ============================================================
    def get_order_payout(self, token: str, order_id: str) -> float | None:
        if not token or not order_id:
            return None

        url = f"https://api.ebay.com/sell/finances/v1/transaction?filter=orderId:{{{order_id}}}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json"
        }

        try:
            resp = requests.get(url, headers=headers, timeout=10)

            if resp.status_code != 200:
                return None

            data = resp.json()
            transacciones = data.get("transactions", [])

            if not transacciones:
                return None

            # LA CLAVE: Sumar TODAS las transacciones del pedido.
            # eBay devuelve la VENTA en positivo (+$25.15)
            # y los FEES y TAXES en negativo (-$4.21, -$2.77, -$1.65)
            # La suma de todos da exactamente el Payout Real = $16.52
            total_neto = 0.0
            for trans in transacciones:
                valor = trans.get("amount", {}).get("value")
                if valor is not None:
                    total_neto += float(valor)

            return round(total_neto, 2)

        except Exception:
            return None

    def get_item_image_fallback(self, token: str, legacy_item_id: str) -> str | None:
        if not token or not legacy_item_id:
            return None
        url = f"https://api.ebay.com/buy/browse/v1/item/get_item_by_legacy_id?legacy_item_id={legacy_item_id}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json"
        }
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                return data.get("image", {}).get("imageUrl")
            return None
        except Exception:
            return None

    def upload_tracking(self, token: str, order_id: str, tracking_number: str, carrier: str) -> tuple[bool, str]:
        if not token or not order_id or not tracking_number or not carrier:
            return False, "Faltan datos obligatorios para subir el rastreo."
        url = f"https://api.ebay.com/sell/fulfillment/v1/order/{order_id}/shipping_fulfillment"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        payload = {
            "trackingNumber": tracking_number,
            "shippingCarrierCode": carrier
        }
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=10)
            resp.raise_for_status()
            return True, f"Rastreo {tracking_number} subido exitosamente."
        except Exception as e:
            err_msg = f"Fallo al subir rastreo: {str(e)}"
            if hasattr(e, 'response') and e.response is not None:
                err_msg += f". Respuesta: {e.response.text}"
            return False, err_msg
