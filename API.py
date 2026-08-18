import os
import requests
from flask import Flask, request
from datetime import datetime, timezone, timedelta

app = Flask(__name__)

ID_INSTANCE = os.getenv("ID_INSTANCE")
API_TOKEN_INSTANCE = os.getenv("API_TOKEN_INSTANCE")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

NUMEROS_PERMITIDOS = ["584120326262@c.us", "584147178563@c.us", "584128222613@c.us"]
NUMERO_VENTAS = "584128222613@c.us"
NUMERO_TECNICO = "584247609075@c.us"
NUMERO_FACTURACION = "584247157087@c.us"

chats_pausados = {}

def send_whatsapp_message(chat_id, text):
    url = f"https://api.green-api.com/waInstance{ID_INSTANCE}/sendMessage/{API_TOKEN_INSTANCE}"
    try:
        requests.post(url, json={"chatId": chat_id, "message": text}, timeout=10)
    except: pass

@app.route('/webhook', methods=['POST'])
def webhook():
    body = request.get_json()
    if not body or body.get('typeWebhook') != 'incomingMessageReceived': return 'OK', 200

    chat_id = body.get('senderData', {}).get('chatId')
    msg_type = body.get('messageData', {}).get('typeMessage')
    is_me = body.get('senderData', {}).get('isMe')

    if chat_id not in NUMEROS_PERMITIDOS and not is_me: return 'OK', 200

    if not is_me and chat_id not in chats_pausados:
        # AVISO INMEDIATO PARA EVITAR TIMEOUT
        send_whatsapp_message(chat_id, "Analizando tu solicitud, dame un segundo...")
        
        # CONSULTA GEMINI (MODELO 3.6-FLASH)
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.6-flash:generateContent?key={GEMINI_API_KEY}"
        text = body.get('messageData', {}).get('textMessageData', {}).get('textMessage', '')
        
        try:
            response = requests.post(url, json={"contents": [{"parts": [{"text": text}]}]}, timeout=20)
            reply = response.json()['candidates'][0]['content']['parts'][0]['text']
            
            # GESTIÓN DE ETIQUETAS
            destino = None
            if "[ESCALAR_VENTAS]" in reply: destino = NUMERO_VENTAS
            elif "[ESCALAR_TECNICO]" in reply: destino = NUMERO_TECNICO
            elif "[ESCALAR_FACTURACION]" in reply: destino = NUMERO_FACTURACION
            
            if destino:
                chats_pausados[chat_id] = datetime.now()
                send_whatsapp_message(chat_id, reply.replace("[ESCALAR_VENTAS]", "").replace("[ESCALAR_TECNICO]", "").replace("[ESCALAR_FACTURACION]", ""))
                send_whatsapp_message(destino, f"⚠️ ASISTENCIA REQUERIDA\nCliente: {chat_id.split('@')[0]}\nRespuesta: {reply[:100]}")
            else:
                send_whatsapp_message(chat_id, reply)
        except:
            send_whatsapp_message(chat_id, "Hubo un error técnico, te paso con un asesor ahora mismo.")
            send_whatsapp_message(NUMERO_TECNICO, f"⚠️ ALERTA: Fallo en IA con el cliente {chat_id.split('@')[0]}")
            
    return 'OK', 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
