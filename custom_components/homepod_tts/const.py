DOMAIN = "homepod_tts"
PLATFORMS = ["notify"]

CONF_HOMEPOD_IDENTIFIER = "homepod_identifier"
CONF_GEMINI_API_KEY = "gemini_api_key"
CONF_CHIME_ENABLED = "chime_enabled"
CONF_CHIME_PATH = "chime_path"
CONF_DEFAULT_VOLUME = "default_volume"
CONF_RESTORE_VOLUME = "restore_volume"
CONF_TTS_VOICE = "tts_voice"
CONF_COMPRESS_TTS = "compress_tts"

DEFAULT_CHIME_ENABLED = True
DEFAULT_VOLUME = 0.5
DEFAULT_RESTORE_VOLUME = True
DEFAULT_TTS_VOICE = "Aoede"
DEFAULT_COMPRESS_TTS = True

GEMINI_TTS_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/"
    "models/gemini-2.5-flash-preview-tts:generateContent"
)

GEMINI_TTS_SAMPLE_RATE = 24000
GEMINI_TTS_CHANNELS = 1

AIRPLAY_SAMPLE_RATE = 44100
AIRPLAY_CHANNELS = 2
