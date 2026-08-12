import os
import requests
from flask import Flask, request

app = Flask(__name__)

ID_INSTANCE = os.getenv("ID_INSTANCE")
API_TOKEN_INSTANCE = os.getenv("API_TOKEN_INSTANCE")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
SUPERVISOR_CHAT_ID = "584128222613@c.us" 

chats_pausados = set()

# ==========================================
# 🛑 MODO PRUEBAS: SOLO RESPONDERÁ A ESTOS NÚMEROS
# ==========================================
NUMEROS_PERMITIDOS = [
    "584128222613@c.us", 
    "584120326262@c.us"
]

SYSTEM_PROMPT = """
Eres el asistente virtual experto de Campo Salud. Tu tono es amable, muy profesional y servicial.

INFORMACIÓN DE LA EMPRESA:
- Horario de atención: Trabajamos de Lunes a Viernes de 8:00 AM a 12:00 PM y de 2:00 PM a 5:00 PM.
- Especialidades agrícolas: Asesoría y productos para cultivos comerciales, especialmente papa, ajo, zanahoria y fresa.
- Agroquímicos: Manejamos una amplia gama, incluyendo fertilizantes específicos como OMEX NK60 y Potten-T (excelente fuente de potasio).
- Veterinaria: Insumos ganaderos, alimentación, suplementos (como vitaminas a base de calcio) y organización de jornadas de exámenes de salud animal.

TUS INSTRUCCIONES ESTRICTAS:
1. Cuando un cliente salude, NUNCA escales inmediatamente. SIEMPRE debes responder primero con este mensaje:
   "¡Hola! Bienvenido a Campo Salud 🚜. ¿En qué podemos ayudarte hoy?
   1️⃣ Agroquímicos y fertilizantes
   2️⃣ Insumos y veterinaria
   3️⃣ Consultas técnicas
   4️⃣ Hablar con un asesor"
2. Si el cliente hace preguntas generales sobre los cultivos o productos que conoces, ayúdalo con información técnica básica.
3. Si el cliente pide hablar con un humano o un asesor, infórmale siempre nuestro horario de atención antes de pasarlo con él.

CUÁNDO ESCALAR (Usa la palabra exacta ESCALAR_HUMANO en tu respuesta SOLO en estos casos):
- El cliente pide precios exactos, costos, presupuestos o cotizaciones (no tienes acceso a la lista de precios).
- El cliente necesita un diagnóstico agronómico o veterinario profundo que requiere la evaluación de un profesional.
"""

def send_whatsapp_message(chat_id, text):
    url = f"https://api.green-api.com/waInstance{ID_INSTANCE}/sendMessage/{API_TOKEN_INSTANCE}"
    try:
        response = requests.post(url, json={"chatId": chat_id, "message": text})
        print(f"[GREEN API] Mensaje enviado a {chat_id}: Código {response.status_code}")
    except Exception as e:
        print(f"[GREEN API ERROR]: {e}")

def consultar_gemini(texto_usuario):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent?key={GEMINI_API_KEY}"
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
            print(f"[GEMINI ERROR]: {datos}")
            return "ESCALAR_HUMANO"
    except Exception as e:
        print(f"[GEMINI EXCEPCIÓN]: {e}")
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

    # --- LOS CHIVATOS ---
    print(f"\n====================================")
    print(f"[NUEVO MENSAJE] De: {chat_id} | Es mío: {is_me}")
    print(f"[TEXTO]: {text}")

    # EL ESCUDO
    if chat_id not in NUMEROS_PERMITIDOS and not is_me:
        print(f"[BLOQUEADO POR ESCUDO] El número {chat_id} no está en la lista VIP.")
        return 'OK', 200
    
    print(f"[PERMITIDO] El número {chat_id} pasó el escudo de pruebas.")

    if is_me:
        if text.strip() == '/bot on': 
            chats_pausados.discard(chat_id)
            print(f"[BOT REACTIVADO] para el chat {chat_id}")
        elif text.strip() == '/bot off': 
            chats_pausados.add(chat_id)
            print(f"[BOT PAUSADO] para el chat {chat_id}")
        return 'OK', 200

    if chat_id in chats_pausados: 
        print(f"[IGNORADO] El chat {chat_id} está pausado, esperando al humano.")
        return 'OK', 200

    if msg_type not in ['textMessage', 'extendedTextMessage']:
        print("[ESCALADO AUTO] El cliente envió un archivo.")
        chats_pausados.add(chat_id)
        send_whatsapp_message(chat_id, "He recibido tu archivo. Un asesor de Campo Salud te contactará pronto. 🧑‍🌾")
        send_whatsapp_message(SUPERVISOR_CHAT_ID, f"🔔 ALERTA: El cliente de prueba {chat_id} envió un archivo.")
        return 'OK', 200

    print("[CONSULTANDO A GEMINI...]")
    reply = consultar_gemini(text)
    print("[RESPUESTA DE GEMINI LISTA]")

    if "ESCALAR_HUMANO" in reply:
        print("[ACCIÓN] Gemini decidió escalar al humano.")
        chats_pausados.add(chat_id)
        send_whatsapp_message(chat_id, "Claro, te pondré en contacto con un asesor de Campo Salud. Aguarda un momento... 🧑‍🌾")
        send_whatsapp_message(SUPERVISOR_CHAT_ID, f"🔔 ALERTA: El cliente de prueba {chat_id} requiere atención.")
    else:
        print("[ACCIÓN] Enviando respuesta automática...")
        send_whatsapp_message(chat_id, reply)

    return 'OK', 200

if __name__ == '__main__':
    puerto = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=puerto)
