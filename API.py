import os
import requests
from flask import Flask, request

app = Flask(__name__)

ID_INSTANCE = os.getenv("ID_INSTANCE")
API_TOKEN_INSTANCE = os.getenv("API_TOKEN_INSTANCE")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
SUPERVISOR_CHAT_ID = "584128222613@c.us" 

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
        requests.post(url, json={"chatId": chat_id, "message": text})
        print(f"[GREEN API] Mensaje enviado a {chat_id}")
    except Exception as e:
        print(f"[GREEN API ERROR]: {e}")

# ==========================================
# NUEVO MOTOR LIGERO DE GOOGLE (CERO MEMORIA)
# ==========================================
def consultar_gemini(texto_usuario):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{
            "parts": [{"text": f"{SYSTEM_PROMPT}\n\nCliente: {texto_usuario}"}]
        }]
    }
    headers = {'Content-Type': 'application/json'}
    try:
        response = requests.post(url, headers=headers, json=payload)
        datos = response.json()
        if 'candidates' in datos:
            return datos['candidates'][0]['content']['parts'][0]['text'].strip()
        else:
            print(f"[ERROR API GOOGLE]: {datos}")
            return "ESCALAR_HUMANO"
    except Exception as e:
        print(f"[EXCEPCIÓN API GOOGLE]: {e}")
        return "ESCALAR_HUMANO"

@app.route('/webhook', methods=['POST'])
def webhook():
    body = request.get_json()
    if not body or body.get('typeWebhook') != 'incomingMessageReceived': 
        return 'OK', 200
        
    chat_id = body.get('senderData', {}).get('chatId')
    msg_type = body.get('messageData', {}).get('typeMessage')
    is_me = body.get('senderData', {}).get('isMe')

    if msg_type == 'textMessage':
        text = body.get('messageData', {}).get('textMessageData', {}).get('textMessage', '')
    elif msg_type == 'extendedTextMessage':
        text = body.get('messageData', {}).get('extendedTextMessageData', {}).get('text', '')
    else:
        text = ""

    print(f"\n[MENSAJE ENTRANTE] De {chat_id} | Texto: {text}")

    if is_me:
        if text.strip() == '/bot on': 
            chats_pausados.discard(chat_id)
            print("[BOT REACTIVADO MANUALMENTE]")
        elif text.strip() == '/bot off': 
            chats_pausados.add(chat_id)
            print("[BOT PAUSADO MANUALMENTE]")
        return 'OK', 200

    if chat_id in chats_pausados: 
        return 'OK', 200

    if msg_type not in ['textMessage', 'extendedTextMessage']:
        chats_pausados.add(chat_id)
        send_whatsapp_message(chat_id, "He recibido tu archivo. Un asesor de Campo Salud te contactará pronto. 🧑‍🌾")
        send_whatsapp_message(SUPERVISOR_CHAT_ID, f"🔔 ALERTA: El cliente {chat_id} necesita atención (envió un archivo).")
        return 'OK', 200

    print("[CONSULTANDO A GEMINI LIGERO...]")
    reply = consultar_gemini(text)
    print("[RESPUESTA RECIBIDA CON ÉXITO]")

    if "ESCALAR_HUMANO" in reply:
        chats_pausados.add(chat_id)
        send_whatsapp_message(chat_id, "Claro, te pondré en contacto con un asesor de Campo Salud. Aguarda un momento... 🧑‍🌾")
        send_whatsapp_message(SUPERVISOR_CHAT_ID, f"🔔 ALERTA: El cliente {chat_id} solicitó hablar con un humano o preguntó por precios/costos.")
    else:
        send_whatsapp_message(chat_id, reply)

    return 'OK', 200

if __name__ == '__main__':
    puerto = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=puerto)
