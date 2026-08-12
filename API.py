import os
import requests
from flask import Flask, request
import google.generativeai as genai

app = Flask(__name__)

ID_INSTANCE = os.getenv("ID_INSTANCE")
API_TOKEN_INSTANCE = os.getenv("API_TOKEN_INSTANCE")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
SUPERVISOR_CHAT_ID = "584128222613@c.us" 

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-3.5-flash')

chats_pausados = set()

SYSTEM_PROMPT = """
Eres el asistente virtual de Campo Salud. 
SENSIBILIDAD ALTA (70%): Si no estás 100% seguro de la respuesta, o si el tema es complejo, financiero o requiere atención personal, NO intentes responder. Responde EXCLUSIVAMENTE: ESCALAR_HUMANO.

REGLAS DE ESCALADO:
- Si piden precios, costos o cotizaciones: ESCALAR_HUMANO.
- Si envían fotos, archivos o audios: ESCALAR_HUMANO.

MENÚ INICIAL:
Si saludan, ofrece:
"¡Hola! Bienvenido a Campo Salud 🚜. ¿En qué podemos ayudar hoy? 
1️⃣ Agroquímicos
2️⃣ Medicamentos animales
3️⃣ Consultas veterinarias
4️⃣ Hablar con un asesor"
"""

def send_whatsapp_message(chat_id, text):
    url = f"https://api.green-api.com/waInstance{ID_INSTANCE}/sendMessage/{API_TOKEN_INSTANCE}"
    try:
        response = requests.post(url, json={"chatId": chat_id, "message": text})
        print(f"[GREEN API RESPONSE] Enviado a {chat_id}: Código {response.status_code} | {response.text}")
    except Exception as e:
        print(f"[GREEN API ERROR] No se pudo conectar: {e}")

@app.route('/webhook', methods=['POST'])
def webhook():
    body = request.get_json()
    if not body or body.get('typeWebhook') != 'incomingMessageReceived': 
        return 'OK', 200
        
    chat_id = body.get('senderData', {}).get('chatId')
    msg_type = body.get('messageData', {}).get('typeMessage')
    is_me = body.get('senderData', {}).get('isMe')

    # Extraer el texto correctamente (sea texto normal o respuesta citada)
    if msg_type == 'textMessage':
        text = body.get('messageData', {}).get('textMessageData', {}).get('textMessage', '')
    elif msg_type == 'extendedTextMessage':
        text = body.get('messageData', {}).get('extendedTextMessageData', {}).get('text', '')
    else:
        text = ""

    print(f"\n[MENSAJE ENTRANTE] De: {chat_id} | Tipo: {msg_type} | Texto: {text}")

    # Comandos del administrador (Business)
    if is_me:
        if text.strip() == '/bot on': 
            chats_pausados.discard(chat_id)
            print(f"[BOT REACTIVADO] para el chat {chat_id}")
        elif text.strip() == '/bot off': 
            chats_pausados.add(chat_id)
            print(f"[BOT PAUSADO] para el chat {chat_id}")
        return 'OK', 200

    # Si el usuario está en la lista de pausa, ignorarlo
    if chat_id in chats_pausados: 
        print(f"[IGNORADO] El chat {chat_id} está en la lista de pausados por el humano.")
        return 'OK', 200

    # Si envía archivo/imagen/audio -> Pausar y Escalar
    if msg_type not in ['textMessage', 'extendedTextMessage']:
        print(f"[ESCALADO AUTO] Archivo recibido de {chat_id}. Pausando bot.")
        chats_pausados.add(chat_id)
        send_whatsapp_message(chat_id, "He recibido tu mensaje. Un asesor de Campo Salud te contactará pronto. 🧑‍🌾")
        send_whatsapp_message(SUPERVISOR_CHAT_ID, f"🔔 ALERTA: El cliente {chat_id} necesita atención (envió archivo).")
        return 'OK', 200

    # Consultar a la IA
    print("[CONSULTANDO A GEMINI...]")
    response = model.generate_content(f"{SYSTEM_PROMPT}\n\nCliente: {text}")
    reply = response.text.strip()
    print(f"[RESPUESTA GEMINI GENERADA CON ÉXITO]")

    if "ESCALAR_HUMANO" in reply:
        chats_pausados.add(chat_id)
        print("[ACCIÓN] Gemini decidió escalar al humano.")
        send_whatsapp_message(chat_id, "Claro, te pondré en contacto con un asesor de Campo Salud. Aguarda un momento... 🧑‍🌾")
        send_whatsapp_message(SUPERVISOR_CHAT_ID, f"🔔 ALERTA: El cliente {chat_id} solicitó hablar con un humano o preguntó por precios/costos.")
    else:
        print("[ACCIÓN] Enviando respuesta normal...")
        send_whatsapp_message(chat_id, reply)

    return 'OK', 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
