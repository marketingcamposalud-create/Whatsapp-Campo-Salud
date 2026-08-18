import os
import requests
import threading
from flask import Flask, request
from datetime import datetime, timezone, timedelta

app = Flask(__name__)

# CREDENCIALES
ID_INSTANCE = os.getenv("ID_INSTANCE")
API_TOKEN_INSTANCE = os.getenv("API_TOKEN_INSTANCE")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# RUTAS DE DEPARTAMENTOS
NUMEROS_PERMITIDOS = ["584120326262@c.us", "584147178563@c.us", "584128222613@c.us"]
NUMERO_VENTAS = "584128222613@c.us"
NUMERO_TECNICO = "584247609075@c.us"
NUMERO_FACTURACION = "584247157087@c.us"

chats_pausados = {}

SYSTEM_PROMPT = """
Eres "Campo", el asistente virtual experto de la empresa Campo Salud, ubicada en Mucuchíes.
REGLA DE ORO (ESTILO): Eres directo, conciso y extremadamente profesional. Cero texto de relleno.
CAPACIDAD: Debes ser capaz de responder eficientemente preguntas simples y complejas sobre agronomía y veterinaria.
REGLAS DE NEGOCIO:
1. PRODUCTOS Y CALIDAD: Brinda recomendaciones técnicas certeras priorizando la calidad y el manejo ideal para cultivos (ajo, papa, zanahoria, fresas). 
2. FORMULACIONES: Basa tus recomendaciones agronómicas en formulaciones exactas, recordando que utilizamos insumos como OMEX NK 60 (con 8.4% de nitrógeno), Byo-K 40 y Potten-T para el manejo nutricional y fitosanitario.
SISTEMA DE ESCALADO AUTOMÁTICO (ESTRICTO):
Analiza lo que necesita el cliente. Redacta tu respuesta solucionando la duda de forma técnica y veraz. Si puedes dar la mejor solución técnica por ti mismo (ej. control de nematodos), responde directamente SIN añadir ninguna etiqueta.
Solo si NO tienes la información o el cliente requiere interacción humana obligatoria, AÑADE UNA SOLA ETIQUETA al final:
[ESCALAR_VENTAS] -> Si piden presupuestos directos o precios.
[ESCALAR_TECNICO] -> Si la consulta sobrepasa tus capacidades y requiere un ingeniero.
[ESCALAR_FACTURACION] -> Si hacen preguntas de pagos o información privada.
"""

def get_venezuela_time():
    return datetime.now(timezone(timedelta(hours=-4)))

def send_whatsapp_message(chat_id, text):
    url = f"https://api.green-api.com/waInstance{ID_INSTANCE}/sendMessage/{API_TOKEN_INSTANCE}"
    try:
        requests.post(url, json={"chatId": chat_id, "message": text}, timeout=10)
    except Exception as e:
        print(f"[GREEN API ERROR]: No se pudo enviar el mensaje a {chat_id}. Detalle: {e}", flush=True)

def procesar_gemini_y_responder(chat_id, texto_usuario):
    print(f"\n[INICIANDO HILO] Analizando solicitud técnica de {chat_id}...", flush=True)
    
    now = get_venezuela_time()
    hora_str = now.strftime("%I:%M %p")
    contexto = f"Hora Actual: {hora_str}\nCliente: {texto_usuario}"

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.6-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{
            "parts": [{"text": f"{SYSTEM_PROMPT}\n\n{contexto}"}]
        }]
    }
    headers = {'Content-Type': 'application/json'}

    try:
        # Límite de tiempo aumentado a 90 segundos para procesar consultas complejas sin cortar la conexión
        response = requests.post(url, headers=headers, json=payload, timeout=90)
        datos = response.json()

        if 'candidates' in datos:
            reply = datos['candidates'][0]['content']['parts'][0]['text'].strip()
            print("[RESPUESTA DE GEMINI PROCESADA CON ÉXITO]", flush=True)

            destino = None
            if "[ESCALAR_VENTAS]" in reply: destino = NUMERO_VENTAS
            elif "[ESCALAR_TECNICO]" in reply: destino = NUMERO_TECNICO
            elif "[ESCALAR_FACTURACION]" in reply: destino = NUMERO_FACTURACION

            if destino:
                chats_pausados[chat_id] = now
                reply_limpia = reply.replace("[ESCALAR_VENTAS]", "").replace("[ESCALAR_TECNICO]", "").replace("[ESCALAR_FACTURACION]", "").strip()
                send_whatsapp_message(chat_id, reply_limpia)
                send_whatsapp_message(destino, f"⚠️ ASISTENCIA TÉCNICA REQUERIDA\n👤 Cliente: {chat_id.split('@')[0]}\n📋 Respuesta previa: {reply_limpia}")
                print(f"[BOT PAUSADO] Escalado ejecutado correctamente.", flush=True)
            else:
                send_whatsapp_message(chat_id, reply)
        else:
            print(f"[GEMINI ERROR INTERNO]: {datos}", flush=True)
            send_whatsapp_message(chat_id, "Disculpa, tengo inconvenientes técnicos procesando el diagnóstico. Te transferiré a un asesor.")
            send_whatsapp_message(NUMERO_TECNICO, f"⚠️ ALERTA: Fallo en IA con el cliente {chat_id.split('@')[0]}")
    except Exception as e:
        print(f"[ERROR DE CONEXIÓN EN HILO]: {e}", flush=True)
        send_whatsapp_message(chat_id, "Ocurrió un error de conexión procesando la información. Te pasaré con un asesor en breve.")

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        body = request.get_json()
        if not body or body.get('typeWebhook') != 'incomingMessageReceived':
            return 'OK', 200

        chat_id = body.get('senderData', {}).get('chatId')
        msg_type = body.get('messageData', {}).get('typeMessage')
        is_me = body.get('senderData', {}).get('isMe')
        now = get_venezuela_time()

        if chat_id not in NUMEROS_PERMITIDOS and not is_me:
            return 'OK', 200

        # GESTIÓN DE CONTROL MANUAL Y GATILLOS
        if is_me:
            text = body.get('messageData', {}).get('textMessageData', {}).get('textMessage', '') or \
                   body.get('messageData', {}).get('extendedTextMessageData', {}).get('text', '')
            text_lower = text.lower()

            if text.strip() == '/bot on':
                chats_pausados.pop(chat_id, None)
                print(f"[BOT REACTIVADO MANUALMENTE] Comando detectado para {chat_id}", flush=True)
            elif text.strip() == '/bot off':
                chats_pausados[chat_id] = now
                print(f"[BOT PAUSADO MANUALMENTE] Comando detectado para {chat_id}", flush=True)
            else:
                frases_cierre = ["feliz dia", "feliz día", "feliz tarde", "feliz noche", "estamos a la orden", "a su orden", "hasta luego", "gracias por preferirnos"]
                if any(frase in text_lower for frase in frases_cierre):
                    chats_pausados.pop(chat_id, None)
                    print(f"[BOT REACTIVADO AUTOMÁTICAMENTE] Frase de despedida detectada.", flush=True)
            return 'OK', 200

        # TEMPORIZADOR DE INACTIVIDAD (2 HORAS)
        if chat_id in chats_pausados:
            diferencia = now - chats_pausados[chat_id]
            if diferencia >= timedelta(hours=2):
                chats_pausados.pop(chat_id, None)
                print(f"[REINICIO AUTOMÁTICO DE SESIÓN] Límite de 2 horas superado para {chat_id}", flush=True)
            else:
                return 'OK', 200

        # EXTRACCIÓN ROBUSTA DE TEXTO
        texto_usuario = ""
        if msg_type == 'textMessage':
            texto_usuario = body.get('messageData', {}).get('textMessageData', {}).get('textMessage', '')
        elif msg_type == 'extendedTextMessage':
            texto_usuario = body.get('messageData', {}).get('extendedTextMessageData', {}).get('text', '')

        if msg_type not in ['textMessage', 'extendedTextMessage'] or not texto_usuario.strip():
            chats_pausados[chat_id] = now
            send_whatsapp_message(chat_id, "He recibido tu archivo multimedia. Un técnico real lo revisará y te responderá en breve.")
            send_whatsapp_message(NUMERO_FACTURACION, f"🚨 ALERTA DE ARCHIVO\n👤 Cliente: {chat_id.split('@')[0]}\n📁 Motivo: Documento o imagen recibida.")
            return 'OK', 200

        print(f"\n====================================", flush=True)
        print(f"[NUEVO MENSAJE] {chat_id.split('@')[0]}: {texto_usuario}", flush=True)

        # DESPLIEGUE DEL HILO ASÍNCRONO SIN MENSAJE INTERMEDIO
        hilo = threading.Thread(target=procesar_gemini_y_responder, args=(chat_id, texto_usuario))
        hilo.start()

        return 'OK', 200

    except Exception as e:
        print(f"[CRITICAL WEBHOOK ERROR]: {e}", flush=True)
        return 'OK', 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
