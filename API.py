import os
import requests
from flask import Flask, request
from datetime import datetime, timezone, timedelta

app = Flask(__name__)

ID_INSTANCE = os.getenv("ID_INSTANCE")
API_TOKEN_INSTANCE = os.getenv("API_TOKEN_INSTANCE")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# ==========================================
# 🛑 MODO PRUEBAS VIP
# ==========================================
NUMEROS_PERMITIDOS = [
    "584120326262@c.us",
    "584147178563@c.us",
    "584128222613@c.us"
]

NUMERO_VENTAS = "584128222613@c.us"
NUMERO_TECNICO = "584247609075@c.us"
NUMERO_FACTURACION = "584247157087@c.us"

chats_pausados = {}

SYSTEM_PROMPT = """
Eres el asistente virtual experto de Campo Salud.
REGLA DE ORO (ESTILO): Eres directo, conciso y extremadamente profesional. Cero texto de relleno. Resuelve dudas simples.

REGLAS DE NEGOCIO:
1. PRODUCTOS Y CALIDAD: Para la agronomía, especialmente en cultivos de ajos, papas, zanahoria y fresas, debes brindar recomendaciones certeras y 100% seguras. No escatimes en costos si la solución lo requiere.
2. FORMULACIONES: Recuerda que usamos formulaciones exactas como OMEX NK60, y que nuestro acondicionador Potten-T contiene humato fosfo-potásico. NUNCA menciones marcas comerciales de la competencia al inicio. Habla del ingrediente activo.
3. HORARIO: Lunes a Viernes de 8:00 AM a 12:00 PM y de 2:00 PM a 5:00 PM.
4. FUERA DE HORARIO: Si la "Hora Actual" (indicada abajo) está fuera de este rango, DEBES iniciar tu respuesta diciendo que un humano atenderá la solicitud en el próximo horario laboral.

SISTEMA DE ESCALADO AUTOMÁTICO (ESTRICTO):
Analiza lo que necesita el cliente. Redacta tu respuesta corta solucionando la duda o saludando, y si es necesario, AÑADE UNA SOLA ETIQUETA al final:
[ESCALAR_VENTAS] -> Si quieren comprar, piden presupuestos/precios de agroquímicos o veterinaria, o desean hablar con ventas.
[ESCALAR_TECNICO] -> Si hacen consultas agronómicas/veterinarias complejas, piden diagnósticos o buscan asesoría técnica.
[ESCALAR_FACTURACION] -> Si hacen preguntas de información privada, facturación, pagos, envíos.

Si puedes responder la duda por ti mismo sin necesidad de un humano, simplemente responde sin añadir ninguna etiqueta.
"""

def get_venezuela_time():
    tz_ve = timezone(timedelta(hours=-4))
    return datetime.now(tz_ve)

def send_whatsapp_message(chat_id, text):
    url = f"https://api.green-api.com/waInstance{ID_INSTANCE}/sendMessage/{API_TOKEN_INSTANCE}"
    try:
        # TIMEOUT AÑADIDO (12 segundos) PARA PREVENIR COLAPSOS
        response = requests.post(url, json={"chatId": chat_id, "message": text}, timeout=12)
        print(f"[GREEN API] Mensaje enviado a {chat_id} - Código: {response.status_code}", flush=True)
    except Exception as e:
        print(f"[GREEN API ERROR]: {e}", flush=True)

def consultar_gemini(texto_usuario, chat_id):
    now = get_venezuela_time()
    dias = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
    dia_semana = dias[now.weekday()]
    hora_str = now.strftime("%I:%M %p")

    contexto = f"Día Actual: {dia_semana}\nHora Actual: {hora_str}\nCliente: {texto_usuario}"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.6-flash:generateContent?key={GEMINI_API_KEY}"

    payload = {
        "contents": [{
            "parts": [{"text": f"{SYSTEM_PROMPT}\n\n{contexto}"}]
        }]
    }
    headers = {'Content-Type': 'application/json'}

    print(f"[CONSULTANDO A GEMINI PARA {chat_id} ...]", flush=True)
    try:
        # TIMEOUT AÑADIDO (15 segundos) PARA PREVENIR COLAPSOS
        response = requests.post(url, headers=headers, json=payload, timeout=15)
        datos = response.json()
        if 'candidates' in datos:
            print("[RESPUESTA DE GEMINI LISTA]", flush=True)
            return datos['candidates'][0]['content']['parts'][0]['text'].strip()
        else:
            print(f"[GEMINI ERROR]: {datos}", flush=True)
            return "[ESCALAR_FACTURACION] Disculpa, tengo inconvenientes técnicos temporales. Te transferiré a administración."
    except Exception as e:
        print(f"[GEMINI EXCEPCIÓN]: {e}", flush=True)
        return "[ESCALAR_FACTURACION] Ocurrió un error. Te pasaré con un asesor en breve."

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
        hora_str = now.strftime("%I:%M %p")

        if chat_id not in NUMEROS_PERMITIDOS and not is_me:
            print(f"[BLOQUEADO POR ESCUDO] El número {chat_id} fue ignorado.", flush=True)
            return 'OK', 200

        if is_me:
            if msg_type in ['textMessage', 'extendedTextMessage']:
                text = body.get('messageData', {}).get('textMessageData', {}).get('textMessage', '') or \
                       body.get('messageData', {}).get('extendedTextMessageData', {}).get('text', '')
                text_lower = text.lower()

                if text.strip() == '/bot on':
                    chats_pausados.pop(chat_id, None)
                    print(f"[BOT REACTIVADO MANUALMENTE] para el chat {chat_id}", flush=True)
                elif text.strip() == '/bot off':
                    chats_pausados[chat_id] = now
                    print(f"[BOT PAUSADO MANUALMENTE] para el chat {chat_id}", flush=True)
                else:
                    frases_cierre = [
                        "feliz dia", "feliz día", "feliz tarde", "feliz noche", 
                        "estamos a la orden", "a su orden", "siempre a la orden", 
                        "hasta luego", "gracias por preferirnos", "cualquier duda",
                        "estamos en contacto", "feliz fin de semana"
                    ]
                    if any(frase in text_lower for frase in frases_cierre):
                        chats_pausados.pop(chat_id, None)
                        print(f"[BOT REACTIVADO AUTOMÁTICAMENTE] por frase de despedida: '{text}'", flush=True)
            return 'OK', 200

        if chat_id in chats_pausados:
            tiempo_pausado = chats_pausados[chat_id]
            diferencia = now - tiempo_pausado
            
            if diferencia >= timedelta(hours=2):
                chats_pausados.pop(chat_id, None)
                print(f"[REINICIO AUTOMÁTICO] Pasaron más de 2 horas. Reactivando bot para {chat_id}", flush=True)
            else:
                print(f"[IGNORADO] El chat {chat_id} sigue en pausa temporal.", flush=True)
                return 'OK', 200

        num_cliente = chat_id.split('@')[0]

        if msg_type not in ['textMessage', 'extendedTextMessage']:
            print("[ESCALADO AUTO] El cliente envió un archivo.", flush=True)
            chats_pausados[chat_id] = now 
            send_whatsapp_message(chat_id, "He recibido tu archivo. Una persona real lo revisará y te responderá en breve.")
            alerta = f"🚨 ALERTA DE ARCHIVO\n👤 Cliente: {num_cliente}\n🕒 Hora: {hora_str}\n📁 Motivo: Envió documento, foto o audio."
            send_whatsapp_message(NUMERO_FACTURACION, alerta)
            return 'OK', 200

        text = ""
        if msg_type == 'textMessage':
            text = body.get('messageData', {}).get('textMessageData', {}).get('textMessage', '')
        elif msg_type == 'extendedTextMessage':
            text = body.get('messageData', {}).get('extendedTextMessageData', {}).get('text', '')

        print(f"\n====================================", flush=True)
        print(f"[NUEVO MENSAJE] {num_cliente}: {text}", flush=True)

        reply = consultar_gemini(text, chat_id)
        destino_alerta = None
        motivo_alerta = ""

        if "[ESCALAR_VENTAS]" in reply:
            destino_alerta = NUMERO_VENTAS
            motivo_alerta = "Atención Comercial / Ventas"
            reply = reply.replace("[ESCALAR_VENTAS]", "").strip()
        elif "[ESCALAR_TECNICO]" in reply:
            destino_alerta = NUMERO_TECNICO
            motivo_alerta = "Consulta Técnica / Agronómica"
            reply = reply.replace("[ESCALAR_TECNICO]", "").strip()
        elif "[ESCALAR_FACTURACION]" in reply:
            destino_alerta = NUMERO_FACTURACION
            motivo_alerta = "Facturación / Información Privada"
            reply = reply.replace("[ESCALAR_FACTURACION]", "").strip()

        if reply:
            print("[ACCIÓN] Enviando respuesta automática...", flush=True)
            send_whatsapp_message(chat_id, reply)

        if destino_alerta:
            chats_pausados[chat_id] = now 
            print(f"[ACCIÓN] Bot pausado. Transfiriendo a {motivo_alerta}...", flush=True)
            alerta_formateada = f"⚠️ ASISTENCIA REQUERIDA\n👤 Cliente: {num_cliente}\n🕒 Hora: {hora_str}\n🏢 Departamento: {motivo_alerta}"
            send_whatsapp_message(destino_alerta, alerta_formateada)

        return 'OK', 200
    except Exception as e:
        print(f"[CRITICAL WEBHOOK ERROR]: {e}", flush=True)
        return 'OK', 200

if __name__ == '__main__':
    puerto = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=puerto)
