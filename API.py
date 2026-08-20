import os
import requests
import threading
import time
import json
import gspread
import re
from flask import Flask, request
from datetime import datetime, timezone, timedelta

app = Flask(__name__)

# ==========================================
# CREDENCIALES Y RUTAS
# ==========================================
ID_INSTANCE = os.getenv("ID_INSTANCE")
API_TOKEN_INSTANCE = os.getenv("API_TOKEN_INSTANCE")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

NUMEROS_PERMITIDOS = ["584120326262@c.us", "584147178563@c.us", "584128222613@c.us"]
NUMERO_VENTAS = "584128222613@c.us"
NUMERO_TECNICO = "584247609075@c.us"
NUMERO_FACTURACION = "584247157087@c.us"

chats_pausados = {}
historial_chats = {}

# ==========================================
# MEMORIA CACHÉ GLOBAL (ALTA VELOCIDAD)
# ==========================================
CACHE_INVENTARIO = {
    "matriz": [],
    "idx_desc": -1,
    "idx_precio": -1,
    "idx_stock": -1,
    "fila_inicio": 0,
    "ultima_actualizacion": 0
}

# ==========================================
# CEREBRO DEL BOT
# ==========================================
SYSTEM_PROMPT = """
Eres "Campo", el asistente virtual y asesor de ventas de Campo Salud, ubicada en Mucuchíes.
REGLA DE ORO (ESTILO): Eres directo, conciso y extremadamente profesional. Cero texto de relleno.
CAPACIDAD: Responde dudas agronómicas, veterinarias y CIERRA VENTAS DE FORMA AUTÓNOMA.

DATOS BANCARIOS DE CAMPO SALUD, C.A. (RIF: J-310112029):
- Pago Móvil Provincial (0108): Teléfono 0412-7178563
- Pago Móvil B. de Venezuela (0102): Teléfono 0412-7178563
- Transferencia Provincial: Cuenta Corriente 0108-0114-16-0100025892

HORARIO DE ATENCIÓN Y LOGÍSTICA:
- Lunes a Viernes: 8:00 AM a 12:00 PM y de 2:00 PM a 5:00 PM.
- Sábados y Domingos: CERRADO.
- REGLA ESTRICTA FUERA DE HORARIO: Revisa detenidamente el "Día Actual" y la "Hora Actual" provistos en el contexto. Si el horario actual NO está dentro del rango laboral, NO puedes concretar ventas, dar datos de pago, ni transferir la conversación a un humano. Debes informar amablemente que la tienda física está cerrada, indicar el horario de atención, y aclarar que las compras y el soporte directo se retomarán al abrir. Puedes seguir respondiendo dudas técnicas 24/7.

REGLAS DE INVENTARIO Y CIERRE DE VENTAS:
1. Revisa el "HISTORIAL DE CONVERSACIÓN RECIENTE" para recordar el contexto.
2. Revisa los "RESULTADOS DEL INVENTARIO". Si un producto está "Agotado", infórmalo, no inventes precios.
3. CIERRE AUTÓNOMO: Si el cliente confirma que desea comprar un producto disponible, calcula el total a pagar, proporciónale INMEDIATAMENTE los datos bancarios y pídele que envíe el comprobante (foto o referencia) por este mismo chat.
4. Basa tus recomendaciones en insumos propios como OMEX NK 60 (8.4% N), Byo-K 40 y Potten-T.
5. CONSOLIDACIÓN DE MENSAJES: Si notas en el historial que el cliente envió varios mensajes cortos y fragmentados uno tras otro, responde UNA SOLA VEZ abordando toda la idea junta. No des respuestas fragmentadas.

SISTEMA DE ESCALADO AUTOMÁTICO (ESTRICTO):
Si estás asesorando, dando precios o concretando una venta normal, responde directamente SIN añadir etiqueta.
ÚNICAMENTE AÑADE UNA ETIQUETA AL FINAL en estos casos:
[ESCALAR_FACTURACION] -> SI EL CLIENTE ENVÍA UN NÚMERO DE REFERENCIA DE PAGO ESCRITO o tiene un problema de facturación.
[ESCALAR_VENTAS] -> Solo si piden cotizaciones de muy alto volumen o productos que no están en el inventario.
[ESCALAR_TECNICO] -> Solo si la consulta requiere un diagnóstico muy complejo de un ingeniero.
"""

def get_venezuela_time():
    return datetime.now(timezone(timedelta(hours=-4)))

def send_whatsapp_message(chat_id, text):
    url = f"https://api.green-api.com/waInstance{ID_INSTANCE}/sendMessage/{API_TOKEN_INSTANCE}"
    try:
        response = requests.post(url, json={"chatId": chat_id, "message": text}, timeout=10)
        if response.status_code != 200:
            print(f"[GREEN API RECHAZO] Código: {response.status_code}", flush=True)
    except Exception as e:
        print(f"[GREEN API ERROR DE RED]: {e}", flush=True)

def obtener_inventario_filtrado(texto_busqueda):
    global CACHE_INVENTARIO
    try:
        palabras_usuario = re.findall(r'\b[a-zA-ZáéíóúÁÉÍÓÚñÑ0-9]{2,}\b', texto_busqueda.lower())
        ignoradas = {'hola', 'buenas', 'tardes', 'días', 'dias', 'tienen', 'precio', 'cuanto', 'cuesta', 'quiero', 'necesito', 'para', 'como', 'estan', 'estoy', 'ustedes', 'comprar', 'unas', 'pero', 'ahora', 'poco', 'tonto', 'mejorar', 'eso', 'esto', 'aqui', 'aquí', 'dijiste', 'tiene', 'estaba', 'cual', 'quien', 'donde', 'que', 'con', 'del', 'los', 'las', 'pago', 'movil', 'cuenta', 'transferencia', 'listo', 'ya', 'pague'}
        claves_utiles = [p for p in palabras_usuario if p not in ignoradas]
        
        if not claves_utiles:
            return "=== RESULTADOS DEL INVENTARIO ===\nNo se detectaron productos específicos para buscar en la base de datos en este momento."

        tiempo_actual = time.time()
        
        if tiempo_actual - CACHE_INVENTARIO["ultima_actualizacion"] > 900 or not CACHE_INVENTARIO["matriz"]:
            print("[SISTEMA CACHÉ] Descargando base de datos desde Google Sheets...", flush=True)
            credenciales_json = json.loads(os.environ.get('GOOGLE_CREDENTIALS'))
            gc = gspread.service_account_from_dict(credenciales_json)
            sh = gc.open("Inventario Campo Salud")
            hoja = sh.sheet1
            matriz_cruda = hoja.get_all_values()
            
            idx_desc, idx_precio, idx_stock, fila_inicio = -1, -1, -1, 0
            
            for i, fila in enumerate(matriz_cruda):
                fila_limpia = [str(celda).strip().lower() for celda in fila]
                if "descripción" in fila_limpia or "descripcion" in fila_limpia:
                    idx_desc = fila_limpia.index("descripción") if "descripción" in fila_limpia else fila_limpia.index("descripcion")
                    idx_precio = fila_limpia.index("precio de venta") if "precio de venta" in fila_limpia else fila_limpia.index("precio") if "precio" in fila_limpia else -1
                    idx_stock = fila_limpia.index("existencia") if "existencia" in fila_limpia else fila_limpia.index("stock") if "stock" in fila_limpia else -1
                    fila_inicio = i + 1
                    break
            
            if idx_desc != -1:
                CACHE_INVENTARIO["matriz"] = matriz_cruda
                CACHE_INVENTARIO["idx_desc"] = idx_desc
                CACHE_INVENTARIO["idx_precio"] = idx_precio
                CACHE_INVENTARIO["idx_stock"] = idx_stock
                CACHE_INVENTARIO["fila_inicio"] = fila_inicio
                CACHE_INVENTARIO["ultima_actualizacion"] = tiempo_actual
                print("[SISTEMA CACHÉ] Actualización exitosa. Datos guardados en RAM.", flush=True)
            else:
                return "Error interno: Columnas de inventario no encontradas."

        matriz = CACHE_INVENTARIO["matriz"]
        idx_desc = CACHE_INVENTARIO["idx_desc"]
        idx_precio = CACHE_INVENTARIO["idx_precio"]
        idx_stock = CACHE_INVENTARIO["idx_stock"]
        fila_inicio = CACHE_INVENTARIO["fila_inicio"]
        
        resultados = []
        
        for fila in matriz[fila_inicio:]:
            if len(fila) <= max(idx_desc, idx_precio, idx_stock): continue
                
            producto_original = str(fila[idx_desc]).strip()
            producto_lower = producto_original.lower()
            
            if not producto_original or producto_original == "." or "inactivo" in producto_lower: continue
            
            # MAGIA TÉCNICA 2.0: Sistema de Puntuación (Scoring)
            # Le da 1 punto por cada palabra clave que coincida
            score = sum(1 for clave in claves_utiles if clave in producto_lower)
            
            if score > 0:
                precio = str(fila[idx_precio]).strip() or "N/A"
                stock = str(fila[idx_stock]).strip() or "N/A"
                
                try:
                    stock_num = float(stock.replace(',', '.'))
                    estado = "Agotado" if stock_num <= 0 else f"Disponible ({stock_num})"
                except ValueError:
                    estado = f"Disponible ({stock})"
                
                resultados.append({
                    "texto": f"- {producto_original} | Precio: ${precio} | Stock: {estado}",
                    "score": score
                })
        
        # Ordenamos los resultados: los que tienen más coincidencias van de primeros
        resultados = sorted(resultados, key=lambda x: x['score'], reverse=True)
        
        if not resultados:
            return "=== RESULTADOS DEL INVENTARIO ===\nProducto no encontrado. Recomienda alternativas o escala a ventas."
            
        lineas_inventario = ["=== RESULTADOS DEL INVENTARIO (FILTRADO POR RELEVANCIA) ==="]
        # Le enviamos a la IA únicamente los 30 productos MÁS relevantes
        for res in resultados[:30]: 
            lineas_inventario.append(res["texto"])
            
        if len(resultados) > 30:
            lineas_inventario.append("... (Se omitieron resultados menos relevantes).")
            
        return "\n".join(lineas_inventario)
        
    except Exception as e:
        print(f"[ERROR BUSCADOR INTERNO]: {e}", flush=True)
        return "El inventario está temporalmente inaccesible."

def procesar_gemini_y_responder(chat_id, texto_usuario):
    print(f"\n[INICIANDO HILO] Consultando para: {chat_id}...", flush=True)
    
    if chat_id not in historial_chats:
        historial_chats[chat_id] = []
        
    texto_contexto_busqueda = texto_usuario
    for msg in reversed(historial_chats[chat_id]):
        if msg.startswith("Cliente:"):
            texto_contexto_busqueda = msg.replace("Cliente:", "").strip() + " " + texto_usuario
            break
            
    inventario_filtrado = obtener_inventario_filtrado(texto_contexto_busqueda)

    historial_chats[chat_id].append(f"Cliente: {texto_usuario}")
    if len(historial_chats[chat_id]) > 6:
        historial_chats[chat_id].pop(0)

    now = get_venezuela_time()
    hora_str = now.strftime("%I:%M %p")
    
    dias = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
    dia_actual = dias[now.weekday()]
    
    bloque_historial = "\n".join(historial_chats[chat_id])
    
    contexto = f"Día Actual: {dia_actual}\nHora Actual: {hora_str}\n\n{inventario_filtrado}\n\n=== HISTORIAL DE CONVERSACIÓN RECIENTE ===\n{bloque_historial}\nCampo (Tú):"

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.6-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {"contents": [{"parts": [{"text": f"{SYSTEM_PROMPT}\n\n{contexto}"}]}]}
    headers = {'Content-Type': 'application/json'}

    for intento in range(3):
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=35)
            datos = response.json()

            if 'error' in datos and datos['error'].get('code') == 503:
                time.sleep(1)
                continue

            if 'candidates' in datos:
                reply = datos['candidates'][0]['content']['parts'][0]['text'].strip()
                print("[RESPUESTA EXITOSA]", flush=True)

                historial_chats[chat_id].append(f"Campo (Tú): {reply}")
                if len(historial_chats[chat_id]) > 6:
                    historial_chats[chat_id].pop(0)

                destino = None
                if "[ESCALAR_VENTAS]" in reply: destino = NUMERO_VENTAS
                elif "[ESCALAR_TECNICO]" in reply: destino = NUMERO_TECNICO
                elif "[ESCALAR_FACTURACION]" in reply: destino = NUMERO_FACTURACION

                if destino:
                    chats_pausados[chat_id] = now
                    reply_limpia = reply.replace("[ESCALAR_VENTAS]", "").replace("[ESCALAR_TECNICO]", "").replace("[ESCALAR_FACTURACION]", "").strip()
                    send_whatsapp_message(chat_id, reply_limpia)
                    
                    if destino == NUMERO_FACTURACION:
                        send_whatsapp_message(destino, f"🚨 ALERTA DE PAGO REALIZADO\nCliente: {chat_id.split('@')[0]}\nVerifica la referencia o comprobante en WhatsApp.\nMensaje del bot: {reply_limpia}")
                    else:
                        send_whatsapp_message(destino, f"⚠️ ALERTA DE ASISTENCIA\nCliente: {chat_id.split('@')[0]}\nRespuesta: {reply_limpia}")
                else:
                    send_whatsapp_message(chat_id, reply)
                return

            break 
        except requests.exceptions.RequestException:
            print(f"[IA REINTENTO] Tiempo de espera agotado. Lanzando intento {intento + 2}...", flush=True)
            time.sleep(1)
            continue

    send_whatsapp_message(chat_id, "Disculpa, tengo inconvenientes de conexión en este instante. Te transferiré a un asesor.")
    send_whatsapp_message(NUMERO_TECNICO, f"⚠️ Fallo de IA (Timeout) con {chat_id.split('@')[0]}")

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        body = request.get_json()
        if not body or body.get('typeWebhook') != 'incomingMessageReceived': return 'OK', 200

        chat_id = body.get('senderData', {}).get('chatId')
        msg_type = body.get('messageData', {}).get('typeMessage')
        is_me = body.get('senderData', {}).get('isMe')
        now = get_venezuela_time()

        if is_me:
            text = body.get('messageData', {}).get('textMessageData', {}).get('textMessage', '') or body.get('messageData', {}).get('extendedTextMessageData', {}).get('text', '')
            text_lower = text.lower()
            if text.strip() == '/bot on': chats_pausados.pop(chat_id, None)
            elif text.strip() == '/bot off': chats_pausados[chat_id] = now
            elif any(frase in text_lower for frase in ["feliz dia", "feliz día", "feliz tarde", "feliz noche", "estamos a la orden", "a su orden", "hasta luego", "gracias por preferirnos"]):
                chats_pausados.pop(chat_id, None)
                historial_chats.pop(chat_id, None)
            return 'OK', 200

        if chat_id in chats_pausados:
            dias = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
            dia_actual = dias[now.weekday()]
            hora_actual_decimal = now.hour + now.minute / 60.0
            es_horario_laboral = (dia_actual not in ["Sábado", "Domingo"]) and ((8.0 <= hora_actual_decimal < 12.0) or (14.0 <= hora_actual_decimal < 17.0))
            
            if now - chats_pausados[chat_id] >= timedelta(hours=2) and es_horario_laboral: 
                chats_pausados.pop(chat_id, None)
                historial_chats.pop(chat_id, None)
            else: 
                print(f"[CHAT PAUSADO EN SILENCIO] Mensaje de {chat_id} ignorado para no interrumpir al humano.", flush=True)
                return 'OK', 200

        texto_usuario = ""
        if msg_type == 'textMessage': texto_usuario = body.get('messageData', {}).get('textMessageData', {}).get('textMessage', '')
        elif msg_type == 'extendedTextMessage': texto_usuario = body.get('messageData', {}).get('extendedTextMessageData', {}).get('text', '')

        # GESTIÓN DE COMPROBANTES DE PAGO Y HORARIOS
        if msg_type not in ['textMessage', 'extendedTextMessage'] or not texto_usuario.strip():
            chats_pausados[chat_id] = now
            
            dias = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
            dia_actual = dias[now.weekday()]
            hora_actual_decimal = now.hour + now.minute / 60.0
            es_horario_laboral = (dia_actual not in ["Sábado", "Domingo"]) and ((8.0 <= hora_actual_decimal < 12.0) or (14.0 <= hora_actual_decimal < 17.0))
            
            if es_horario_laboral:
                send_whatsapp_message(chat_id, "Hemos recibido tu comprobante/archivo. Nuestro equipo validará la información en sistema y te contactará en breve para concretar la entrega.")
                send_whatsapp_message(NUMERO_FACTURACION, f"🚨 COMPROBANTE DE PAGO RECIBIDO\nCliente: {chat_id.split('@')[0]}\nRevisa el chat de WhatsApp para verificar el capture/documento.")
            else:
                send_whatsapp_message(chat_id, "Hemos recibido tu comprobante/archivo. La tienda física se encuentra cerrada en este momento. Procesaremos tu solicitud a primera hora en nuestro próximo bloque de atención laboral.")
                send_whatsapp_message(NUMERO_FACTURACION, f"🚨 COMPROBANTE DE PAGO RECIBIDO (FUERA DE HORARIO)\nCliente: {chat_id.split('@')[0]}")
            
            return 'OK', 200

        print(f"\n[NUEVO MENSAJE] {chat_id.split('@')[0]}: {texto_usuario}", flush=True)
        threading.Thread(target=procesar_gemini_y_responder, args=(chat_id, texto_usuario)).start()
        return 'OK', 200
    except Exception as e:
        print(f"[CRITICAL WEBHOOK ERROR]: {e}", flush=True)
        return 'OK', 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
