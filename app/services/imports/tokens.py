import logging
import os

logger = logging.getLogger(__name__)

_FERNET = None
_READY = False


def _configured() -> bool:
    return _get_fernet() is not None


def _get_fernet():
    global _FERNET, _READY
    if _READY:
        return _FERNET
    raw = os.getenv("IMPORT_TOKEN_KEY", "").strip()
    if not raw:
        _READY = False
        _FERNET = None
        return None
    try:
        from cryptography.fernet import Fernet
        _FERNET = Fernet(raw.encode("ascii"))
        _READY = True
    except Exception as e:
        logger.warning("IMPORT_TOKEN_KEY unusable: %s", e)
        _READY = False
        _FERNET = None
    return _FERNET


def encrypt(plaintext: str) -> str | None:
    f = _get_fernet()
    if not f or not plaintext:
        return None
    try:
        return f.encrypt(plaintext.encode("utf-8")).decode("ascii")
    except Exception as e:
        logger.warning("token encrypt failed: %s", e)
        return None


def decrypt(ciphertext: str | None) -> str | None:
    if not ciphertext:
        return None
    f = _get_fernet()
    if not f:
        return None
    try:
        return f.decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except Exception as e:
        logger.warning("token decrypt failed: %s", e)
        return None
