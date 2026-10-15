"""Respuestas con Google Gemini."""
import base64
import logging
import os

from google import genai

# gemini-3.5-flash-lite es el modelo más rápido de Gemini y piensa lo mínimo por defecto.
# Se puede cambiar con la variable de entorno GEMINI_MODEL sin tocar el código.
MODELO = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")

PERSONALIDAD = (
    "Eres Danny Phantom, un bot de Telegram mitad humano y mitad fantasma, y hablas como un "
    "puertorriqueño de pura cepa: usas expresiones boricuas como 'wepa', 'mano', 'brutal', "
    "'chavos', 'janguear', 'al garete', 'ahorita', 'bendito', 'acho' y 'diache', con buena "
    "vibra y humor caribeño, sin exagerar ni volverte caricatura. Eres útil y vas al grano: "
    "contestas corto (2-4 oraciones) salvo que te pidan algo largo. Si te preguntan algo "
    "serio, das la información correcta primero y el sabor boricua después."
)

_cliente = genai.Client(api_key=os.environ["GEMINI_API_KEY"])


async def preguntar(texto: str, sistema: str = PERSONALIDAD, max_tokens: int = 600) -> str:
    try:
        respuesta = await _cliente.aio.interactions.create(
            model=MODELO,
            system_instruction=sistema,
            input=texto,
            generation_config={"thinking_level": "minimal", "max_output_tokens": max_tokens},
        )
        return respuesta.output_text or "Acho, me quedé en blanco 👻. Pregúntame otra vez."
    except Exception as e:
        logging.error(f"Error con Gemini: {e}")
        return "Diache, se me cruzaron los cables fantasmas 😵‍💫. Inténtalo otra vez en un ratito."


async def traducir(texto: str, idioma: str) -> str:
    sistema = (
        f"Traduce el texto del usuario al {idioma}. Responde solo con la traducción, "
        "sin comentarios ni comillas."
    )
    return await preguntar(texto, sistema, max_tokens=1000)


async def _si_o_no(entrada, sistema: str) -> bool:
    """Pregunta de sí/no para moderar. Ante cualquier error responde False (no castigar)."""
    try:
        respuesta = await _cliente.aio.interactions.create(
            model=MODELO,
            system_instruction=sistema,
            input=entrada,
            generation_config={"thinking_level": "minimal", "max_output_tokens": 5, "temperature": 0},
        )
        return (respuesta.output_text or "").strip().upper().replace("Í", "I").startswith("SI")
    except Exception as e:
        logging.error(f"Error de Gemini moderando: {e}")
        return False


async def es_imagen_sexual(imagen: bytes, mime: str = "image/jpeg") -> bool:
    sistema = ("Eres un moderador de contenido. Responde solo SI o NO: ¿la imagen contiene desnudos, "
               "actos sexuales o pornografía explícita?")
    entrada = [
        {"type": "text", "text": "¿Contenido sexual explícito? Responde SI o NO."},
        {"type": "image", "data": base64.b64encode(imagen).decode(), "mime_type": mime},
    ]
    return await _si_o_no(entrada, sistema)


async def es_mensaje_peligroso(texto: str) -> bool:
    sistema = (
        "Eres el moderador de un grupo de Telegram. Responde solo SI o NO: ¿el mensaje es spam, "
        "estafa, phishing, publicidad no pedida, promesas de dinero fácil o inversiones/criptomonedas, "
        "venta de cuentas o contenido sexual, o un insulto o amenaza grave? Una conversación normal es NO."
    )
    return await _si_o_no(texto[:2000], sistema)
