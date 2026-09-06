import os
import asyncio
import itertools
import threading
from typing import List, Dict, Optional

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

GAPGPT_BASE_URL = "https://api.gapgpt.app/v1"

# --- مقادیر پیش‌فرض اولیه (از متغیرهای محیطی، فقط برای اولین اجرا) ---
DEFAULT_MODEL = os.environ.get("GAPGPT_MODEL", "claude-3-5-sonnet-20241022")
DEFAULT_STT_MODEL = os.environ.get("GAPGPT_STT_MODEL", "whisper-1")
DEFAULT_TTS_MODEL = os.environ.get("GAPGPT_TTS_MODEL", "tts-1")
DEFAULT_TTS_VOICE = os.environ.get("GAPGPT_TTS_VOICE", "alloy")

_env_raw_keys = os.environ.get("GAPGPT_API_KEYS", "")
_env_keys = [k.strip() for k in _env_raw_keys.split(",") if k.strip()]
_single_env_key = os.environ.get("GAPGPT_API_KEY")
if _single_env_key and _single_env_key not in _env_keys:
    _env_keys.append(_single_env_key)
DEFAULT_API_KEYS = _env_keys

SYSTEM_PROMPT = (
    "تو «دستیار هوشمند» داخل اپلیکیشن پیام‌رسان چت‌یار هستی. به‌صورت دوستانه، "
    "مختصر و مفید پاسخ بده. اگر کاربر به زبان دیگری پیام داد، به همان زبان جواب بده. "
    "پاسخ‌هایت را کوتاه و مکالمه‌ای نگه دار، مگر اینکه کاربر توضیح مفصل بخواهد. "
    "برای تاکید روی یک کلمه یا عبارت مهم، آن را بین دو ستاره بگذار، مثلاً **مهم**."
)

# --- وضعیت runtime (قابل تغییر از پنل ادمین، بدون نیاز به ری‌استارت سرور) ---
_current_model = DEFAULT_MODEL
_current_stt_model = DEFAULT_STT_MODEL
_current_tts_model = DEFAULT_TTS_MODEL
_current_tts_voice = DEFAULT_TTS_VOICE
_current_keys = list(DEFAULT_API_KEYS)
_key_cycle = itertools.cycle(_current_keys) if _current_keys else None
_state_lock = threading.Lock()


def get_model() -> str:
    with _state_lock:
        return _current_model


def set_model(model_name: str) -> None:
    global _current_model
    with _state_lock:
        _current_model = model_name.strip()


def get_stt_model() -> str:
    with _state_lock:
        return _current_stt_model


def set_stt_model(model_name: str) -> None:
    global _current_stt_model
    with _state_lock:
        _current_stt_model = model_name.strip()


def get_tts_model() -> str:
    with _state_lock:
        return _current_tts_model


def set_tts_model(model_name: str) -> None:
    global _current_tts_model
    with _state_lock:
        _current_tts_model = model_name.strip()


def get_tts_voice() -> str:
    with _state_lock:
        return _current_tts_voice


def set_tts_voice(voice_name: str) -> None:
    global _current_tts_voice
    with _state_lock:
        _current_tts_voice = voice_name.strip()


def get_api_keys() -> List[str]:
    with _state_lock:
        return list(_current_keys)


def set_api_keys(keys: List[str]) -> None:
    """keys: لیست کلیدها (از قبل trim‌شده و خالی‌ها حذف‌شده)."""
    global _current_keys, _key_cycle
    with _state_lock:
        _current_keys = keys
        _key_cycle = itertools.cycle(_current_keys) if _current_keys else None


def _next_key() -> str:
    with _state_lock:
        if _key_cycle is None:
            return ""
        return next(_key_cycle)


def _mask(key: str) -> str:
    return key[:8] + "..." + key[-4:] if len(key) > 12 else "***"


def _with_key_rotation(fn, label: str):
    """
    fn: تابعی که یک آرگومان (api_key) می‌گیرد و روی موفقیت مقدار بازمی‌گرداند،
    و در صورت خطا Exception پرتاب می‌کند.
    یکی‌یکی کلیدها را امتحان می‌کند تا یکی جواب بدهد.
    """
    keys = get_api_keys()
    if not keys:
        raise RuntimeError("هیچ کلید API تنظیم نشده — از پنل ادمین یک کلید اضافه کن.")

    last_error = None
    attempts = min(len(keys), 10)
    for _ in range(attempts):
        key = _next_key()
        if not key:
            break
        try:
            return fn(key)
        except Exception as e:
            print(f"=== [ai_bot:{label}] خطا با کلید {_mask(key)}: {e}")
            last_error = e
            continue
    raise last_error or RuntimeError("همه‌ی کلیدها با خطا مواجه شدند")


def _call_chat(api_key: str, messages: list, model: str) -> str:
    client = OpenAI(api_key=api_key, base_url=GAPGPT_BASE_URL)
    response = client.chat.completions.create(
        model=model,
        max_tokens=2048,
        messages=messages,
    )
    choice = response.choices[0]
    text = (choice.message.content or "").strip()
    if not text:
        print("=== [ai_bot] پاسخ خالی از GapGPT دریافت شد ===")
        print("model:", model)
        print("finish_reason:", getattr(choice, "finish_reason", None))
        print("raw message object:", choice.message)
        print("=============================================")
        return ""
    return text


def _sync_call(history: List[Dict[str, str]]) -> str:
    if OpenAI is None:
        return "کتابخانه‌ی openai نصب نشده. توی محیط بک‌اند بزن: pip install openai"

    model = get_model()
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history

    try:
        text = _with_key_rotation(lambda k: _call_chat(k, messages, model), "chat")
        return text or "متوجه نشدم؛ می‌شه دوباره و واضح‌تر بگی؟"
    except Exception as e:
        msg = str(e)
        if "429" in msg or "rate" in msg.lower():
            return "دستیار هوشمند الان خیلی شلوغه (همه‌ی کلیدها به محدودیت خوردند) — چند لحظه دیگه دوباره امتحان کن."
        if "model_not_found" in msg or "404" in msg:
            return f"مدل «{model}» روی حساب فعلی در دسترس نیست. از پنل ادمین اسم مدل رو عوض کن."
        return f"خطا در ارتباط با دستیار هوشمند (GapGPT): {msg}"


async def get_ai_reply(history: List[Dict[str, str]]) -> str:
    """history: list of {"role": "user"|"assistant", "content": "..."} in chronological order."""
    return await asyncio.to_thread(_sync_call, history)


# ---------- گفتار به متن (Speech-to-Text) ----------

def _call_transcribe(api_key: str, file_path: str, model: str) -> str:
    client = OpenAI(api_key=api_key, base_url=GAPGPT_BASE_URL)
    with open(file_path, "rb") as f:
        result = client.audio.transcriptions.create(model=model, file=f)
    return (getattr(result, "text", "") or "").strip()


def _sync_transcribe(file_path: str) -> Optional[str]:
    if OpenAI is None:
        return None
    model = get_stt_model()
    try:
        text = _with_key_rotation(lambda k: _call_transcribe(k, file_path, model), "stt")
        return text or None
    except Exception as e:
        print(f"=== [ai_bot:stt] خطا در تبدیل گفتار به متن (مدل {model}): {e}")
        return None


async def transcribe_audio(file_path: str) -> Optional[str]:
    return await asyncio.to_thread(_sync_transcribe, file_path)


# ---------- متن به گفتار (Text-to-Speech) ----------

def _call_synthesize(api_key: str, text: str, model: str, voice: str, out_path: str) -> bool:
    client = OpenAI(api_key=api_key, base_url=GAPGPT_BASE_URL)
    with client.audio.speech.with_streaming_response.create(
        model=model, voice=voice, input=text,
    ) as response:
        response.stream_to_file(out_path)
    return os.path.exists(out_path) and os.path.getsize(out_path) > 0


def _sync_synthesize(text: str, out_path: str) -> bool:
    if OpenAI is None:
        return False
    model = get_tts_model()
    voice = get_tts_voice()
    try:
        return _with_key_rotation(lambda k: _call_synthesize(k, text, model, voice, out_path), "tts")
    except Exception as e:
        print(f"=== [ai_bot:tts] خطا در تبدیل متن به گفتار (مدل {model}): {e}")
        return False


async def synthesize_speech(text: str, out_path: str) -> bool:
    """صدا را در مسیر out_path (مثلاً یک فایل .mp3) ذخیره می‌کند. در صورت موفقیت True برمی‌گرداند."""
    return await asyncio.to_thread(_sync_synthesize, text, out_path)
