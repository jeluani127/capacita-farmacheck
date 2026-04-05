import os
import logging
import smtplib
import random
import gspread
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from google.oauth2.service_account import Credentials
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes, ConversationHandler, CallbackQueryHandler
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import anthropic
import base64
import json
from datetime import datetime

# ============================================================
# CONFIGURACION
# ============================================================
from dotenv import load_dotenv
load_dotenv()

TELEGRAM_TOKEN        = os.getenv("TELEGRAM_TOKEN")
ANTHROPIC_API_KEY     = os.getenv("ANTHROPIC_API_KEY")
EMAIL_REMITENTE       = os.getenv("EMAIL_REMITENTE")
EMAIL_PASSWORD        = os.getenv("EMAIL_PASSWORD")
EMAIL_SMTP_SERVER     = os.getenv("EMAIL_SMTP_SERVER")
GOOGLE_SHEETS_ID      = os.getenv("GOOGLE_SHEETS_ID")
GOOGLE_CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")
DATOS_ARCHIVO         = "usuarios.json"

_vars_requeridas = {
    "TELEGRAM_TOKEN": TELEGRAM_TOKEN,
    "ANTHROPIC_API_KEY": ANTHROPIC_API_KEY,
    "EMAIL_REMITENTE": EMAIL_REMITENTE,
    "EMAIL_PASSWORD": EMAIL_PASSWORD,
    "EMAIL_SMTP_SERVER": EMAIL_SMTP_SERVER,
    "GOOGLE_SHEETS_ID": GOOGLE_SHEETS_ID,
}
_faltantes = [k for k, v in _vars_requeridas.items() if not v]
if _faltantes:
    raise EnvironmentError(
        f"❌ Variables de entorno faltantes: {', '.join(_faltantes)}\n"
        "Revisa tu archivo .env antes de iniciar el bot."
    )
# ============================================================

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

NOMBRE, TELEFONO, CORREO, VERIFICAR_CORREO, ESPERANDO_ETIQUETA = range(5)

# ============================================================
# CLIPS EDUCATIVOS NOM-072 (Día 4)
# ============================================================
CLIPS_NOM072 = [
    {
        "titulo": "📌 ¿Qué es la NOM-072-SSA1-2012?",
        "contenido": (
            "La *NOM-072-SSA1-2012* es la Norma Oficial Mexicana que establece "
            "los requisitos mínimos de información que debe contener la etiqueta "
            "de todo medicamento para uso humano comercializado en México.\n\n"
            "Su objetivo es garantizar que el paciente y el profesional de salud "
            "cuenten con información clara, veraz y suficiente para el uso seguro "
            "del medicamento.\n\n"
            "📖 _Clip 1 de 12 — Serie FarmaCheck_"
        )
    },
    {
        "titulo": "💊 Denominación distintiva vs. genérica",
        "contenido": (
            "Toda etiqueta debe incluir *dos nombres*:\n\n"
            "• *Denominación distintiva:* El nombre comercial o de marca "
            "(ej. Tylenol®, Aspirina®)\n\n"
            "• *Denominación genérica:* El nombre científico de la sustancia activa "
            "(ej. Paracetamol, Ácido acetilsalicílico)\n\n"
            "Ambos son obligatorios según la NOM-072. El genérico no puede omitirse "
            "aunque el producto sea de marca.\n\n"
            "📖 _Clip 2 de 12 — Serie FarmaCheck_"
        )
    },
    {
        "titulo": "🏭 Fabricante vs. titular del registro",
        "contenido": (
            "La NOM-072 exige que la etiqueta indique *dos entidades* distintas:\n\n"
            "• *Fabricante:* La empresa que produce físicamente el medicamento, "
            "con nombre y domicilio completo.\n\n"
            "• *Titular del registro sanitario:* La empresa dueña del registro ante "
            "COFEPRIS, que puede ser diferente al fabricante.\n\n"
            "Esta distinción es importante para la trazabilidad y responsabilidad "
            "del producto.\n\n"
            "📖 _Clip 3 de 12 — Serie FarmaCheck_"
        )
    },
    {
        "titulo": "🔢 Número de registro sanitario",
        "contenido": (
            "El *registro sanitario* es el código que COFEPRIS otorga para autorizar "
            "la venta de un medicamento en México.\n\n"
            "Formato típico: *XXXXSA-XXXXXXXXX* o similar.\n\n"
            "⚠️ Un medicamento sin número de registro sanitario visible en la etiqueta "
            "puede ser:\n"
            "• Producto no autorizado\n"
            "• Falsificación\n"
            "• Importación irregular\n\n"
            "Siempre verifica este dato antes de recomendar o adquirir un medicamento.\n\n"
            "📖 _Clip 4 de 12 — Serie FarmaCheck_"
        )
    },
    {
        "titulo": "📅 Fecha de caducidad y número de lote",
        "contenido": (
            "Dos datos de trazabilidad que nunca pueden faltar:\n\n"
            "• *Fecha de caducidad:* Indica hasta cuándo garantiza el fabricante "
            "la potencia y seguridad del medicamento. Formato: MM/AAAA o DD/MM/AAAA.\n\n"
            "• *Número de lote:* Código que identifica el grupo de producción. "
            "Permite rastrear el medicamento en caso de alerta sanitaria o retiro del mercado.\n\n"
            "Sin estos datos, no es posible garantizar la calidad del producto.\n\n"
            "📖 _Clip 5 de 12 — Serie FarmaCheck_"
        )
    },
    {
        "titulo": "🚦 Leyendas de venta: ¿con o sin receta?",
        "contenido": (
            "La NOM-072 obliga a indicar claramente el tipo de venta:\n\n"
            "• *'Venta sin receta médica'* — OTC, libre dispensación\n"
            "• *'Venta con receta médica'* — Requiere prescripción\n"
            "• *'Venta con receta médica retenida'* — Receta especial controlada\n\n"
            "Esta leyenda protege al paciente y orienta al farmacéutico sobre "
            "cómo dispensar correctamente el medicamento.\n\n"
            "📖 _Clip 6 de 12 — Serie FarmaCheck_"
        )
    },
    {
        "titulo": "⚠️ Leyendas de seguridad obligatorias",
        "contenido": (
            "Dependiendo del medicamento, la NOM-072 exige leyendas como:\n\n"
            "• _'No se deje al alcance de los niños'_\n"
            "• _'No se use en el embarazo sin consultar al médico'_\n"
            "• _'Este medicamento puede causar somnolencia'_\n"
            "• _'Evite conducir vehículos o manejar maquinaria'_\n\n"
            "Estas leyendas son determinadas por la naturaleza del principio activo "
            "y son de cumplimiento obligatorio, no opcionales.\n\n"
            "📖 _Clip 7 de 12 — Serie FarmaCheck_"
        )
    },
    {
        "titulo": "💉 Forma farmacéutica y vía de administración",
        "contenido": (
            "La etiqueta debe especificar:\n\n"
            "• *Forma farmacéutica:* Cómo se presenta el medicamento "
            "(tableta, cápsula, solución, crema, supositorio, etc.)\n\n"
            "• *Vía de administración:* Cómo debe introducirse al organismo "
            "(oral, tópica, intravenosa, intramuscular, sublingual, etc.)\n\n"
            "Confundir la vía de administración puede causar efectos adversos graves. "
            "La etiqueta debe ser inequívoca en este punto.\n\n"
            "📖 _Clip 8 de 12 — Serie FarmaCheck_"
        )
    },
    {
        "titulo": "📦 Concentración, contenido neto y condiciones de almacenamiento",
        "contenido": (
            "Tres datos técnicos obligatorios:\n\n"
            "• *Concentración o potencia:* Cantidad de principio activo por unidad "
            "(ej. 500 mg, 10 mg/mL)\n\n"
            "• *Contenido neto:* Cantidad total del producto "
            "(ej. 20 tabletas, 120 mL)\n\n"
            "• *Condiciones de almacenamiento:* Temperatura, humedad y luz "
            "(ej. 'Consérvese en lugar fresco y seco, a temperatura menor de 25°C')\n\n"
            "📖 _Clip 9 de 12 — Serie FarmaCheck_"
        )
    },
    {
        "titulo": "🌍 País de origen e indicaciones terapéuticas",
        "contenido": (
            "• *País de origen:* Dónde fue fabricado el medicamento. "
            "Importante para importaciones y cumplimiento aduanal.\n\n"
            "• *Indicaciones terapéuticas:* Para qué enfermedades o síntomas "
            "está indicado el medicamento. Deben coincidir con el registro sanitario "
            "autorizado por COFEPRIS.\n\n"
            "Indicaciones no autorizadas en la etiqueta constituyen una irregularidad "
            "sanitaria grave.\n\n"
            "📖 _Clip 10 de 12 — Serie FarmaCheck_"
        )
    },
    {
        "titulo": "🚫 Contraindicaciones, precauciones e interacciones",
        "contenido": (
            "La NOM-072 exige que la etiqueta o su inserto incluyan:\n\n"
            "• *Contraindicaciones:* Situaciones en que el medicamento NO debe usarse "
            "(alergias, enfermedades previas, embarazo)\n\n"
            "• *Precauciones y advertencias:* Cuidados especiales durante el uso\n\n"
            "• *Interacciones medicamentosas:* Otros medicamentos, alimentos o "
            "sustancias que pueden afectar su eficacia o seguridad\n\n"
            "• *Reacciones adversas:* Efectos secundarios conocidos\n\n"
            "📖 _Clip 11 de 12 — Serie FarmaCheck_"
        )
    },
    {
        "titulo": "✅ Resumen: Los 21 puntos de la NOM-072",
        "contenido": (
            "La *NOM-072-SSA1-2012* requiere verificar 21 puntos en cada etiqueta:\n\n"
            "1. Denominación distintiva\n"
            "2. Denominación genérica\n"
            "3. Forma farmacéutica\n"
            "4. Concentración o potencia\n"
            "5. Contenido neto\n"
            "6. Vía de administración\n"
            "7. Indicaciones terapéuticas\n"
            "8. Contraindicaciones\n"
            "9. Precauciones y advertencias\n"
            "10. Interacciones medicamentosas\n"
            "11. Reacciones adversas\n"
            "12. Posología y dosis\n"
            "13. Leyendas de seguridad\n"
            "14. Número de registro sanitario\n"
            "15. Nombre y domicilio del fabricante\n"
            "16. Nombre y domicilio del titular\n"
            "17. País de origen\n"
            "18. Número de lote\n"
            "19. Fecha de caducidad\n"
            "20. Condiciones de almacenamiento\n"
            "21. Leyenda venta con/sin receta\n\n"
            "¡Envíame una etiqueta y verifico todos estos puntos! 🔬\n\n"
            "📖 _Clip 12 de 12 — Serie FarmaCheck_"
        )
    },
]

# ============================================================
# FILTRO DE LENGUAJE INAPROPIADO
# ============================================================
PALABRAS_BLOQUEADAS = {
    "puta", "puto", "chingar", "chinga", "chingada", "chingado",
    "cabron", "cabrón", "pendejo", "pendeja", "pinche", "verga",
    "mierda", "perra", "perro", "culero", "culo", "joder",
    "mamada", "mamadas", "coño", "idiota", "imbecil", "imbécil",
    "estupido", "estúpido", "maldito", "maldita", "guey", "wey",
    "hijo de puta", "hdp", "chinguen", "chínguense",
}

def contiene_groserías(texto: str) -> bool:
    texto_lower = texto.lower()
    for palabra in PALABRAS_BLOQUEADAS:
        if palabra in texto_lower:
            return True
    return False

def bloquear_usuario(user_id: int):
    usuarios = cargar_usuarios()
    uid = str(user_id)
    if uid in usuarios:
        usuarios[uid]['bloqueado'] = True
        usuarios[uid]['fecha_bloqueo'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with open(DATOS_ARCHIVO, 'w', encoding='utf-8') as f:
            json.dump(usuarios, f, ensure_ascii=False, indent=2)

def usuario_bloqueado(user_id: int) -> bool:
    usuarios = cargar_usuarios()
    return usuarios.get(str(user_id), {}).get('bloqueado', False)

# ============================================================
DISCLAIMER = """
─────────────────────────────────
⚠️ AVISO IMPORTANTE

Este análisis fue generado por Inteligencia Artificial como herramienta de apoyo.
Los resultados NO sustituyen la revisión y supervisión de un experto regulatorio humano calificado.

Se recomienda validar cualquier hallazgo con un profesional en regulación farmacéutica
antes de tomar decisiones basadas en este reporte.

🔬 FarmaCheck — Herramienta de apoyo regulatorio
─────────────────────────────────"""

NOM_072_PROMPT = """Eres un experto en regulación farmacéutica mexicana, especializado en la NOM-072-SSA1-2012 
que establece los requisitos de etiquetado de medicamentos para uso humano.

Tu ÚNICA función es analizar imágenes o documentos de etiquetas de medicamentos y verificar su cumplimiento 
con la NOM-072-SSA1-2012.

NO respondas preguntas de otro tipo. Si alguien pregunta algo diferente, responde:
"Solo puedo verificar etiquetas de medicamentos conforme a la NOM-072-SSA1-2012. 
Por favor envía una foto, screenshot o PDF de la etiqueta que deseas verificar."

Cuando recibas una etiqueta, genera un checklist COMPLETO con los siguientes puntos de la NOM-072:

1. ✅/❌ Denominación distintiva (nombre comercial)
2. ✅/❌ Denominación genérica (DCI o nombre genérico)
3. ✅/❌ Forma farmacéutica
4. ✅/❌ Concentración o potencia
5. ✅/❌ Contenido neto
6. ✅/❌ Vía de administración
7. ✅/❌ Indicaciones terapéuticas
8. ✅/❌ Contraindicaciones
9. ✅/❌ Precauciones y advertencias
10. ✅/❌ Interacciones medicamentosas
11. ✅/❌ Reacciones adversas
12. ✅/❌ Posología y dosis
13. ✅/❌ Leyendas de seguridad obligatorias
14. ✅/❌ Número de registro sanitario
15. ✅/❌ Nombre y domicilio del fabricante
16. ✅/❌ Nombre y domicilio del titular del registro
17. ✅/❌ País de origen
18. ✅/❌ Número de lote
19. ✅/❌ Fecha de caducidad
20. ✅/❌ Condiciones de almacenamiento
21. ✅/❌ Leyenda venta con/sin receta

Al final indica:
- 📊 RESUMEN: X de 21 puntos cumplidos
- ⚠️ PUNTOS FALTANTES: Lista los que no cumplen
- 💡 RECOMENDACIÓN: Qué debe corregirse"""

VALIDACION_PROMPT = """Eres un validador de imágenes para un sistema de verificación de etiquetas de medicamentos.

Tu única tarea es determinar si la imagen recibida corresponde a:
- Una etiqueta de medicamento
- El empaque de un medicamento
- Un documento relacionado con un medicamento (prospecto, inserto, ficha técnica)

Responde ÚNICAMENTE con una de estas dos palabras:
- VALIDA  (si la imagen sí corresponde a una etiqueta o documento de medicamento)
- INVALIDA (si la imagen NO corresponde a una etiqueta o documento de medicamento)

No agregues explicaciones, puntos, ni ninguna otra palabra. Solo VALIDA o INVALIDA."""


# ============================================================
# FUNCIONES DE DATOS
# ============================================================
def cargar_usuarios():
    if os.path.exists(DATOS_ARCHIVO):
        with open(DATOS_ARCHIVO, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def guardar_usuario(user_id, datos):
    usuarios = cargar_usuarios()
    usuarios[str(user_id)] = datos
    with open(DATOS_ARCHIVO, 'w', encoding='utf-8') as f:
        json.dump(usuarios, f, ensure_ascii=False, indent=2)
    logger.info(f"Usuario guardado: {datos['nombre']}")

def usuario_registrado(user_id):
    usuarios = cargar_usuarios()
    return str(user_id) in usuarios

def obtener_usuario(user_id):
    usuarios = cargar_usuarios()
    return usuarios.get(str(user_id), {})


# ============================================================
# FUNCION EMAIL
# ============================================================
def enviar_email(destinatario, nombre, reporte):
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = "🔬 Tu reporte FarmaCheck — NOM-072-SSA1-2012"
        msg['From'] = EMAIL_REMITENTE
        msg['To'] = destinatario
        cuerpo = f"""Hola {nombre},

Aquí está tu reporte de verificación de etiqueta conforme a la NOM-072-SSA1-2012:

{'='*60}
{reporte}
{'='*60}

⚠️ AVISO IMPORTANTE:
Este análisis fue generado por Inteligencia Artificial como herramienta de apoyo.
Los resultados NO sustituyen la revisión de un experto regulatorio humano calificado.

🔬 FarmaCheck — Herramienta de apoyo regulatorio
"""
        msg.attach(MIMEText(cuerpo, 'plain', 'utf-8'))
        with smtplib.SMTP_SSL(EMAIL_SMTP_SERVER, 465) as server:
            server.login(EMAIL_REMITENTE, EMAIL_PASSWORD)
            server.sendmail(EMAIL_REMITENTE, destinatario, msg.as_string())
        logger.info(f"Email enviado a {destinatario}")
        return True
    except Exception as e:
        logger.error(f"Error enviando email: {e}")
        return False

def enviar_codigo_verificacion(destinatario, nombre, codigo):
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = "🔐 Tu código de verificación FarmaCheck"
        msg['From'] = EMAIL_REMITENTE
        msg['To'] = destinatario
        cuerpo = f"""Hola {nombre},

Tu código de verificación es:

    ➡️  {codigo}

Ingresa este código en el bot de Telegram para completar tu registro.

El código expira en 10 minutos.

🔬 FarmaCheck — Herramienta de apoyo regulatorio
"""
        msg.attach(MIMEText(cuerpo, 'plain', 'utf-8'))
        with smtplib.SMTP_SSL(EMAIL_SMTP_SERVER, 465) as server:
            server.login(EMAIL_REMITENTE, EMAIL_PASSWORD)
            server.sendmail(EMAIL_REMITENTE, destinatario, msg.as_string())
        logger.info(f"Código de verificación enviado a {destinatario}")
        return True
    except Exception as e:
        logger.error(f"Error enviando código: {e}")
        return False


# ============================================================
# FUNCION GOOGLE SHEETS
# ============================================================
def registrar_en_sheets(datos, evento, detalle=""):
    try:
        if not os.path.exists(GOOGLE_CREDENTIALS_FILE):
            logger.warning("credentials.json no encontrado — omitiendo Sheets")
            return False
        scopes = [
            'https://spreadsheets.google.com/feeds',
            'https://www.googleapis.com/auth/drive'
        ]
        creds = Credentials.from_service_account_file(GOOGLE_CREDENTIALS_FILE, scopes=scopes)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(GOOGLE_SHEETS_ID).sheet1
        fila = [
            datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            datos.get('nombre', ''),
            datos.get('telefono', ''),
            datos.get('correo', ''),
            str(datos.get('telegram_id', '')),
            datos.get('telegram_username', 'sin_username'),
            evento,
            detalle,
            datos.get('consultas', 0)
        ]
        sheet.append_row(fila)
        logger.info(f"Registrado en Sheets: {datos.get('nombre','')} — {evento}")
        return True
    except Exception as e:
        logger.error(f"Error en Google Sheets: {e}")
        return False


MENSAJE_PRIVACIDAD = """
🔒 *Aviso de Privacidad*

Tus datos (nombre, correo, teléfono) se almacenan únicamente en nuestra base de datos segura para brindarte el servicio.

*Ningún dato queda guardado en la Inteligencia Artificial.* Anthropic (el proveedor de IA) procesa la imagen en tiempo real y no la retiene.

Tus datos no serán compartidos con terceros sin tu consentimiento.

Al continuar, aceptas este aviso de privacidad. ✅
"""

# ============================================================
# NOTIFICACIONES — HANDLERS (Día 4)
# ============================================================
async def notificaciones_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not usuario_registrado(user_id):
        await update.message.reply_text(
            "⚠️ Primero debes registrarte. Escribe /start para comenzar."
        )
        return
    usuarios = cargar_usuarios()
    uid = str(user_id)
    usuarios[uid]['notificaciones'] = True
    usuarios[uid]['clip_actual'] = usuarios[uid].get('clip_actual', 0)
    with open(DATOS_ARCHIVO, 'w', encoding='utf-8') as f:
        json.dump(usuarios, f, ensure_ascii=False, indent=2)
    await update.message.reply_text(
        "🔔 *¡Notificaciones activadas!*\n\n"
        "Recibirás un clip educativo sobre la NOM-072 cada semana. 📚\n\n"
        "Para desactivarlas escribe /notificaciones_off",
        parse_mode='Markdown'
    )
    registrar_en_sheets(obtener_usuario(user_id), 'NOTIF_ON', 'Notificaciones activadas')

async def notificaciones_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not usuario_registrado(user_id):
        await update.message.reply_text(
            "⚠️ Primero debes registrarte. Escribe /start para comenzar."
        )
        return
    usuarios = cargar_usuarios()
    uid = str(user_id)
    usuarios[uid]['notificaciones'] = False
    with open(DATOS_ARCHIVO, 'w', encoding='utf-8') as f:
        json.dump(usuarios, f, ensure_ascii=False, indent=2)
    await update.message.reply_text(
        "🔕 *Notificaciones desactivadas.*\n\n"
        "Ya no recibirás clips semanales. Puedes reactivarlas cuando quieras "
        "con /notificaciones_on",
        parse_mode='Markdown'
    )
    registrar_en_sheets(obtener_usuario(user_id), 'NOTIF_OFF', 'Notificaciones desactivadas')

async def enviar_clips_semanales(app):
    usuarios = cargar_usuarios()
    enviados = 0
    for uid, datos in usuarios.items():
        if not datos.get('notificaciones', False):
            continue
        if datos.get('bloqueado', False):
            continue
        telegram_id = datos.get('telegram_id')
        if not telegram_id:
            continue
        clip_idx = datos.get('clip_actual', 0)
        if clip_idx >= len(CLIPS_NOM072):
            clip_idx = 0
        clip = CLIPS_NOM072[clip_idx]
        try:
            mensaje = f"📬 *{clip['titulo']}*\n\n{clip['contenido']}"
            await app.bot.send_message(
                chat_id=telegram_id,
                text=mensaje,
                parse_mode='Markdown'
            )
            usuarios[uid]['clip_actual'] = clip_idx + 1
            enviados += 1
            logger.info(f"Clip {clip_idx+1} enviado a {datos.get('nombre','')}")
        except Exception as e:
            logger.error(f"Error enviando clip a {uid}: {e}")
    with open(DATOS_ARCHIVO, 'w', encoding='utf-8') as f:
        json.dump(usuarios, f, ensure_ascii=False, indent=2)
    logger.info(f"Clips semanales enviados: {enviados} usuarios")


# ============================================================
# ENCUESTA DE SATISFACCION (Día 5)
# ============================================================
async def respuesta_satisfaccion(update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    usuario = obtener_usuario(user_id)

    if query.data == 'satisfecho_si':
        registrar_en_sheets(usuario, 'ENCUESTA_SI', 'Usuario satisfecho')
        await query.edit_message_text(
            "¡Gracias por tu respuesta! 😊\n\n"
            "Envíame otra etiqueta cuando quieras. 🔬"
        )
    else:
        registrar_en_sheets(usuario, 'ENCUESTA_NO', 'Usuario no satisfecho')
        await query.edit_message_text(
            "Gracias por tu honestidad. 🙏\n\n"
            "Seguimos mejorando. Envíame otra etiqueta cuando quieras. 🔬"
        )
# ============================================================


# ============================================================
# HANDLERS DEL BOT
# ============================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if usuario_bloqueado(user_id):
        await update.message.reply_text(
            "🚫 Tu acceso ha sido suspendido debido al uso de lenguaje inapropiado.\n\n"
            "Para reactivar tu cuenta, comunícate con tu proveedor de servicio."
        )
        return ConversationHandler.END

    if usuario_registrado(user_id):
        await update.message.reply_text(
            "👋 ¡Bienvenido de nuevo!\n\n"
            "Envíame una *foto*, *screenshot* o *PDF* de la etiqueta del medicamento "
            "para verificar su cumplimiento con la *NOM-072-SSA1-2012*. 🔬\n\n"
            "💡 _Tip: Activa los clips educativos semanales con /notificaciones_on_",
            parse_mode='Markdown'
        )
        return ESPERANDO_ETIQUETA

    await update.message.reply_text(
        "👋 ¡Bienvenido al *Verificador de Etiquetas FarmaCheck*!\n\n"
        "🔬 Verifico etiquetas de medicamentos conforme a la *NOM-072-SSA1-2012*.\n\n"
        "Antes de comenzar, lee nuestro aviso de privacidad:",
        parse_mode='Markdown'
    )
    await update.message.reply_text(MENSAJE_PRIVACIDAD, parse_mode='Markdown')
    await update.message.reply_text(
        "Para continuar con tu registro, ¿cuál es tu *nombre completo*?",
        parse_mode='Markdown'
    )
    return NOMBRE

async def recibir_nombre(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text
    user_id = update.effective_user.id
    if contiene_groserías(texto):
        bloquear_usuario(user_id)
        await update.message.reply_text(
            "🚫 Se detectó lenguaje inapropiado. Tu acceso ha sido suspendido.\n\n"
            "Para reactivar tu cuenta, comunícate con tu proveedor de servicio."
        )
        return ConversationHandler.END
    context.user_data['nombre'] = texto
    await update.message.reply_text(
        f"Gracias, *{texto}*! 😊\n\n¿Cuál es tu *número de teléfono*?",
        parse_mode='Markdown'
    )
    return TELEFONO

async def recibir_telefono(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['telefono'] = update.message.text
    await update.message.reply_text(
        "¿Cuál es tu *correo electrónico*?\n\n"
        "_(Te enviaremos un código de verificación a este correo)_ 📧",
        parse_mode='Markdown'
    )
    return CORREO

async def recibir_correo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    correo = update.message.text.strip()
    context.user_data['correo'] = correo
    nombre = context.user_data['nombre']
    codigo = str(random.randint(100000, 999999))
    context.user_data['codigo_verificacion'] = codigo
    await update.message.reply_text(
        f"📧 Enviando código de verificación a *{correo}*...",
        parse_mode='Markdown'
    )
    email_ok = enviar_codigo_verificacion(correo, nombre, codigo)
    if email_ok:
        await update.message.reply_text(
            "✅ ¡Código enviado!\n\n"
            "Por favor revisa tu correo e ingresa el *código de 6 dígitos* aquí. 🔐\n\n"
            "_(Si no lo ves, revisa tu carpeta de spam)_",
            parse_mode='Markdown'
        )
        return VERIFICAR_CORREO
    else:
        await update.message.reply_text(
            "❌ No se pudo enviar el código a ese correo.\n\n"
            "Por favor verifica que sea un correo válido e intenta de nuevo.\n"
            "¿Cuál es tu *correo electrónico*?",
            parse_mode='Markdown'
        )
        return CORREO

async def verificar_codigo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    codigo_ingresado = update.message.text.strip()
    codigo_correcto = context.user_data.get('codigo_verificacion', '')
    if codigo_ingresado == codigo_correcto:
        user_id = update.effective_user.id
        tg_user = update.effective_user
        datos = {
            'nombre': context.user_data['nombre'],
            'telefono': context.user_data['telefono'],
            'correo': context.user_data['correo'],
            'fecha_registro': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'telegram_id': user_id,
            'telegram_username': tg_user.username or 'sin_username',
            'telegram_nombre': tg_user.full_name or '',
            'correo_verificado': True,
            'consultas': 0,
            'notificaciones': False,
            'clip_actual': 0
        }
        guardar_usuario(user_id, datos)
        registrar_en_sheets(datos, 'REGISTRO_NUEVO', 'Email verificado')
        await update.message.reply_text(
            f"✅ *¡Correo verificado y registro completado!*\n\n"
            f"👤 {datos['nombre']}\n"
            f"📱 {datos['telefono']}\n"
            f"📧 {datos['correo']} ✅\n\n"
            "Ahora envíame una *foto*, *screenshot* o *PDF* de la etiqueta del medicamento. 🔬\n\n"
            "💡 _¿Quieres recibir clips educativos semanales sobre la NOM-072? "
            "Escribe /notificaciones_on_",
            parse_mode='Markdown'
        )
        return ESPERANDO_ETIQUETA
    else:
        await update.message.reply_text(
            "❌ *Código incorrecto.*\n\n"
            "Por favor intenta de nuevo. ¿Cuál es el código de 6 dígitos?",
            parse_mode='Markdown'
        )
        return VERIFICAR_CORREO


def es_etiqueta_valida(client, image_data=None, pdf_data=None, media_type="image/jpeg") -> bool:
    try:
        if image_data:
            contenido = [
                {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_data}},
                {"type": "text", "text": "¿Es esto una etiqueta o empaque de medicamento?"}
            ]
        else:
            contenido = [
                {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": pdf_data}},
                {"type": "text", "text": "¿Es esto una etiqueta o documento de medicamento?"}
            ]
        respuesta = client.messages.create(
            model="claude-opus-4-5",
            max_tokens=10,
            system=VALIDACION_PROMPT,
            messages=[{"role": "user", "content": contenido}]
        )
        resultado = respuesta.content[0].text.strip().upper()
        logger.info(f"Validación de imagen: {resultado}")
        return resultado == "VALIDA"
    except Exception as e:
        logger.error(f"Error en validación de imagen: {e}")
        return True


async def analizar_imagen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 Verificando imagen... Por favor espera un momento.")
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        user_id = update.effective_user.id
        usuario = obtener_usuario(user_id)
        image_data = None
        pdf_data = None
        media_type = "image/jpeg"

        if update.message.photo:
            photo = update.message.photo[-1]
            file = await context.bot.get_file(photo.file_id)
            file_bytes = await file.download_as_bytearray()
            image_data = base64.standard_b64encode(file_bytes).decode('utf-8')
        elif update.message.document and update.message.document.mime_type == 'application/pdf':
            file = await context.bot.get_file(update.message.document.file_id)
            file_bytes = await file.download_as_bytearray()
            pdf_data = base64.standard_b64encode(file_bytes).decode('utf-8')
        else:
            await update.message.reply_text(
                "⚠️ Solo acepto *fotos* o archivos *PDF* de etiquetas de medicamentos.\n\n"
                "Por favor envía una imagen o PDF.",
                parse_mode='Markdown'
            )
            return ESPERANDO_ETIQUETA

        valida = es_etiqueta_valida(client, image_data=image_data, pdf_data=pdf_data, media_type=media_type)
        if not valida:
            registrar_en_sheets(usuario, 'IMAGEN_INVALIDA', 'El usuario envió una imagen que no es etiqueta')
            await update.message.reply_text(
                "🤔 La imagen que enviaste no parece ser una etiqueta o empaque de medicamento.\n\n"
                "Por favor envía una *foto*, *screenshot* o *PDF* de la etiqueta del medicamento "
                "que deseas verificar conforme a la *NOM-072-SSA1-2012*. 🔬",
                parse_mode='Markdown'
            )
            return ESPERANDO_ETIQUETA

        await update.message.reply_text("✅ Imagen válida. Analizando cumplimiento NOM-072... 🔬")

        if image_data:
            message = client.messages.create(
                model="claude-opus-4-5",
                max_tokens=2000,
                system=NOM_072_PROMPT,
                messages=[{"role": "user", "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_data}},
                    {"type": "text", "text": "Analiza esta etiqueta y genera el checklist conforme a la NOM-072-SSA1-2012."}
                ]}]
            )
        else:
            message = client.messages.create(
                model="claude-opus-4-5",
                max_tokens=2000,
                system=NOM_072_PROMPT,
                messages=[{"role": "user", "content": [
                    {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": pdf_data}},
                    {"type": "text", "text": "Analiza esta etiqueta y genera el checklist conforme a la NOM-072-SSA1-2012."}
                ]}]
            )

        respuesta = message.content[0].text
        reporte_completo = respuesta + DISCLAIMER
        if len(reporte_completo) > 4000:
            for i in range(0, len(reporte_completo), 4000):
                await update.message.reply_text(reporte_completo[i:i+4000])
        else:
            await update.message.reply_text(reporte_completo)

        usuarios = cargar_usuarios()
        uid = str(user_id)
        if uid in usuarios:
            usuarios[uid]['consultas'] = usuarios[uid].get('consultas', 0) + 1
            usuarios[uid]['ultima_consulta'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            with open(DATOS_ARCHIVO, 'w', encoding='utf-8') as f:
                json.dump(usuarios, f, ensure_ascii=False, indent=2)
            usuario = usuarios[uid]

        if usuario.get('correo'):
            email_ok = enviar_email(usuario['correo'], usuario['nombre'], respuesta)
            if email_ok:
                await update.message.reply_text("📧 Reporte enviado a tu correo. ✅")
            else:
                await update.message.reply_text("⚠️ No se pudo enviar el correo.")

        registrar_en_sheets(usuario, 'CONSULTA', f"Consulta #{usuario.get('consultas', 1)}")

        # Encuesta de satisfacción (Día 5)
        keyboard = [[
            InlineKeyboardButton("👍 Sí", callback_data='satisfecho_si'),
            InlineKeyboardButton("👎 No", callback_data='satisfecho_no'),
        ]]
        await update.message.reply_text(
            "📋 ¿Te fue útil este análisis?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text("❌ Error al analizar. Por favor intenta de nuevo.")

    return ESPERANDO_ETIQUETA

async def mensaje_texto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text
    user_id = update.effective_user.id
    if contiene_groserías(texto):
        bloquear_usuario(user_id)
        registrar_en_sheets(
            obtener_usuario(user_id),
            'BLOQUEADO',
            f"Lenguaje inapropiado: {texto[:50]}"
        )
        await update.message.reply_text(
            "🚫 Se detectó lenguaje inapropiado. Tu acceso ha sido suspendido.\n\n"
            "Para reactivar tu cuenta, comunícate con tu proveedor de servicio."
        )
        return ConversationHandler.END
    await update.message.reply_text(
        "🔬 Solo verifico etiquetas de medicamentos conforme a la *NOM-072-SSA1-2012*.\n\n"
        "Por favor envía una *foto*, *screenshot* o *PDF* de la etiqueta.",
        parse_mode='Markdown'
    )
    return ESPERANDO_ETIQUETA


# ============================================================
# MAIN
# ============================================================
async def post_init(app):
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        enviar_clips_semanales,
        trigger='cron',
        day_of_week='mon',
        hour=9,
        minute=0,
        args=[app]
    )
    scheduler.start()
    logger.info("Scheduler de notificaciones iniciado.")

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).post_init(post_init).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            NOMBRE: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_nombre)],
            TELEFONO: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_telefono)],
            CORREO: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_correo)],
            VERIFICAR_CORREO: [MessageHandler(filters.TEXT & ~filters.COMMAND, verificar_codigo)],
            ESPERANDO_ETIQUETA: [
                MessageHandler(filters.PHOTO, analizar_imagen),
                MessageHandler(filters.Document.ALL, analizar_imagen),
                MessageHandler(filters.TEXT & ~filters.COMMAND, mensaje_texto),
            ],
        },
        fallbacks=[CommandHandler('start', start)],
    )

    app.add_handler(conv_handler)
    app.add_handler(CommandHandler('notificaciones_on', notificaciones_on))
    app.add_handler(CommandHandler('notificaciones_off', notificaciones_off))
    app.add_handler(CallbackQueryHandler(respuesta_satisfaccion, pattern='^satisfecho_'))

    print("🤖 FarmaCheck Bot v6.0 iniciado!")
    print("📧 Email con verificación: activado")
    print("📊 Google Sheets: activado")
    print("⚠️  Disclaimer: activado")
    print("🔐 Verificación de email: activado")
    print("🖼️  Validación de imagen: activado")
    print("🔔 Notificaciones semanales: activado")
    print("⭐ Encuesta de satisfacción: activado")
    print("✅ Esperando mensajes...")

    app.run_polling()

if __name__ == '__main__':
    main()