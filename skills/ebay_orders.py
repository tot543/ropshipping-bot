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
        Obtiene las órdenes que están pendientes de envío.
        """
        if not token:
            return []

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

        try:
            # Filtramos por las órdenes que NO han sido enviadas aún (Awaiting Shipment)
            url = f"{self.base_url}?limit={limit}&filter=orderfulfillmentstatus:{{NOT_STARTED|IN_PROGRESS}}"
            resp = requests.get(url, headers=headers, timeout=10)
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
            st.error(f"DEBUG Error eBay: {str(e)} - Respuesta de eBay: {resp.text if 'resp' in locals() else 'No response'}")
            return []

    def get_orders_response(self, token: str, limit: int = 10) -> dict:
        """
        Obtiene la respuesta completa de la API de Fulfillment filtrando por pendientes de envío.
        """
        if not token:
            return {}

        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json"
        }

        try:
            url = f"{self.base_url}?limit={limit}&filter=orderfulfillmentstatus:{{NOT_STARTED|IN_PROGRESS}}"
            resp = requests.get(url, headers=headers, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            st.error(f"Error cargando órdenes: {e}")
            return {}

    def send_buyer_message(self, token: str, order_id: str, message_text: str) -> tuple[bool, str]:
        """
        Envía un mensaje al comprador asociado a una orden mediante la API de eBay Trading (Legacy).
        """
        if not token or not order_id or not message_text:
            return False, "Faltan datos para enviar el mensaje."

        # Para mensajería de buyer-seller en eBay, se suele usar el Trading API 
        # (AddMemberMessageAAQToPartner) o el sistema de comunicaciones.
        # Por ahora simularemos la integración o usaremos el sistema de soporte si está disponible.
        # TODO: Implementar llamada real a Trading API / AddMemberMessageAAQToPartner
        
        url = f"https://api.ebay.com/ws/api.dll" # Endpoint genérico de Trading API
        # Nota: La implementación real requiere XML y headers específicos de Trading API.
        
        return True, "Mensaje enviado (Simulado vía API)"

    def get_order_payout(self, token: str, order_id: str) -> float | None:
        """
        Obtiene el monto neto real desde la Finances API de eBay.
        """
        if not token or not order_id:
            return None

        url = f"https://api.ebay.com/sell/finances/v1/transaction?filter=orderId:{{{order_id}}}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json"
        }

        try:
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                for trans in data.get("transactions", []):
                    if trans.get("transactionType") == "SALE":
                        return float(trans.get("amount", {}).get("value", 0.0))
            return None
        except Exception:
            return None

    def get_item_image_fallback(self, token: str, legacy_item_id: str) -> str | None:
        """
        Obtiene la imagen oficial del producto usando la Browse API.
        """
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
