import asyncio
import re
import requests
import json
import datetime
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from mongodb import MongoDB
import concurrent.futures

# ==================== CONFIGURACIÓN ====================
BOT_TOKEN = "8781844368:AAGYSjS3xiHJK_Je7BC_YVd6M9Btw07XMhw"
DEVELOPER_ID = 5962220190
ADMIN_2_ID = 1233826268

# Inicializar MongoDB
db = MongoDB()

# ThreadPoolExecutor para tareas en segundo plano
executor = concurrent.futures.ThreadPoolExecutor(max_workers=10)

# Silenciar logs
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('telegram').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)
logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==================== CLASE TELCEL CONSULTA ====================
class TelcelConsulta:
    def __init__(self):
        self.session = requests.Session()
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Mobile Safari/537.36',
            'Accept': 'application/json, text/javascript, */*; q=0.01',
            'Accept-Language': 'es-ES,es;q=0.5',
            'Content-Type': 'application/json',
            'Origin': 'https://www.mitelcel.com',
            'Referer': 'https://www.mitelcel.com/mitelcel/consumo-datos/claro',
            'X-Requested-With': 'XMLHttpRequest',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-origin',
            'Sec-GPC': '1'
        }
        self._init_session()

    def _init_session(self):
        iframe_url = 'https://www.mitelcel.com/mitelcel/consumo-datos/claro?token=cCFA2BghfcciB2M93HDylaHmfBnuY2fFlvl2xQ2eiDASf%2FzhNcDlO14mDjk5MZEN'
        try:
            resp = self.session.get(iframe_url, headers={
                'User-Agent': self.headers['User-Agent'],
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
                'Accept-Language': 'es-ES,es;q=0.5',
                'Referer': 'https://pay.telcel.com/',
                'Sec-Fetch-Dest': 'iframe',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'cross-site',
                'Sec-Fetch-User': '?1'
            })
            resp.raise_for_status()
        except Exception as e:
            print(f"⚠️ Error al obtener sesión Telcel: {e}")

    def consultar(self, telefono, region='4', perfil='AMIGO'):
        url = 'https://www.mitelcel.com/mitelcel/mitelcel-api-web/api/prepago/internet/frame-consumos'
        payload = {"telefono": telefono, "region": region, "perfil": perfil}
        self.headers['Referer'] = f'https://www.mitelcel.com/mitelcel/consumo-datos/claro?token=cCFA2BghfcciB2M93HDylaHmfBnuY2fFlvl2xQ2eiDASf%2FzhNcDlO14mDjk5MZEN'
        try:
            resp = self.session.post(url, json=payload, headers=self.headers)
            resp.raise_for_status()
            data = resp.json()
            print(f"[TELCEL] Respuesta para {telefono}:\n{json.dumps(data, indent=2, ensure_ascii=False)}")
            return data
        except Exception as e:
            print(f"Error consulta Telcel para {telefono}: {e}")
            return None

    def obtener_iniciales(self, nombre):
        palabras_clave = {
            'sin limite': 'SL', 'sin límite': 'SL',
            'internet por tiempo': 'IT', 'bolsa de datos': 'BD',
            'paquete prepagado': 'PP', 'prepagado': 'PP',
            'datos': 'DT', 'redes sociales': 'RS',
            'whatsapp': 'WA', 'facebook': 'FB',
            'instagram': 'IG', 'youtube': 'YT',
            'tiktok': 'TK', 'spotify': 'SP'
        }
        nombre_lower = nombre.lower()
        for clave, abrev in palabras_clave.items():
            if clave in nombre_lower:
                return abrev
        palabras = nombre.split()
        if len(palabras) >= 2:
            iniciales = ''.join([p[0].upper() for p in palabras if len(p) > 2])
            if len(iniciales) >= 2:
                return iniciales[:2]
        return nombre[:2].upper()

    def formatear_paquetes(self, numero, data):
        if not data:
            return None, None
        respuesta = data.get('response', {})
        mensaje = respuesta.get('message', {})
        if mensaje.get('codigoError') == "MDN_NOT_FOUND":
            return None, "no_telcel"
        data_consumo = respuesta.get('data', {})
        consumos = data_consumo.get('consumos', [])
        if not consumos:
            return None, "sin_paquetes"
        paquetes = []
        for consumo in consumos:
            nombre = consumo.get('nombreProducto', '')
            mb_totales = consumo.get('mbTotales', 0)
            if mb_totales > 0:
                abrev = self.obtener_iniciales(nombre)
                match = re.search(r'(\d+)', nombre)
                if match:
                    paquetes.append(f"{abrev}{match.group(1)}")
                else:
                    paquetes.append(f"{abrev}{int(mb_totales)}")
        if paquetes:
            return f"✅{numero} {paquetes[0]}", "ok"
        return None, "sin_paquetes"

    def formatear_saldo(self, numero, data):
        if not data:
            return None, None
        respuesta = data.get('response', {})
        mensaje = respuesta.get('message', {})
        if mensaje.get('codigoError') == "MDN_NOT_FOUND":
            return None, "no_telcel"
        data_consumo = respuesta.get('data', {})
        sumatoria = data_consumo.get('sumatoria', {})
        if sumatoria and sumatoria.get('mbDisponibles', 0) > 0:
            return f"✅{numero} {sumatoria.get('mbDisponibles', 0)}MB", "ok"
        consumos = data_consumo.get('consumos', [])
        total_mb = sum(consumo.get('mbDisponibles', 0) for consumo in consumos)
        if total_mb > 0:
            return f"✅{numero} {total_mb}MB", "ok"
        return None, "sin_saldo"

    def formatear_balance(self, numero, data):
        if not data:
            return f"❌ Error al consultar el número {numero}", None
        respuesta = data.get('response', {})
        mensaje = respuesta.get('message', {})
        if mensaje.get('codigoError') == "MDN_NOT_FOUND":
            return None, "no_telcel"
        lineas = [f"📱 NÚMERO: {numero}", ""]
        data_consumo = respuesta.get('data', {})
        fecha_act = data_consumo.get('fechaActualizacion', '')
        if fecha_act:
            lineas.append(f"Última actualización: {fecha_act}")
        lineas.append("")
        consumos = data_consumo.get('consumos', [])
        if not consumos:
            lineas.append("Sin paquetes activos.")
        else:
            for idx, consumo in enumerate(consumos, 1):
                if idx > 1:
                    lineas.append("")
                lineas.append(f"PAQUETE {idx}")
                lineas.append(f"Nombre: {consumo.get('nombreProducto', 'N/A')}")
                lineas.append(f"Tipo: {consumo.get('tipoPaquete', 'N/A')}")
                lineas.append(f"Megas totales: {consumo.get('mbTotales', 0)} MB")
                lineas.append(f"Megas usados: {consumo.get('mbUsados', 0)} MB")
                lineas.append(f"Megas disponibles: {consumo.get('mbDisponibles', 0)} MB")
                lineas.append(f"Porcentaje consumido: {consumo.get('porcentajeConsumido', 0)}%")
                if consumo.get('fechaActivacion'):
                    ts = consumo['fechaActivacion'] / 1000
                    lineas.append(f"Activación: {datetime.datetime.fromtimestamp(ts).strftime('%d/%m/%Y %H:%M')}")
                if consumo.get('fechaExpiracion'):
                    ts = consumo['fechaExpiracion'] / 1000
                    lineas.append(f"Expiración: {datetime.datetime.fromtimestamp(ts).strftime('%d/%m/%Y %H:%M')}")
        sumatoria = data_consumo.get('sumatoria')
        if sumatoria and sumatoria.get('mbIncluidos'):
            lineas.append("")
            lineas.append("--- RESUMEN TOTAL ---")
            lineas.append(f"Megas incluidos: {sumatoria.get('mbIncluidos', 0)} MB")
            lineas.append(f"Megas usados: {sumatoria.get('mbUsados', 0)} MB")
            lineas.append(f"Megas disponibles: {sumatoria.get('mbDisponibles', 0)} MB")
        return "\n".join(lineas), "ok"

# ==================== FUNCIONES AUXILIARES ====================
def parse_phone_numbers(text):
    return re.findall(r'\b(\d{10})\b', text)

def is_admin(user_id):
    if user_id == DEVELOPER_ID or user_id == ADMIN_2_ID:
        return True
    return db.admin(user_id)

def is_developer(user_id):
    return user_id == DEVELOPER_ID

def is_premium(user_id):
    user = db.query_user(user_id)
    if not user:
        return False
    premium_until = user.get('premium_until')
    if not premium_until:
        return False
    if premium_until <= datetime.datetime.now():
        return False
    return True

def can_use_bot(user_id):
    if db.is_banned(user_id):
        return False, "baneado"
    if is_admin(user_id):
        return True, "admin"
    if is_premium(user_id):
        return True, "premium"
    return False, "free"

# ==================== WORKERS EN SEGUNDO PLANO ====================
def worker_paquetes(numeros):
    consultor = TelcelConsulta()
    resultados, no_telcel, sin_paquetes = [], [], []
    for num in numeros:
        data = consultor.consultar(num)
        if data is None:
            no_telcel.append(num)
        else:
            resultado, estado = consultor.formatear_paquetes(num, data)
            if estado == "ok" and resultado:
                resultados.append(resultado)
            elif estado == "no_telcel":
                no_telcel.append(num)
            else:
                sin_paquetes.append(num)
    return resultados, no_telcel, sin_paquetes

def worker_saldo(numeros):
    consultor = TelcelConsulta()
    resultados, no_telcel, sin_saldo = [], [], []
    for num in numeros:
        data = consultor.consultar(num)
        if data is None:
            no_telcel.append(num)
        else:
            resultado, estado = consultor.formatear_saldo(num, data)
            if estado == "ok" and resultado:
                resultados.append(resultado)
            elif estado == "no_telcel":
                no_telcel.append(num)
            else:
                sin_saldo.append(num)
    return resultados, no_telcel, sin_saldo

def worker_balance(numeros):
    consultor = TelcelConsulta()
    resultados, no_telcel = [], []
    for num in numeros:
        data = consultor.consultar(num)
        if data is None:
            no_telcel.append(num)
        else:
            texto, estado = consultor.formatear_balance(num, data)
            if estado == "ok" and texto:
                resultados.append(texto)
            else:
                no_telcel.append(num)
    return resultados, no_telcel

# ==================== COMANDOS ====================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or "None"
    first_name = update.effective_user.first_name or "Unknown"
    
    if not db.query_user(user_id):
        role = "owner" if is_admin(user_id) else "free"
        db.insert_user({
            "id": user_id,
            "username": username,
            "first_name": first_name,
            "role": role,
            "banned": False,
            "created_at": datetime.datetime.now(),
            "premium_until": None
        })
    elif is_admin(user_id):
        db.user.update_one({"id": user_id}, {"$set": {"role": "owner"}})
    
    can_use, reason = can_use_bot(user_id)
    
    mensaje = "📱 <b>TELCEL CONSULTOR</b>\n\n"
    
    if not can_use:
        mensaje += "🚫 <b>ACCESO RESTRINGIDO</b>\n\n"
        if reason == "baneado":
            mensaje += "❌ Has sido baneado del sistema.\n"
        else:
            mensaje += "❌ No tienes una suscripción activa.\n"
            mensaje += "💳 Usa /claim con una key válida para activar premium.\n\n"
        await update.message.reply_text(mensaje, parse_mode='HTML')
        return
    
    mensaje += "<b>COMANDOS DISPONIBLES</b>:\n"
    mensaje += "/paquetes <b>numeros</b> - Ver paquetes activos\n"
    mensaje += "/balance <b>numeros</b> - Detalle completo\n"
    mensaje += "/saldo <b>numeros</b> - Megas disponibles\n"
    mensaje += "/bloques <b>N</b> <b>numeros</b> - Agrupar en bloques\n"
    mensaje += "/me - Tu información\n"
    
    if is_admin(user_id):
        mensaje += "\n🔧 <b>ADMIN</b>:\n"
        mensaje += "/panel - Panel de control\n"
    
    if is_developer(user_id):
        mensaje += "\n👑 <b>DEVELOPER</b>\n"
    
    await update.message.reply_text(mensaje, parse_mode='HTML')

async def paquetes_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    can_use, reason = can_use_bot(user_id)
    if not can_use:
        if reason == "baneado":
            await update.message.reply_text("🚫 <b>ACCESO DENEGADO - Usuario baneado</b>", parse_mode='HTML')
        else:
            await update.message.reply_text(
                "🚫 <b>ACCESO RESTRINGIDO</b>\n\n"
                "❌ No tienes una suscripción premium activa.\n"
                "💳 Usa /claim con una key válida para activar premium.",
                parse_mode='HTML'
            )
        return
    
    if not context.args:
        await update.message.reply_text(
            "📋 <b>Uso</b>: /paquetes <b>numeros</b>\n"
            "<b>Ejemplo</b>: /paquetes 5512345678 5523456789",
            parse_mode='HTML'
        )
        return
    
    text = " ".join(context.args)
    numeros = parse_phone_numbers(text)
    if not numeros:
        await update.message.reply_text("❌ No se encontraron números de 10 dígitos.", parse_mode='HTML')
        return
    if len(numeros) > 100:
        numeros = numeros[:100]
        await update.message.reply_text("⚠️ Máximo 100 números.", parse_mode='HTML')
    
    await update.message.reply_text(f"🔄 Consultando {len(numeros)} número(s)...", parse_mode='HTML')
    
    loop = asyncio.get_event_loop()
    resultados, no_telcel, sin_paquetes = await loop.run_in_executor(executor, worker_paquetes, numeros)
    
    mensaje = [f"✅ Resultados Finales ({len(numeros)}/{len(numeros)})", ""]
    if resultados:
        mensaje.append(f"✅ Approved! ({len(resultados)})")
        mensaje.extend(resultados)
    if sin_paquetes:
        mensaje.append("")
        mensaje.append(f"❌ Sin paquetes ({len(sin_paquetes)}):")
        mensaje.extend(sin_paquetes)
    if no_telcel:
        mensaje.append("")
        mensaje.append(f"❌ No Telcel ({len(no_telcel)}):")
        mensaje.extend(no_telcel)
    
    await update.message.reply_text("\n".join(mensaje), parse_mode='HTML')

async def balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    can_use, reason = can_use_bot(user_id)
    if not can_use:
        if reason == "baneado":
            await update.message.reply_text("🚫 <b>ACCESO DENEGADO - Usuario baneado</b>", parse_mode='HTML')
        else:
            await update.message.reply_text(
                "🚫 <b>ACCESO RESTRINGIDO</b>\n\n"
                "❌ No tienes una suscripción premium activa.\n"
                "💳 Usa /claim con una key válida para activar premium.",
                parse_mode='HTML'
            )
        return
    
    if not context.args:
        await update.message.reply_text(
            "📋 <b>Uso</b>: /balance <b>numeros</b>\n"
            "<b>Ejemplo</b>: /balance 5512345678",
            parse_mode='HTML'
        )
        return
    
    text = " ".join(context.args)
    numeros = parse_phone_numbers(text)
    if not numeros:
        await update.message.reply_text("❌ No se encontraron números de 10 dígitos.", parse_mode='HTML')
        return
    if len(numeros) > 100:
        numeros = numeros[:100]
        await update.message.reply_text("⚠️ Máximo 100 números.", parse_mode='HTML')
    
    await update.message.reply_text(f"🔄 Consultando {len(numeros)} número(s)...", parse_mode='HTML')
    
    loop = asyncio.get_event_loop()
    resultados, no_telcel = await loop.run_in_executor(executor, worker_balance, numeros)
    
    mensaje = [f"✅ Resultados Balance ({len(numeros)}/{len(numeros)})", ""]
    if resultados:
        mensaje.append(f"✅ Approved! ({len(resultados)})")
        mensaje.extend(resultados)
    if no_telcel:
        mensaje.append("")
        mensaje.append(f"❌ No Telcel ({len(no_telcel)}):")
        mensaje.extend(no_telcel)
    
    await update.message.reply_text("\n".join(mensaje), parse_mode='HTML')

async def saldo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    can_use, reason = can_use_bot(user_id)
    if not can_use:
        if reason == "baneado":
            await update.message.reply_text("🚫 <b>ACCESO DENEGADO - Usuario baneado</b>", parse_mode='HTML')
        else:
            await update.message.reply_text(
                "🚫 <b>ACCESO RESTRINGIDO</b>\n\n"
                "❌ No tienes una suscripción premium activa.\n"
                "💳 Usa /claim con una key válida para activar premium.",
                parse_mode='HTML'
            )
        return
    
    if not context.args:
        await update.message.reply_text(
            "📋 <b>Uso</b>: /saldo <b>numeros</b>\n"
            "<b>Ejemplo</b>: /saldo 5512345678",
            parse_mode='HTML'
        )
        return
    
    text = " ".join(context.args)
    numeros = parse_phone_numbers(text)
    if not numeros:
        await update.message.reply_text("❌ No se encontraron números de 10 dígitos.", parse_mode='HTML')
        return
    if len(numeros) > 100:
        numeros = numeros[:100]
        await update.message.reply_text("⚠️ Máximo 100 números.", parse_mode='HTML')
    
    await update.message.reply_text(f"🔄 Consultando {len(numeros)} número(s)...", parse_mode='HTML')
    
    loop = asyncio.get_event_loop()
    resultados, no_telcel, sin_saldo = await loop.run_in_executor(executor, worker_saldo, numeros)
    
    mensaje = [f"✅ Resultados Saldo ({len(numeros)}/{len(numeros)})", ""]
    if resultados:
        mensaje.append(f"✅ Approved! ({len(resultados)})")
        mensaje.extend(resultados)
    if sin_saldo:
        mensaje.append("")
        mensaje.append(f"❌ Sin saldo ({len(sin_saldo)}):")
        mensaje.extend(sin_saldo)
    if no_telcel:
        mensaje.append("")
        mensaje.append(f"❌ No Telcel ({len(no_telcel)}):")
        mensaje.extend(no_telcel)
    
    await update.message.reply_text("\n".join(mensaje), parse_mode='HTML')

async def bloques_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    can_use, reason = can_use_bot(user_id)
    if not can_use:
        if reason == "baneado":
            await update.message.reply_text("🚫 <b>ACCESO DENEGADO - Usuario baneado</b>", parse_mode='HTML')
        else:
            await update.message.reply_text(
                "🚫 <b>ACCESO RESTRINGIDO</b>\n\n"
                "❌ No tienes una suscripción premium activa.\n"
                "💳 Usa /claim con una key válida para activar premium.",
                parse_mode='HTML'
            )
        return
    
    if not context.args:
        await update.message.reply_text(
            "📋 <b>Uso</b>: /bloques <b>N</b> <b>numeros</b>\n"
            "<b>Ejemplo</b>: /bloques 2 5662745449 5662749398",
            parse_mode='HTML'
        )
        return
    
    try:
        tamano = int(context.args[0])
        if tamano < 1:
            await update.message.reply_text("❌ N debe ser mayor a 0.", parse_mode='HTML')
            return
    except ValueError:
        await update.message.reply_text("❌ N debe ser un número.", parse_mode='HTML')
        return
    
    text = " ".join(context.args[1:])
    numeros = parse_phone_numbers(text)
    if not numeros:
        await update.message.reply_text("❌ No se encontraron números de 10 dígitos.", parse_mode='HTML')
        return
    if len(numeros) > 100:
        numeros = numeros[:100]
    
    bloques = [numeros[i:i+tamano] for i in range(0, len(numeros), tamano)]
    mensaje = f"<b>Total</b>: {len(numeros)} números\n<b>Bloques de</b>: {tamano}\n\n"
    
    for idx, bloque in enumerate(bloques, 1):
        mensaje += f"<b>Bloque {idx}</b>\n"
        mensaje += "\n".join(bloque)
        mensaje += "\n\n"
    
    if len(mensaje) > 4000:
        for parte in [mensaje[i:i+4000] for i in range(0, len(mensaje), 4000)]:
            await update.message.reply_text(parte, parse_mode='HTML')
    else:
        await update.message.reply_text(mensaje, parse_mode='HTML')

async def me_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_info = db.get_user_info(user_id)
    if not user_info:
        await update.message.reply_text("❌ No estás registrado. Usa /start", parse_mode='HTML')
        return
    
    premium_until = user_info.get('premium_until')
    is_premium_user = premium_until and premium_until > datetime.datetime.now()
    
    first_name = user_info.get('first_name', 'Unknown')
    if first_name == "Unknown":
        try:
            user = await context.bot.get_chat(user_id)
            first_name = user.first_name or "Unknown"
        except:
            pass
    
    lineas = ["-" * 40]
    lineas.append(f"<b>ID</b>: {user_info['id']}")
    lineas.append(f"<b>NAME</b>: {first_name}")
    lineas.append(f"<b>USERNAME</b>: @{user_info.get('username', 'None')}")
    lineas.append(f"<b>ROL</b>: {user_info.get('role', 'FREE').upper()}")
    
    if is_premium_user:
        lineas.append(f"<b>Premium hasta</b>: {premium_until.strftime('%d/%m/%Y %H:%M')}")
    else:
        lineas.append("<b>Expired plan</b>")
    
    if user_info.get('banned'):
        lineas.append("🚫 <b>BANEADO</b>")
    
    lineas.append("-" * 40)
    
    await update.message.reply_text("\n".join(lineas), parse_mode='HTML')

# ==================== COMANDOS ADMIN ====================

async def panel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("⛔ <b>NO AUTORIZADO</b>", parse_mode='HTML')
        return
    
    await update.message.reply_text(
        "🔧 <b>PANEL DE ADMINISTRACIÓN</b>\n\n"
        "/key <b>dias</b> - Crear key premium\n"
        "/delkey <b>key</b> - Eliminar key (revoca premium si fue usada)\n"
        "/claim <b>key</b> - Canjear key\n"
        "/ban <b>id</b> - Banear usuario\n"
        "/unban <b>id</b> - Desbanear usuario\n"
        "/dar <b>id</b> <b>rol</b> - Asignar rol (owner/admin/seller)\n"
        "/me - Tu información",
        parse_mode='HTML'
    )

async def key_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("⛔ <b>NO AUTORIZADO</b>", parse_mode='HTML')
        return
    if not context.args:
        await update.message.reply_text(
            "📋 <b>Uso</b>: /key <b>dias</b>\n"
            "<b>Ejemplo</b>: /key 7",
            parse_mode='HTML'
        )
        return
    
    try:
        days = int(context.args[0])
        if days < 1:
            await update.message.reply_text("❌ Días debe ser mayor a 0.", parse_mode='HTML')
            return
    except ValueError:
        await update.message.reply_text("❌ Ingresa un número válido.", parse_mode='HTML')
        return
    
    key = db.create_key(days)
    key_data = db.get_key_info(key)
    
    await update.message.reply_text(
        f"✅ <b>KEY CREADA</b>\n\n"
        f"<b>🔑 Key</b>: <code>{key}</code>\n"
        f"<b>📅 Días</b>: {days}\n"
        f"<b>⏳ Válida hasta</b>: {key_data['expires_at'].strftime('%d/%m/%Y %H:%M')}",
        parse_mode='HTML'
    )

async def delkey_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Elimina una key y revoca premium si fue usada"""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("⛔ <b>NO AUTORIZADO</b>", parse_mode='HTML')
        return
    if not context.args:
        await update.message.reply_text(
            "📋 <b>Uso</b>: /delkey <b>key</b>\n"
            "<b>Ejemplo</b>: /delkey ELBUENMX-728926725728",
            parse_mode='HTML'
        )
        return
    
    key = context.args[0].strip()
    key_data = db.get_key_info(key)
    
    if not key_data:
        await update.message.reply_text(f"❌ Key <code>{key}</code> no encontrada.", parse_mode='HTML')
        return
    
    used_by = key_data.get('used_by')
    
    # Eliminar la key
    db.keys.delete_one({"key": key})
    
    mensaje = [
        f"✅ <b>KEY ELIMINADA</b>\n\n",
        f"<b>🔑 Key</b>: <code>{key}</code>\n",
        f"<b>📅 Creada</b>: {key_data['created_at'].strftime('%d/%m/%Y %H:%M')}\n",
        f"<b>📅 Expiraba</b>: {key_data['expires_at'].strftime('%d/%m/%Y %H:%M')}"
    ]
    
    # Si la key fue usada, revocar premium y mostrar usuario
    if used_by:
        user = db.query_user(used_by)
        if user:
            # Revocar premium
            db.user.update_one(
                {"id": used_by},
                {"$set": {"premium_until": None, "role": "free"}}
            )
            mensaje.append(f"\n<b>👤 Usuario</b>: @{user.get('username', 'None')} (ID: {used_by})")
            mensaje.append("<b>🔄 Premium revocado</b>")
            
            # Notificar al usuario
            try:
                await context.bot.send_message(
                    used_by,
                    "🚫 <b>Premium revocado</b>\n\n"
                    "❌ La key que canjeaste fue eliminada por el administrador.",
                    parse_mode='HTML'
                )
            except:
                pass
    
    await update.message.reply_text("\n".join(mensaje), parse_mode='HTML')

async def claim_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or "None"
    first_name = update.effective_user.first_name or "Unknown"
    
    if db.is_banned(user_id):
        await update.message.reply_text("🚫 <b>ACCESO DENEGADO - Usuario baneado</b>", parse_mode='HTML')
        return
    
    if is_premium(user_id):
        user_data = db.query_user(user_id)
        premium_until = user_data.get('premium_until')
        await update.message.reply_text(
            f"🚫 <b>YA TIENES PREMIUM ACTIVO</b>\n\n"
            f"📆 Tu premium expira: {premium_until.strftime('%d/%m/%Y %H:%M')}\n"
            f"⏳ Espera a que expire para canjear otra key.",
            parse_mode='HTML'
        )
        return
    
    if not context.args:
        await update.message.reply_text(
            "📋 <b>Uso</b>: /claim <b>key</b>\n"
            "<b>Ejemplo</b>: /claim ELBUENMX-728926725728",
            parse_mode='HTML'
        )
        return
    
    key = context.args[0].strip()
    
    key_data = db.get_key_info(key)
    if not key_data:
        await update.message.reply_text(f"❌ Key <code>{key}</code> no encontrada.", parse_mode='HTML')
        return
    
    if key_data.get('used', False):
        used_by = key_data.get('used_by')
        await update.message.reply_text(
            f"❌ <b>KEY YA CANJEADA</b>\n\n"
            f"🔑 <code>{key}</code>\n"
            f"👤 Usuario que la canjeó: {used_by if used_by else 'Desconocido'}",
            parse_mode='HTML'
        )
        return
    
    if key_data.get('expires_at') and key_data['expires_at'] < datetime.datetime.now():
        await update.message.reply_text(
            f"❌ <b>KEY EXPIRADA</b>\n\n"
            f"🔑 <code>{key}</code>\n"
            f"📅 Expiró: {key_data['expires_at'].strftime('%d/%m/%Y %H:%M')}",
            parse_mode='HTML'
        )
        return
    
    success, result = db.claim_key(key, user_id, username, first_name)
    
    if not success:
        await update.message.reply_text(f"❌ {result}", parse_mode='HTML')
        return
    
    days, new_expiry = result
    await update.message.reply_text(
        f"✅ <b>Your account was upgraded to premium</b>\n\n"
        f"<b>👤 Usuario</b>: @{username}\n"
        f"<b>🆔 UserID</b>: <code>{user_id}</code>\n"
        f"<b>📅 Added days</b>: {days}\n"
        f"<b>👑 Rank</b>: PREMIUM\n\n"
        f"<b>📆 Expires</b>: {new_expiry.strftime('%d/%m/%Y %H:%M')}",
        parse_mode='HTML'
    )

async def ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("⛔ <b>NO AUTORIZADO</b>", parse_mode='HTML')
        return
    if not context.args:
        await update.message.reply_text(
            "📋 <b>Uso</b>: /ban <b>user_id</b>\n"
            "<b>Ejemplo</b>: /ban 123456789",
            parse_mode='HTML'
        )
        return
    
    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ ID inválido.", parse_mode='HTML')
        return
    
    if target_id == DEVELOPER_ID:
        await update.message.reply_text("❌ No puedes banear al DEVELOPER.", parse_mode='HTML')
        return
    
    if target_id == ADMIN_2_ID and not is_developer(user_id):
        await update.message.reply_text("❌ No puedes banear a este admin.", parse_mode='HTML')
        return
    
    user = db.query_user(target_id)
    if not user:
        await update.message.reply_text(f"❌ Usuario {target_id} no encontrado.", parse_mode='HTML')
        return
    
    db.ban_user(target_id)
    await update.message.reply_text(
        f"✅ <b>USUARIO BANEADO</b>\n\n"
        f"<b>🆔 ID</b>: <code>{target_id}</code>\n"
        f"<b>👤 Username</b>: @{user.get('username', 'None')}",
        parse_mode='HTML'
    )

async def unban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("⛔ <b>NO AUTORIZADO</b>", parse_mode='HTML')
        return
    if not context.args:
        await update.message.reply_text(
            "📋 <b>Uso</b>: /unban <b>user_id</b>\n"
            "<b>Ejemplo</b>: /unban 123456789",
            parse_mode='HTML'
        )
        return
    
    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ ID inválido.", parse_mode='HTML')
        return
    
    user = db.query_user(target_id)
    if not user:
        await update.message.reply_text(f"❌ Usuario {target_id} no encontrado.", parse_mode='HTML')
        return
    
    db.unban_user(target_id)
    await update.message.reply_text(
        f"✅ <b>USUARIO DESBANEADO</b>\n\n"
        f"<b>🆔 ID</b>: <code>{target_id}</code>\n"
        f"<b>👤 Username</b>: @{user.get('username', 'None')}",
        parse_mode='HTML'
    )

async def dar_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_developer(user_id):
        await update.message.reply_text("⛔ <b>SOLO DEVELOPER</b>", parse_mode='HTML')
        return
    if len(context.args) < 2:
        await update.message.reply_text(
            "📋 <b>Uso</b>: /dar <b>user_id</b> <b>rol</b>\n"
            "<b>Roles</b>: owner, admin, seller\n"
            "<b>Ejemplo</b>: /dar 123456789 admin",
            parse_mode='HTML'
        )
        return
    
    try:
        target_id = int(context.args[0])
        role = context.args[1].lower()
        if role not in ['owner', 'admin', 'seller']:
            await update.message.reply_text("❌ Rol inválido. Roles: owner, admin, seller", parse_mode='HTML')
            return
    except ValueError:
        await update.message.reply_text("❌ ID inválido.", parse_mode='HTML')
        return
    
    user = db.query_user(target_id)
    if not user:
        await update.message.reply_text(f"❌ Usuario {target_id} no encontrado.", parse_mode='HTML')
        return
    
    db.user.update_one({"id": target_id}, {"$set": {"role": role}})
    await update.message.reply_text(
        f"✅ <b>ROL ACTUALIZADO</b>\n\n"
        f"<b>🆔 ID</b>: <code>{target_id}</code>\n"
        f"<b>👤 Username</b>: @{user.get('username', 'None')}\n"
        f"<b>📋 Nuevo rol</b>: {role.upper()}",
        parse_mode='HTML'
    )

# ==================== MANEJADORES .COMANDOS ====================
async def paquetes_dot_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    text = re.sub(r'^\.paquetes\s*', '', text)
    context.args = text.split()
    await paquetes_command(update, context)

async def balance_dot_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    text = re.sub(r'^\.balance\s*', '', text)
    context.args = text.split()
    await balance_command(update, context)

async def saldo_dot_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    text = re.sub(r'^\.saldo\s*', '', text)
    context.args = text.split()
    await saldo_command(update, context)

async def bloques_dot_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    text = re.sub(r'^\.bloques\s*', '', text)
    context.args = text.split()
    await bloques_command(update, context)

# ==================== MAIN ====================
def main():
    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("paquetes", paquetes_command))
    application.add_handler(CommandHandler("balance", balance_command))
    application.add_handler(CommandHandler("saldo", saldo_command))
    application.add_handler(CommandHandler("bloques", bloques_command))
    application.add_handler(CommandHandler("me", me_command))
    application.add_handler(CommandHandler("panel", panel_command))
    application.add_handler(CommandHandler("key", key_command))
    application.add_handler(CommandHandler("delkey", delkey_command))
    application.add_handler(CommandHandler("claim", claim_command))
    application.add_handler(CommandHandler("ban", ban_command))
    application.add_handler(CommandHandler("unban", unban_command))
    application.add_handler(CommandHandler("dar", dar_command))
    
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.Regex(r'^\.paquetes'),
        paquetes_dot_handler
    ))
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.Regex(r'^\.balance'),
        balance_dot_handler
    ))
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.Regex(r'^\.saldo'),
        saldo_dot_handler
    ))
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.Regex(r'^\.bloques'),
        bloques_dot_handler
    ))

    print("\n" + "="*60)
    print("🤖 BOT TELCEL CONSULTOR INICIADO")
    print("="*60)
    print("Comandos: /paquetes, /balance, /saldo, /bloques, /me")
    print("Admin: /panel, /key, /delkey, /claim, /ban, /unban, /dar")
    print("Developer ID: 5962220190")
    print("Admin ID: 1233826268")
    print("="*60)
    
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()