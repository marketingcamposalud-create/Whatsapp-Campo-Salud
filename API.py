import os
import requests
from flask import Flask, request, jsonify
import google.generativeai as genai

app = Flask(__name__)

# 1. Configurar las variables de entorno (las pondremos luego en Render)
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN") # Una contraseña inventada por ti
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# 2. Configurar la IA de Gemini
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

# 3. Darle la personalidad e instrucciones a tu IA (Campo Salud)
SYSTEM_PROMPT = """
Eres el asistente virtual experto de 'Campo Salud', un negocio de suministros agrícolas y veterinarios en Mucuchíes. 
Tus recomendaciones agronómicas deben ser de fuentes seguras y certeras. 
Te especializas en cultivos de altura (2660 - 3700 msnm) como ajos, papas, zanahorias y fresas.
No escatimes en costos para dar las mejores y más seguras recomendaciones para el control de plagas y nutrición.
"""

@app.route('/webhook', methods=['GET', 'POST'])
def webhook():
    # --- VERIFICACIÓN DEL WEBHOOK (META LO EXIGE) ---
    if request.method == 'GET':
        mode = request.args.get('hub.mode')
        token = request.args.get('hub.verify_token')
        challenge = request.args.get('hub.challenge')
        
        if mode == 'subscribe' and token == VERIFY_TOKEN:
            return challenge, 200
        else:
            return 'Error de verificación', 403

    # --- RECEPCIÓN DE MENSAJES DE WHATSAPP ---
    if request.method == 'POST':
        body = request.get_json()
        
        try:
            # Extraer el mensaje y el número del cliente de la estructura de datos de Meta
            message_info = body['entry'][0]['changes'][0]['value']['messages'][0]
            sender_phone = message_info['from']
            user_text = message_info['text']['body']
            
            # Generar respuesta con Gemini
            gemini_response = model.generate_content(f"{SYSTEM_PROMPT}\n\nCliente dice: {user_text}")
            reply_text = gemini_response.text
            
            # Enviar la respuesta de vuelta a WhatsApp
            send_whatsapp_message(sender_phone, reply_text)
            
        except KeyError:
            # Meta envía actualizaciones de estado (entregado, leído) que no son mensajes de texto
            pass
            
        return 'EVENT_RECEIVED', 200

def send_whatsapp_message(to, text):
    url = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    data = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text}
    }
    requests.post(url, headers=headers, json=data)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)