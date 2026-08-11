import os
import requests
from flask import Flask, request
import google.generativeai as genai

app = Flask(__name__)

# Credenciales
ID_INSTANCE = os.getenv("ID_INSTANCE")
API_TOKEN_INSTANCE = os.getenv("API_TOKEN_INSTANCE")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
# El número del supervisor debe llevar el @c.us al final
SUPERVISOR_CHAT_ID = "584128222613@c.us" 

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

chats_pausados = set()

SYSTEM_PROMPT = """
Eres el asistente virtual de Campo Salud. 
SENSIBILIDAD ALTA (70%): Si no estás 100% seguro de la respuesta, o si el tema es complejo, financiero o requiere atención personal, NO intentes responder. Responde EXCLUSIVAMENTE: ESCALAR_HUMANO.

REGLAS DE ESCALADO:
- Si el usuario pide precios, costos o cotizaciones: ESCALAR_HUMANO.
- Si el usuario envía fotos, archivos o audios: ESCALAR_HUMANO.
- Si el usuario insiste o se muestra frustrado: ESCALAR_HUMANO.

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
    requests.post(url, json={"chatId": chat_id, "message": text})

@app.route('/webhook', methods=['POST'])
def webhook():
    body = request.get_json()
    if not body or body.get('typeWebhook') != 'incomingMessageReceived': return 'OK', 200
        
    chat_id = body.get('senderData', {}).get('chatId')
    msg_type = body.get('messageData', {}).get('typeMessage')
    text = body.get('messageData', {}).get('textMessageData', {}).get('textMessage', '')
    is_me = body.get('senderData', {}).get('isMe')

    if is_me:
        if text.strip() == '/bot on': chats_pausados.discard(chat_id)
        elif text.strip() == '/bot off': chats_pausados.add(chat_id)
        return 'OK', 200

    if chat_id in chats_pausados: return 'OK', 200

    # 1. ESCALADO AUTOMÁTICO (Si no es texto o la IA decide escalar)
    if msg_type != 'textMessage':
        chats_pausados.add(chat_id)
        send_whatsapp_message(chat_id, "He recibido tu mensaje. Un asesor de Campo Salud te contactará pronto.")
        send_whatsapp_message(SUPERVISOR_CHAT_ID, f"🔔 ALERTA: El cliente {chat_id} necesita atención humana (envió un archivo o audio).")
        return 'OK', 200

    # 2. PROCESAR TEXTO
    response = model.generate_content(f"{SYSTEM_PROMPT}\n\nCliente: {text}")
    reply = response.text.strip()

    if "ESCALAR_HUMANO" in reply:
        chats_pausados.add(chat_id)
        send_whatsapp_message(chat_id, "Claro, te pondré en contacto con un asesor de Campo Salud. Aguarda un momento... 🧑‍🌾")
        send_whatsapp_message(SUPERVISOR_CHAT_ID, f"🔔 ALERTA: El cliente {chat_id} solicitó hablar con un humano o preguntó por precios/costos.")
    else:
        send_whatsapp_message(chat_id, reply)

    return 'OK', 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
