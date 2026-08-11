import os
import requests
from flask import Flask, request
import google.generativeai as genai

app = Flask(__name__)

# 1. Variables de entorno (Las sacaremos de Green API y Google)
ID_INSTANCE = os.getenv("ID_INSTANCE")
API_TOKEN_INSTANCE = os.getenv("API_TOKEN_INSTANCE")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# 2. Configurar Gemini
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

# 3. Personalidad e instrucciones de Campo Salud
SYSTEM_PROMPT = """
Eres el asistente virtual experto de 'Campo Salud', un negocio de suministros agrícolas y veterinarios en Mucuchíes. 
Tus recomendaciones agronómicas deben ser de fuentes seguras y certeras. 
Te especializas en cultivos de altura (2660 - 3700 msnm) como ajos, papas, zanahorias y fresas.
Si recomiendas productos específicos del inventario, recuerda que:
- Pottent es una fuente de potasio.
- OMEX es la variante NK60.
- VITAMIN contiene calcio.
No escatimes en costos para dar las mejores y más seguras recomendaciones para el control de plagas, nemátodos y nutrición.
"""

@app.route('/webhook', methods=['POST'])
def webhook():
    body = request.get_json()
    
    # Verificar que el evento sea un mensaje nuevo recibido
    if body and body.get('typeWebhook') == 'incomingMessageReceived':
        message_data = body.get('messageData', {})
        
        # Verificar que sea un mensaje de texto
        if message_data.get('typeMessage') == 'textMessage':
            user_text = message_data.get('textMessageData', {}).get('textMessage')
            sender_chat_id = body.get('senderData', {}).get('chatId')
            is_me = body.get('senderData', {}).get('isMe')
            
            # Evitar que el bot se responda a sí mismo
            if sender_chat_id and not is_me:
                # 4. Enviar a Gemini
                gemini_response = model.generate_content(f"{SYSTEM_PROMPT}\n\nCliente dice: {user_text}")
                reply_text = gemini_response.text
                
                # 5. Devolver la respuesta a WhatsApp vía Green API
                send_whatsapp_message(sender_chat_id, reply_text)
                
    return 'OK', 200

def send_whatsapp_message(chat_id, text):
    url = f"https://api.green-api.com/waInstance{ID_INSTANCE}/sendMessage/{API_TOKEN_INSTANCE}"
    payload = {
        "chatId": chat_id,
        "message": text
    }
    headers = {'Content-Type': 'application/json'}
    requests.post(url, headers=headers, json=payload)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
