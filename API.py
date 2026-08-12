import os
import requests
from flask import Flask, request
from datetime import datetime, timezone, timedelta

app = Flask(__name__)

ID_INSTANCE = os.getenv("ID_INSTANCE")
API_TOKEN_INSTANCE = os.getenv("API_TOKEN_INSTANCE")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# ==========================================
# RUTAS DE DEPARTAMENTOS
# ==========================================
NUMERO_VENTAS = "584128222613@c.us"
NUMERO_TECNICO = "584247609075@c.us"
NUMERO_FACTURACION = "584247157087@c.us" # Se omitió el 0 inicial del 0424 por formato de WhatsApp

chats_pausados = set()

SYSTEM_PROMPT = """
Eres el asistente virtual experto de Campo Salud. tu nombre es Campo
REGLA DE ORO (ESTILO):Eres amigable, Eres directo, conciso y extremadamente profesional. Cero texto de relleno. Resuelve dudas simples en una o dos frases cortas.

REGLAS DE NEGOCIO:
1. PRODUCTOS: NUNCA menciones nombres de marcas comerciales al inicio. Si recomiendas soluciones para los cultivos, habla solo de compuestos (ej. fuentes de potasio, suplementos de calcio, nitrógeno). Solo proporciona marcas si el cliente pregunta directamente por una.
2. HORARIO: Lunes a Viernes de 8:00 AM a 12:00 PM y de 2:00 PM a 5:00 PM.
3. FUERA DE HORARIO: Si la "Hora Actual" (indicada abajo) está fuera de este rango, DEBES iniciar tu respuesta diciendo explícitamente que eres el asistente virtual automatizado y que una persona real le responderá su solicitud en el próximo turno laboral.

SISTEMA DE ESCALADO AUTOMÁTICO (ESTRICTO):
Analiza lo que necesita el cliente. Redacta tu respuesta corta solucionando la duda o saludando (incluyendo la advertencia de fuera de horario si aplica) y al FINAL EXACTO de tu mensaje, DEBES añadir una de estas etiquetas secretas si se requiere atención humana:

- [ESCALAR_VENTAS] -> Si quieren comprar, piden presupuestos/precios de agroquímicos o veterinaria, o desean hablar con un asesor comercial.
- [ESCALAR_TECNICO] -> Si hacen consultas agronómicas/veterinarias complejas, piden diagnósticos o buscan asesoría técnica profesional.
- [ESCALAR_FACTURACION] -> Si hacen preguntas de información privada, facturación, pagos, envíos, o si preguntan cosas que no sabes o están fuera del tema agrícola.

Si puedes responder la duda por ti mismo sin necesidad de un humano, simplemente responde sin añadir ninguna etiqueta.
"""

def get_venezuela_time():
    tz_ve = timezone(timedelta(hours=-4))
    return datetime.now(tz_ve)

def send_whatsapp_message(chat_id, text):
    url = f"https://api.green-api.com/waInstance{ID_INSTANCE}/sendMessage/{API_TOKEN_INSTANCE}"
    try:
        requests.post(url, json={"chatId": chat_id, "message": text})
    except Exception as e:
        print(f"[GREEN API ERROR]: {e}")

def consultar_gemini(texto_usuario, chat_id):
    now = get_venezuela_time()
    dias = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
    dia_semana = dias[now.weekday()]
    hora_str = now.strftime("%I:%M %p")
    
    # Se inyecta la hora actual para que el bot sepa si está fuera de horario
    contexto = f"Día Actual: {dia_semana}\nHora Actual: {hora_str}\nCliente: {texto_usuario}"
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{
            "parts": [{"text": f"{SYSTEM_PROMPT}\n\n{contexto}"}]
        }]
    }
    headers = {'Content-Type': 'application/json'}
    try:
        response = requests.post(url, headers=headers, json=payload)
        datos = response.json()
        if 'candidates' in datos:
            return datos['candidates'][0]['content']['parts'][0]['text'].strip()
        else:
            return "[ESCALAR_FACTURACION] Disculpa, tengo inconvenientes técnicos temporales. Te transferiré a administración."
    except Exception as e:
        return "[ESCALAR_FACTURACION] Ocurrió un error. Te pasaré con un asesor en breve."

@app.route('/webhook', methods=['POST'])
def webhook():
    body = request.get_json()
    if not body or body.get('typeWebhook') != 'incomingMessageReceived': 
        return 'OK', 200
        
    chat_id = body.get('senderData', {}).get('chatId')
    msg_type = body.get('messageData', {}).get('typeMessage')
    is_me = body.get('senderData', {}).get('isMe')

    if is_me:
        # Comandos de reactivación/pausa manual
        if msg_type in ['textMessage', 'extendedTextMessage']:
            text = body.get('messageData', {}).get('textMessageData', {}).get('textMessage', '') or \
                   body.get('messageData', {}).get('extendedTextMessageData', {}).get('text', '')
            if text.strip() == '/bot on': 
                chats_pausados.discard(chat_id)
            elif text.strip() == '/bot off': 
                chats_pausados.add(chat_id)
        return 'OK', 200

    if chat_id in chats_pausados: 
        return 'OK', 200

    # Procesar tiempo para las notificaciones
    now = get_venezuela_time()
    hora_str = now.strftime("%I:%M %p")
    num_cliente = chat_id.split('@')[0]

    # REGLA: FOTOS O ARCHIVOS DIRECTO A FACTURACIÓN (SEGÚN TUS INSTRUCCIONES)
    if msg_type not in ['textMessage', 'extendedTextMessage']:
        chats_pausados.add(chat_id)
        send_whatsapp_message(chat_id, "He recibido tu archivo. Una persona real lo revisará y te responderá en breve.")
        alerta = f"🔔 ALERTA DE ARCHIVO\n📞 Cliente: {num_cliente}\n⏰ Hora: {hora_str}\n🎯 Motivo: Envió documento, foto o audio."
        send_whatsapp_message(NUMERO_FACTURACION, alerta)
        return 'OK', 200

    # Procesamiento de Texto
    if msg_type == 'textMessage':
        text = body.get('messageData', {}).get('textMessageData', {}).get('textMessage', '')
    elif msg_type == 'extendedTextMessage':
        text = body.get('messageData', {}).get('extendedTextMessageData', {}).get('text', '')

    print(f"[NUEVO MENSAJE] {num_cliente}: {text}")
    reply = consultar_gemini(text, chat_id)
    
    destino_alerta = None
    motivo_alerta = ""

    # LÓGICA DE ENRUTAMIENTO (Se filtra la etiqueta para que el cliente no la vea)
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

    # Se envía el mensaje limpio al cliente
    if reply:
        send_whatsapp_message(chat_id, reply)

    # Si se activó alguna ruta de escalado, se pausa al bot y se envía la notificación completa
    if destino_alerta:
        chats_pausados.add(chat_id)
        # Recortamos el mensaje para que no sature la alerta si es muy largo
        texto_recortado = text[:150] + "..." if len(text) > 150 else text
        alerta_formateada = f"🔔 ASISTENCIA REQUERIDA\n📞 Cliente: {num_cliente}\n⏰ Hora: {hora_str}\n🎯 Departamento: {motivo_alerta}\n💬 Último mensaje: '{texto_recortado}'"
        send_whatsapp_message(destino_alerta, alerta_formateada)

    return 'OK', 200

if __name__ == '__main__':
    puerto = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=puerto)
