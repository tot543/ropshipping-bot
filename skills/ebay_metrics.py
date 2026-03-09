import requests
from datetime import datetime, timedelta


class EbayMetricsAgent:
    """
    Agente especializado en extraer métricas de la API de Fulfillment de eBay.
    Diseñado con tolerancia a fallos extrema (Zero-Trust al JSON devuelto).
    """

    def __init__(self):
        self.base_url = "https://api.ebay.com/sell/fulfillment/v1/order"

    def get_weekly_stats(self, token: str) -> dict:
        """
        Obtiene el total de órdenes y ventas netas de los últimos 7 días.
        Siempre retorna un dict estricto: {"ordenes": int, "ventas": float}.
        """
        res = {"ordenes": 0, "ventas": 0.0}

        if not token:
            return res

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        try:
            # Hacemos la petición con limit=50 para traer suficientes datos históricos
            resp = requests.get(f"{self.base_url}?limit=50", headers=headers, timeout=10)
            
            # Si no es un 200 OK (ej. 401 vencido, 403 sin acceso, 500 error ebay), salimos silenciosamente
            if resp.status_code != 200:
                return res
            
            datos = resp.json()
            ordenes = datos.get("orders", [])

            fecha_limite = datetime.utcnow() - timedelta(days=7)

            for order in ordenes:
                # 1. Parseo seguro de fecha
                fecha_cruda = order.get("creationDate", "")
                
                try:
                    # Limpiamos el string para que funcione con datetime.fromisoformat
                    # Formato típico eBay: 2026-03-05T14:30:00.000Z
                    fecha_str = fecha_cruda.replace("Z", "+00:00")
                    dt_obj = datetime.fromisoformat(fecha_str)
                    
                    # Convertimos a tz-naive para poder comparar con datetime.utcnow() sin error
                    fecha_orden = dt_obj.replace(tzinfo=None)
                except Exception:
                    # Si la fecha viene vacía o rara, asumimos que es vieja y la ignoramos
                    continue
                
                # 2. Sumamos si está dentro de los últimos 7 días
                if fecha_orden >= fecha_limite:
                    res["ordenes"] += 1
                    
                    # 3. Extracción profunda y ultra-segura del monto de la orden
                    # Usamos .get encadenado. Cualquier eslabón ausente devolverá {} y luego 0
                    precio_str = order.get("pricingSummary", {}).get("total", {}).get("value", 0)
                    
                    try:
                        res["ventas"] += float(precio_str)
                    except (ValueError, TypeError):
                        pass

        except Exception:
            # Silenciamos timeouts de red, JSONDecodeErrors o cualquier otra interrupción
            pass
            
        return res
