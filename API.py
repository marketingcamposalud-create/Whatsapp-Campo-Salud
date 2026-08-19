import os
import requests
import threading
import time
import json
import gspread
import re  # NUEVA LIBRERÍA: Para analizar palabras clave
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

# ==========================================
# CEREBRO DEL BOT
# ==========================================
SYSTEM_PROMPT = """
Eres "Campo", el asistente virtual experto de la empresa Campo Salud, ubicada en Mucuchíes.
REGLA DE ORO (ESTILO): Eres directo, conciso y extremadamente profesional. Cero texto de relleno.
CAPACIDAD: Responde dudas agronómicas, veterinarias y proporciona precios de los resultados del inventario.

REGLAS DE INVENTARIO Y VENTAS:
1. Revisa los "RESULTADOS DEL INVENTARIO" que se te proporcionan en el contexto. Estos resultados ya fueron filtrados según lo que pidió el cliente.
2. Si un producto dice "Agotado", infórmalo amablemente.
3. Si el contexto dice "Producto no encontrado", no inventes precios. Escala a ventas.
4. Basa tus recomendaciones en insumos propios como OMEX NK 60 (8.4% N), Byo-K 40 y Potten-T.

SISTEMA DE ESCALADO AUTOMÁTICO (ESTRICTO):
Si puedes dar la solución o el precio por ti mismo, responde directamente SIN añadir etiqueta.
Si debes escalar, AÑADE UNA SOLA ETIQUETA al final:
[ESCALAR_VENTAS] -> Si piden cotizaciones mayores, productos no listados, o desean comprar.
[ESCALAR_TECNICO] -> Si requiere diagnóstico avanzado de un ingeniero.
[ESCALAR_FACTURACION] -> Si hacen preguntas de envíos o facturación previa.
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

# ==========================================
# MOTOR DE BÚSQUEDA (EL AHORRADOR DE DINERO)
# ==========================================
def obtener_inventario_filtrado(texto_usuario):
    """Busca en Google Sheets SOLO los productos que mencionó el cliente para ahorrar costos de IA."""
    try:
        # Extraemos palabras de más de 3 letras del mensaje del cliente
        palabras_usuario = re.findall(r'\b[a-zA-ZáéíóúÁÉÍÓÚñÑ]{4,}\b', texto_usuario.lower())
        
        # Palabras comunes que no son productos, para que el buscador las ignore
        ignoradas = {'hola', 'buenas', 'tardes', 'días', 'dias', 'tienen', 'precio', 'cuanto', 'cuesta', 'quiero', 'necesito', 'para', 'como', 'estan', 'estoy', 'ustedes'}
        claves_utiles = [p for p in palabras_usuario if p not in ignoradas]
        
        # Si el cliente solo dice "Hola" o una duda veterinaria sin mencionar un producto, no descargamos la base de datos
        if not claves_utiles:
            return "=== RESULTADOS DEL INVENTARIO ===\nNo se solicitaron productos específicos."

        credenciales_json = json.loads(os.environ.get('GOOGLE_CREDENTIALS'))
        gc = gspread.service_account_from_dict(credenciales_json)
        sh = gc.open("Inventario Campo Salud")
        hoja = sh.sheet1
        matriz = hoja.get_all_values()
        
        idx_desc, idx_precio, idx_stock, fila_inicio = -1, -1, -1, 0
        
        for i, fila in enumerate(matriz):
            fila_limpia = [str(celda).strip().lower() for celda in fila]
            if "descripción" in fila_limpia or "descripcion" in fila_limpia:
                idx_desc = fila_limpia.index("descripción") if "descripción" in fila_limpia else fila_limpia.index("descripcion")
                idx_precio = fila_limpia.index("precio de venta") if "precio de venta" in fila_limpia else fila_limpia.index("precio") if "precio" in fila_limpia else -1
                idx_stock = fila_limpia.index("existencia") if "existencia" in fila_limpia else fila_limpia.index("stock") if "stock" in fila_limpia else -1
                fila_inicio = i + 1
                break
        
        if idx_desc == -1: return "Error interno: Columnas no encontradas."
        
        lineas_inventario = ["=== RESULTADOS DEL INVENTARIO (FILTRADO) ==="]
        coincidencias = 0
        
        for fila in matriz[fila_inicio:]:
            if len(fila) <= max(idx_desc, idx_precio, idx_stock): continue
                
            producto_original = str(fila[idx_desc]).strip()
            producto_lower = producto_original.lower()
            
            if not producto_original or producto_original == "." or "inactivo" in producto_lower: continue
            
            # MAGIA TÉCNICA: Si el nombre del producto en el Excel contiene alguna palabra clave del cliente, lo extrae
            if any(clave in producto_lower for clave in claves_utiles):
                precio = str(fila[idx_precio]).strip() or "N/A"
                stock = str(fila[idx_stock]).strip() or "N/A"
                
                try:
                    stock_num = float(stock.replace(',', '.'))
                    estado = "Agotado" if stock_num <= 0 else f"Disponible ({stock_num})"
                except ValueError:
                    estado = f"Disponible ({stock})"
                
                lineas_inventario.append(f"- {producto_original} | Precio: ${precio} | Stock: {estado}")
                coincidencias += 1
                
                # Límite de seguridad: Si encuentra más de 20 coincidencias, se detiene para no saturar tokens
                if coincidencias >= 20:
                    lineas_inventario.append("... (Múltiples resultados encontrados, especifique más su búsqueda).")
                    break
        
        if coincidencias == 0:
            return "=== RESULTADOS DEL INVENTARIO ===\nProducto no encontrado. Escalar a ventas para verificar disponibilidad manual."
            
        return "\n".join(lineas_inventario)
        
    except Exception as e:
        print(f"[ERROR BUSCADOR INTERNO]: {e}", flush=True)
        return "El inventario está temporalmente inaccesible."

def procesar_gemini_y_responder(chat_id, texto_usuario):
    print(f"\n[INICIANDO HILO] Consultando para: {chat_id}...", flush=True)
    
    # Ahora Python solo extrae lo estrictamente necesario
    inventario_filtrado = obtener_inventario_filtrado(texto_usuario)

    now = get_venezuela_time()
    hora_str = now.strftime("%I:%M %p")
    contexto = f"Hora Actual: {hora_str}\nCliente: {texto_usuario}\n\n{inventario_filtrado}"

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.6-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {"contents": [{"parts": [{"text": f"{SYSTEM_PROMPT}\n\n{contexto}"}]}]}
    headers = {'Content-Type': 'application/json'}

    for intento in range(3):
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=90)
            datos = response.json()

            if 'error' in datos and datos['error'].get('code') == 503:
                time.sleep(2)
                continue

            if 'candidates' in datos:
                reply = datos['candidates'][0]['content']['parts'][0]['text'].strip()
                print("[RESPUESTA EXITOSA]", flush=True)

                destino = None
                if "[ESCALAR_VENTAS]" in reply: destino = NUMERO_VENTAS
                elif "[ESCALAR_TECNICO]" in reply: destino = NUMERO_TECNICO
                elif "[ESCALAR_FACTURACION]" in reply: destino = NUMERO_FACTURACION

                if destino:
                    chats_pausados[chat_id] = now
                    reply_limpia = reply.replace("[ESCALAR_VENTAS]", "").replace("[ESCALAR_TECNICO]", "").replace("[ESCALAR_FACTURACION]", "").strip()
                    send_whatsapp_message(chat_id, reply_limpia)
                    send_whatsapp_message(destino, f"⚠️ ALERTA\nCliente: {chat_id.split('@')[0]}\nRespuesta: {reply_limpia}")
                else:
                    send_whatsapp_message(chat_id, reply)
                return

            break 
        except requests.exceptions.RequestException:
            time.sleep(2)
            continue

    send_whatsapp_message(chat_id, "Disculpa, tengo inconvenientes técnicos. Te transferiré a un asesor.")
    send_whatsapp_message(NUMERO_TECNICO, f"⚠️ Fallo de IA con {chat_id.split('@')[0]}")

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        body = request.get_json()
        if not body or body.get('typeWebhook') != 'incomingMessageReceived': return 'OK', 200

        chat_id = body.get('senderData', {}).get('chatId')
        msg_type = body.get('messageData', {}).get('typeMessage')
        is_me = body.get('senderData', {}).get('isMe')
        now = get_venezuela_time()

        if chat_id not in NUMEROS_PERMITIDOS and not is_me: return 'OK', 200

        if is_me:
            text = body.get('messageData', {}).get('textMessageData', {}).get('textMessage', '') or body.get('messageData', {}).get('extendedTextMessageData', {}).get('text', '')
            text_lower = text.lower()
            if text.strip() == '/bot on': chats_pausados.pop(chat_id, None)
            elif text.strip() == '/bot off': chats_pausados[chat_id] = now
            elif any(frase in text_lower for frase in ["feliz dia", "feliz día", "feliz tarde", "feliz noche", "estamos a la orden", "a su orden", "hasta luego", "gracias por preferirnos"]):
                chats_pausados.pop(chat_id, None)
            return 'OK', 200

        if chat_id in chats_pausados:
            if now - chats_pausados[chat_id] >= timedelta(hours=2): chats_pausados.pop(chat_id, None)
            else: return 'OK', 200

        texto_usuario = ""
        if msg_type == 'textMessage': texto_usuario = body.get('messageData', {}).get('textMessageData', {}).get('textMessage', '')
        elif msg_type == 'extendedTextMessage': texto_usuario = body.get('messageData', {}).get('extendedTextMessageData', {}).get('text', '')

        if msg_type not in ['textMessage', 'extendedTextMessage'] or not texto_usuario.strip():
            chats_pausados[chat_id] = now
            send_whatsapp_message(chat_id, "Archivo recibido. Un técnico lo revisará en breve.")
            send_whatsapp_message(NUMERO_FACTURACION, f"🚨 ARCHIVO RECIBIDO\nCliente: {chat_id.split('@')[0]}")
            return 'OK', 200

        print(f"\n[NUEVO MENSAJE] {chat_id.split('@')[0]}: {texto_usuario}", flush=True)
        threading.Thread(target=procesar_gemini_y_responder, args=(chat_id, texto_usuario)).start()
        return 'OK', 200
    except Exception:
        return 'OK', 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
