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
        """
        Obtiene las órdenes más recientes.
        Siempre retorna una lista segura de diccionarios con las llaves procesadas.
        """
        if not token:
            return []

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

        try:
            resp = requests.get(f"{self.base_url}?limit={limit}", headers=headers, timeout=10)
            
            resp.raise_for_status()

            datos = resp.json()
            ordenes_procesadas = []
            
            for orden in datos.get("orders", []):
                fecha_cruda = orden.get("creationDate", "")
                fecha = fecha_cruda[:10] if fecha_cruda else ""
                
                # Extracción segura
                comprador = orden.get("buyer", {}).get("username", "Comprador Desconocido")
                
                estado_pago = orden.get("paymentSummary", {}).get("totalDueSeller", {}).get("value", "Pagado")
                if str(estado_pago) == "0.0":
                    estado_pago = "Pagado"
                    
                notas = orden.get("buyerCheckoutNotes", "")
                if not notas:
                    notas = "Sin notas del cliente."

                # Información de envío blindada
                shipping_instructions = orden.get("fulfillmentStartInstructions", [])
                shipping = {}
                if shipping_instructions and isinstance(shipping_instructions, list):
                    shipping = shipping_instructions[0].get("shippingStep", {}).get("shipTo", {})
                    
                contact = shipping.get("contactAddress", {}) if isinstance(shipping, dict) else {}
                full_name = shipping.get("fullName", "") if isinstance(shipping, dict) else ""
                
                # Extraemos el SKU del primer producto encontrado
                sku = "Sin SKU"
                line_items = orden.get("lineItems", [])
                if line_items and isinstance(line_items, list) and len(line_items) > 0:
                    sku = line_items[0].get("sku", "Sin SKU")
                
                addr1 = contact.get("addressLine1", "") if isinstance(contact, dict) else {}
                city = contact.get("city", "") if isinstance(contact, dict) else ""
                
                direccion = f"{full_name}, {addr1}, {city}".strip(", ")
                if not direccion or direccion == ",":
                    direccion = "Dirección no disponible"
                
                ordenes_procesadas.append({
                    "Order ID":       orden.get("orderId", "Sin ID"),
                    "Fecha":          fecha,
                    "Comprador":      comprador,
                    "Estado del Pago": f"USD {estado_pago}" if estado_pago != "Pagado" else "Pagado ✅",
                    "Notas del Cliente": notas,
                    "Direccion": direccion,
                    "SKU": sku
                })
                
            return ordenes_procesadas

        except Exception as e:
            # Mostramos el error exacto para depuración
            st.error(f"DEBUG Error eBay: {str(e)} - Respuesta de eBay: {resp.text if 'resp' in locals() else 'No response'}")
            return []

    def upload_tracking(self, token: str, order_id: str, tracking_number: str, carrier: str) -> tuple[bool, str]:
        """
        Sube el número de rastreo a eBay para una orden específica usando la API de Fulfillment.
        """
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
