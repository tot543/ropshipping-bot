import requests
import json
import streamlit as st

class GroqAssistant:
    """
    Agente experto en IA usando la API compatible con OpenAI de Groq.
    Sirve para generar descripciones HTML persuasivas y extraer aspectos técnicos.
    """
    
    def __init__(self):
        self.api_url = "https://api.groq.com/openai/v1/chat/completions"

    def _llamar_groq(self, prompt_sistema: str, prompt_usuario: str) -> str:
        """
        Realiza la petición HTTP directa a la API de Groq.
        """
        try:
            api_key = st.secrets["groq"]["api_key"]
        except KeyError:
            raise ValueError("Falta configurar [groq] api_key en secrets.toml")
            
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": "openai/gpt-oss-120b",
            "messages": [
                {"role": "system", "content": prompt_sistema},
                {"role": "user", "content": prompt_usuario}
            ]
        }
        
        try:
            resp = requests.post(self.api_url, headers=headers, json=payload, timeout=20)
            resp.raise_for_status()
            
            data = resp.json()
            return data['choices'][0]['message']['content']
        except Exception as e:
            err_msg = f"Error en API de Groq: {str(e)}"
            if hasattr(e, 'response') and e.response is not None:
                err_msg += f" - Respuesta: {e.response.text}"
            raise RuntimeError(err_msg)

    def generar_descripcion(self, titulo: str, bullets: list) -> str:
        """
        Genera una descripción HTML limpia y persuasiva en español,
        evitando estrictamente prometer garantías o devoluciones.
        """
        sys_prompt = (
            "Eres un copywriter experto. Genera una descripción HTML limpia (<h2>, <ul>, <li>) "
            "en ESPAÑOL para eBay. REGLA DE ORO: NUNCA menciones garantía (warranty), reembolso ni servicio técnico."
        )
        
        user_prompt = f"Título del producto:\n{titulo}\n\nCaracterísticas (Bullets):\n"
        user_prompt += "\n".join([f"- {b}" for b in bullets])
        
        return self._llamar_groq(sys_prompt, user_prompt)

    def generar_aspectos(self, titulo: str, bullets: list) -> str:
        """
        Extrae los aspectos clave en un JSON validado, combinando specs default obligatorias.
        """
        sys_prompt = (
            "Extrae especificaciones técnicas del producto en JSON válido. "
            "REGLAS OBLIGATORIAS:\n"
            "1) SIEMPRE incluye estas cuatro llaves en tu respuesta JSON, sin importar de qué producto se trate: \"Brand\", \"MPN\", \"Country/Region of Manufacture\", y \"Type\".\n"
            "2) En \"Country/Region of Manufacture\" pon \"United States\".\n"
            "3) En \"Brand\" pon \"Unbranded\" siempre.\n"
            "5) Extrae otros datos (Color, Material) solo si existen.\n"
            "6) REGLA UNIVERSAL DE CONTEXTO: Analiza la categoría del producto. Si por sentido común sabes que esa "
            "categoría requiere aspectos técnicos obligatorios (ej. Marca, Modelo, Color, Talla, Author, Publication Name, etc.) "
            "pero no tienes el dato en la descripción, ESTÁS OBLIGADO a crear la llave y asignarle el valor [\"Does not apply\"]. "
            "Nunca omitas aspectos clave de la categoría.\n"
            "7) REGLA DE ORO: NUNCA omitas una llave obligatoria. Si no tienes la información, "
            "asigna estrictamente el valor [\"Does not apply\"]. Es preferible incluir \"Does not apply\" "
            "a omitir la llave por completo.\n"
            "Devuelve SOLO un objeto JSON con arreglos de strings, sin bloques de código markdown."
        )
        
        user_prompt = f"Título del producto:\n{titulo}\n\nCaracterísticas (Bullets):\n"
        user_prompt += "\n".join([f"- {b}" for b in bullets])
        
        return self._llamar_groq(sys_prompt, user_prompt)

    def interpretar_error_aspectos(self, error_json: str) -> list:
        """
        Analiza el JSON de error de eBay y extrae los nombres de los aspectos faltantes.
        """
        sys_prompt = (
            "Eres un analista técnico de la API de eBay. Tu tarea es recibir un JSON de error "
            "y extraer EXCLUSIVAMENTE los nombres de los aspectos (Item Specifics) que eBay indica que faltan o son requeridos."
            "\n\nEjemplo de entrada: {'errors': [{'message': 'The item specific Brand is missing.'}]}"
            "\nSalida esperada: ['Brand']"
            "\n\nResponde SOLO una lista de Python válida (ej. [\"Brand\", \"Model\"]), sin explicaciones ni bloques de markdown."
        )
        try:
            respuesta = self._llamar_groq(sys_prompt, f"Error JSON:\n{error_json}")
            # Limpiar posibles bloques de código markdown si la IA ignora la instrucción de No Markdown
            respuesta = respuesta.replace('```python', '').replace('```json', '').replace('```', '').strip()
            # Asegurar formato de lista JSON
            import ast
            return ast.literal_eval(respuesta)
        except Exception as e:
            print(f"IA no pudo interpretar el error: {e}")
            return []
