import os
import requests
import threading
import time
import json
import gspread
from flask import Flask, request
from datetime import datetime, timezone, timedelta

app = Flask(__name__)

# ==========================================
# CREDENCIALES
# ==========================================
ID_INSTANCE = os.getenv("ID_INSTANCE")
API_TOKEN_INSTANCE = os.getenv("API_TOKEN_INSTANCE")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# ==========================================
# RUTAS DE DEPARTAMENTOS Y PERMISOS
# ==========================================
NUMEROS_PERMITIDOS = ["584120326262@c.us", "584147178563@c.us", "584128222613@c.us"]
NUMERO_VENTAS = "584128222613@c.us"
NUMERO_TECNICO = "584247609075@c.us"
NUMERO_FACTURACION = "584247157087@c.us"

chats_pausados = {}

# ==========================================
# CEREBRO DEL BOT E INVENTARIO
# ==========================================
SYSTEM_PROMPT = """
Eres "Campo", el asistente virtual experto de la empresa Campo Salud, ubicada en Mucuchíes.
REGLA DE ORO (ESTILO): Eres directo, conciso y extremadamente profesional. Cero texto de relleno.
CAPACIDAD: Responde dudas agronómicas, veterinarias y proporciona precios y disponibilidad de inventario.

REGLAS DE INVENTARIO Y VENTAS:
1. Siempre revisa la "BASE DE DATOS" que se te proporciona dinámicamente en el contexto antes de dar un precio o confirmar disponibilidad.
2. Si un producto está con Stock "Agotado", infórmalo amablemente, no inventes precios ni intentes venderlo.
3. Si el cliente pide un producto que NO está en la base de datos, no especules. Escala la consulta a ventas.
4. Basa tus recomendaciones agronómicas en formulaciones exactas, recordando que utilizamos insumos como OMEX NK 60 (con 8.4% de nitrógeno), Byo-K 40 y Potten-T para el manejo nutricional y fitosanitario.

SISTEMA DE ESCALADO AUTOMÁTICO (ESTRICTO):
Si puedes dar la solución técnica o el precio por ti mismo, responde directamente SIN añadir ninguna etiqueta.
Si debes escalar, AÑADE UNA SOLA ETIQUETA al final:
[ESCALAR_VENTAS] -> Si piden cotizaciones por volumen alto, productos no listados, o desean concretar el pago.
[ESCALAR_TECNICO] -> Si la consulta requiere un diagnóstico avanzado de un ingeniero.
[ESCALAR_FACTURACION] -> Si hacen preguntas de envíos o facturación previa.
"""

def get_venezuela_time():
    return datetime.now(timezone(timedelta(hours=-4)))

def send_whatsapp_message(chat_id, text):
    url = f"https://api.green-api.com/waInstance{ID_INSTANCE}/sendMessage/{API_TOKEN_INSTANCE}"
    try:
        response = requests.post(url, json={"chatId": chat_id, "message": text}, timeout=10)
        if response.status_code != 200:
            print(f"[GREEN API RECHAZO] Código: {response.status_code} - Destino: {chat_id}", flush=True)
        else:
            print(f"[GREEN API ÉXITO] Mensaje entregado a {chat_id}", flush=True)
    except Exception as e:
        print(f"[GREEN API ERROR DE RED]: No se pudo conectar. Detalle: {e}", flush=True)

def obtener_inventario_sheets():
    """Conecta con Google Sheets, descarga el inventario en tiempo real y lo formatea."""
    try:
        credenciales_json = json.loads(os.environ.get('GOOGLE_CREDENTIALS'))
        gc = gspread.service_account_from_dict(credenciales_json)
        
        # El nombre debe coincidir exactamente con el título de tu archivo en Google Drive
        sh = gc.open("Inventario Campo Salud")
        hoja = sh.sheet1
        registros = hoja.get_all_records()
        
        lineas_inventario = ["=== BASE DE DATOS: PRECIOS Y DISPONIBILIDAD ==="]
        
        for fila in registros:
            # Busca exactamente la columna 'Descripción'
            producto = str(fila.get("Descripción", "")).strip()
            
            # Filtro de limpieza: ignora productos en blanco o códigos inactivos
            if not producto or producto == "." or "INACTIVO" in producto:
                continue
                
            precio = fila.get("Precio de venta", "N/A")
            stock = fila.get("Existencia", "N/A")
            
            # Formateo visual para que la IA entienda si hay o no disponibilidad
            try:
                stock_num = float(stock)
                estado = "Agotado" if stock_num <= 0 else f"Disponible ({stock_num})"
            except (ValueError, TypeError):
                estado = f"Disponible ({stock})"
            
            lineas_inventario.append(f"- {producto} | Precio: ${precio} | Stock: {estado}")
            
        return "\n".join(lineas_inventario)
    except Exception as e:
        print(f"[ERROR GOOGLE SHEETS]: {e}", flush=True)
        return "=== BASE DE DATOS ===\nEl inventario está temporalmente inaccesible. Escala la consulta a ventas."

def procesar_gemini_y_responder(chat_id, texto_usuario):
    print(f"\n[INICIANDO HILO] Analizando solicitud técnica y revisando inventario de {chat_id}...", flush=True)
    
    # Descarga el inventario en milisegundos
    inventario_actualizado = obtener_inventario_sheets()

    now = get_venezuela_time()
    hora_str = now.strftime("%I:%M %p")
    
    contexto = f"Hora Actual: {hora_str}\nCliente: {texto_usuario}\n\n{inventario_actualizado}"

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.6-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{
            "parts": [{"text": f"{SYSTEM_PROMPT}\n\n{contexto}"}]
        }]
    }
    headers = {'Content-Type': 'application/json'}

    intentos_maximos = 3
    
    for intento in range(intentos_maximos):
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=90)
            datos = response.json()

            if 'error' in datos and datos['error'].get('code') == 503:
                print(f"[ADVERTENCIA] Google saturado (Error 503). Reintento silencioso {intento + 1}/{intentos_maximos} en progreso...", flush=True)
                time.sleep(2)
                continue

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
                
                return

            print(f"[GEMINI ERROR INTERNO]: {datos}", flush=True)
            break 

        except requests.exceptions.RequestException as e:
            print(f"[ERROR DE RED] Falla en el intento {intento + 1}: {e}", flush=True)
            time.sleep(2)
            continue

    print("[ERROR CRÍTICO] Se agotaron los reintentos. Transfiriendo a un humano.", flush=True)
    send_whatsapp_message(chat_id, "Disculpa, tengo inconvenientes técnicos procesando el diagnóstico. Te transferiré a un asesor.")
    send_whatsapp_message(NUMERO_TECNICO, f"⚠️ ALERTA: Fallo de conexión IA con el cliente {chat_id.split('@')[0]}")

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

        if chat_id in chats_pausados:
            diferencia = now - chats_pausados[chat_id]
            if diferencia >= timedelta(hours=2):
                chats_pausados.pop(chat_id, None)
                print(f"[REINICIO AUTOMÁTICO DE SESIÓN] Límite de 2 horas superado para {chat_id}", flush=True)
            else:
                return 'OK', 200

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

        hilo = threading.Thread(target=procesar_gemini_y_responder, args=(chat_id, texto_usuario))
        hilo.start()

        return 'OK', 200

    except Exception as e:
        print(f"[CRITICAL WEBHOOK ERROR]: {e}", flush=True)
        return 'OK', 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
