import os
import json
import requests
import google.generativeai as genai
from flask import Flask, request, make_response

# --- Configuración Inicial ---
app = Flask(__name__) 
# Estas variables se configuran como variables de entorno en Google Cloud Functions
FB_VERIFY_TOKEN = os.environ.get('FB_VERIFY_TOKEN')
FB_PAGE_ACCESS_TOKEN = os.environ.get('FB_PAGE_ACCESS_TOKEN')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')

if not FB_VERIFY_TOKEN or not FB_PAGE_ACCESS_TOKEN or not GEMINI_API_KEY:
    print("ERROR: Faltan variables de entorno críticas (FB_VERIFY_TOKEN, FB_PAGE_ACCESS_TOKEN, GEMINI_API_KEY)")
    # En un entorno de producción, podrías manejar esto de forma más robusta

try:
    genai.configure(api_key=GEMINI_API_KEY)
    gemini_model = genai.GenerativeModel('gemini-2.0-flash') # O el modelo que prefieras
except Exception as e:
    print(f"Error al configurar Gemini: {e}")
    gemini_model = None

# --- Lógica del Agente de IA ---

def get_gemini_response(user_comment_text, page_name="Nuestra Página", page_description="ayudarte con tus consultas generales"):
    """
    Genera una respuesta usando Gemini, con logs detallados para depuración.
    """
    if not gemini_model:
        print("CRITICAL ERROR: El modelo de Gemini no fue inicializado correctamente.")
        return "Lo siento, estoy teniendo problemas técnicos en este momento."

    # Prepara el prompt como antes
    prompt = f"""Eres un asistente virtual amigable y servicial para la página de Facebook 'undertk studio', que es una agencia de marketing que tiene servicios de creación de contenido pauta y contenido organico asi como desarrollo de sitios web.
Un usuario ha comentado: "{user_comment_text}"

Tu tarea es:
1. Analiza el comentario del usuario.
2. Si es una pregunta general que puedes responder, hazlo de forma concisa y amigable.
3. Si la pregunta es muy específica, sobre un pedido, un problema personal, o requiere información que no tienes, sugiere amablemente que contacten por mensaje privado o indica que un humano del equipo responderá pronto.
4. Si el comentario no es una pregunta (ej. un saludo, un agradecimiento), responde de forma apropiada.
5. No inventes información. Si no sabes la respuesta a una pregunta específica, admítelo.

la información general la puedes encontrar en el sitio https://www.undertk.studio/
 si piden información más detallada proporcionales el siguiente enlace de whatsapp https://api.whatsapp.com/send/?phone=525568764719&text&type=phone_number&app_absent=0

Responde directamente al comentario del usuario.
"""
    
    print("DEBUG: Dentro de get_gemini_response. A punto de llamar a gemini_model.generate_content(prompt).")
    try:
        # Aquí es donde probablemente ocurre el timeout
        response = gemini_model.generate_content(prompt)
        
        # Si ves este log, significa que la llamada a Gemini funcionó
        print("DEBUG: Llamada a Gemini API exitosa.")
        return response.text
    except Exception as e:
        # Si hay un error rápido en la API, lo veremos aquí
        print(f"CRITICAL ERROR: Ocurrió una excepción al llamar a Gemini API: {e}")
        return "Lo siento, no pude procesar tu solicitud con la IA en este momento."

def post_facebook_reply(comment_id, message):
    """
    Publica una respuesta a un comentario en Facebook.
    """
    if not FB_PAGE_ACCESS_TOKEN:
        print("Error: FB_PAGE_ACCESS_TOKEN no está configurado.")
        return False

    post_url = f"https://graph.facebook.com/v23.0/{comment_id}/comments" # Asegúrate de usar la versión más reciente de la API
    payload = {
        'message': message,
        'access_token': FB_PAGE_ACCESS_TOKEN
    }
    try:
        response = requests.post(post_url, data=payload)
        response.raise_for_status() # Lanza una excepción para errores HTTP
        print(f"Respuesta publicada en Facebook: {response.json()}")
        return True
    except requests.exceptions.RequestException as e:
        print(f"Error al publicar en Facebook: {e}")
        if e.response is not None:
            print(f"Detalles del error de Facebook: {e.response.text}")
        return False

# --- Google Cloud Function Entry Point ---
# (Esta función se llamará 'facebook_webhook_handler' cuando despliegues la Cloud Function)
# Necesitarás Flask para manejar las solicitudes HTTP de manera más sencilla.

app = Flask(__name__)

@app.route('/', methods=['GET', 'POST'])
def facebook_webhook_handler():
    if request.method == 'GET':
        # Verificación del Webhook de Facebook
        verify_token = request.args.get('hub.verify_token')
        if verify_token == FB_VERIFY_TOKEN:
            challenge = request.args.get('hub.challenge')
            return make_response(challenge, 200)
        else:
            return make_response('Error, token de verificación incorrecto', 403)

    elif request.method == 'POST':
        print("DEBUG: Solicitud POST recibida (posiblemente un nuevo comentario).")
        data = request.get_json()
        print(f"DEBUG: Datos recibidos de Facebook en POST: {json.dumps(data, indent=2)}") # Imprime todo el JSON para entenderlo

        # Facebook envía los datos en una estructura anidada.
        # Debes procesar estos datos para extraer la información del comentario.
        if data.get("object") == "page":
            for entry in data.get("entry", []):
                page_id_from_event = entry.get("id") # ID de tu página
                for change in entry.get("changes", []):
                    if change.get("field") == "feed":
                        item_value = change.get("value", {})
                        item_type = item_value.get("item")

                        # Asegurarnos de que es un comentario y no otra cosa del feed
                        if item_type == "comment":
                            comment_id = item_value.get("comment_id")
                            user_message = item_value.get("message", "").strip()
                            sender_id = item_value.get("from", {}).get("id")
                            # parent_id podría ser útil si quieres saber a qué publicación o comentario se está respondiendo
                            # post_id = item_value.get("post_id")

                            print(f"DEBUG: Nuevo comentario detectado. ID: {comment_id}, Remitente: {sender_id}, Mensaje: '{user_message}'")

                            # MUY IMPORTANTE: Evitar bucles infinitos o responder a ti mismo.
                            # Compara el sender_id con el ID de tu página (page_id_from_event).
                            # También, el 'FB_PAGE_ID' sería el ID de tu página, idealmente desde una variable de entorno.
                            # Aquí asumimos que 'page_id_from_event' es el ID de tu página.
                            if sender_id == page_id_from_event:
                                print("DEBUG: El comentario es de la propia página. No se responde.")
                                return make_response("EVENT_RECEIVED_FROM_PAGE_ITSELF", 200)

                            if not user_message:
                                print("DEBUG: Comentario vacío. No se responde.")
                                return make_response("EVENT_RECEIVED_EMPTY_COMMENT", 200)

                            # Aquí puedes añadir más lógica de filtrado si quieres:
                            # - Responder solo si el comentario es una pregunta.
                            # - No responder a comentarios con ciertas palabras clave (spam).
                            # - Etc.
                            # Por ahora, intentaremos responder a la mayoría.

                            print(f"DEBUG: Procesando comentario '{user_message}' para respuesta de IA.")
                            # 1. Obtener respuesta de Gemini (asumiendo que tienes la función get_gemini_response)
                            # Puedes pasar más contexto a Gemini si es necesario (nombre de la página, etc.)
                            ai_response = get_gemini_response(user_message, page_name="Tu Página de FB", page_description="asistente virtual")
                            print(f"DEBUG: Respuesta generada por Gemini: '{ai_response}'")

                            # 2. Publicar respuesta en Facebook (asumiendo que tienes la función post_facebook_reply)
                            if ai_response:
                                success = post_facebook_reply(comment_id, ai_response)
                                if success:
                                    print("DEBUG: Respuesta publicada exitosamente en Facebook.")
                                else:
                                    print("ERROR: Hubo un problema al publicar la respuesta en Facebook.")
                            else:
                                print("WARN: Gemini no generó respuesta o la respuesta fue vacía.")
                        else:
                            print(f"DEBUG: Item del feed no es un comentario, es '{item_type}'. Ignorando.")
        else:
            print(f"DEBUG: Objeto de la solicitud POST no es 'page': {data.get('object')}")

        # Siempre devuelve un 200 OK a Facebook para confirmar que recibiste el evento,
        # incluso si decides no actuar sobre él o si hay un error interno al procesarlo.
        # Facebook reintentará enviar el evento si no recibe un 200 OK.
        return make_response("EVENT_RECEIVED", 200)

    else:
        # Manejar otros métodos si es necesario
        print(f"WARN: Método no permitido recibido: {request.method}")
        return make_response("Método no permitido", 405)

# Para pruebas locales (opcional, Flask development server)
# if __name__ == '__main__':
#     if not FB_VERIFY_TOKEN or not FB_PAGE_ACCESS_TOKEN or not GEMINI_API_KEY:
#         print("ERROR: Faltan variables de entorno para prueba local. Configúralas.")
#     else:
#         print(f"FB_VERIFY_TOKEN: {FB_VERIFY_TOKEN[:5]}...") # Solo muestra una parte por seguridad
#         print(f"FB_PAGE_ACCESS_TOKEN: {FB_PAGE_ACCESS_TOKEN[:5]}...")
#         print(f"GEMINI_API_KEY: {GEMINI_API_KEY[:5]}...")
#         app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))