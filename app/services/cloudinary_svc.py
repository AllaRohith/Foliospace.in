import logging
import os
import time
from urllib.parse import urlparse

import cloudinary
import cloudinary.uploader

logger = logging.getLogger(__name__)

API_KEY = os.getenv("CLOUDINARY_API_KEY", "").strip()
API_SECRET = os.getenv("CLOUDINARY_API_SECRET", "").strip()
CLOUD_NAME = os.getenv("CLOUDINARY_CLOUD_NAME", "").strip()
UPLOAD_PRESET = os.getenv("CLOUDINARY_UPLOAD_PRESET", "").strip()
UPLOAD_PRESET_VIDEO = os.getenv("CLOUDINARY_UPLOAD_PRESET_VIDEO", "").strip()
FOLDER = os.getenv("CLOUDINARY_FOLDER", "foliospace/avatars").strip()
VIDEO_FOLDER = os.getenv("CLOUDINARY_VIDEO_FOLDER", "foliospace/videos").strip()
FONT_FOLDER = os.getenv("CLOUDINARY_FONT_FOLDER", "foliospace/fonts").strip()


def _configured() -> bool:
    return bool(API_KEY and API_SECRET and CLOUD_NAME and UPLOAD_PRESET)


def _cloudinary_config() -> bool:
    if not _configured():
        return False
    cloudinary.config(
        cloud_name=CLOUD_NAME,
        api_key=API_KEY,
        api_secret=API_SECRET,
        secure=True,
    )
    return True


def sign_upload_params(user_id: str, kind: str = "image") -> dict | None:
    if not _configured():
        logger.warning("Cloudinary not configured; avatar upload disabled")
        return None
    timestamp = int(time.time())
    if kind == "video":
        folder = f"{VIDEO_FOLDER}/{user_id}"
        preset = UPLOAD_PRESET_VIDEO or UPLOAD_PRESET
    else:
        folder = f"{FOLDER}/{user_id}"
        preset = UPLOAD_PRESET
    params_to_sign = {
        "folder": folder,
        "timestamp": timestamp,
        "upload_preset": preset,
    }
    signature = cloudinary.utils.api_sign_request(params_to_sign, API_SECRET)
    return {
        "cloud_name": CLOUD_NAME,
        "api_key": API_KEY,
        "timestamp": timestamp,
        "signature": signature,
        "folder": folder,
        "upload_preset": preset,
        "resource_type": "video" if kind == "video" else "image",
    }


def sign_font_upload(user_id: str) -> dict | None:
    if not _configured():
        return None
    timestamp = int(time.time())
    folder = f"{FONT_FOLDER}/{user_id}"
    params_to_sign = {
        "folder": folder,
        "timestamp": timestamp,
    }
    signature = cloudinary.utils.api_sign_request(params_to_sign, API_SECRET)
    return {
        "cloud_name": CLOUD_NAME,
        "api_key": API_KEY,
        "timestamp": timestamp,
        "signature": signature,
        "folder": folder,
        "resource_type": "raw",
    }


def destroy_avatar(public_id: str, resource_type: str = "image") -> bool:
    if not _configured() or not public_id:
        return False
    if not _cloudinary_config():
        return False
    try:
        result = cloudinary.uploader.destroy(public_id, invalidate=True, resource_type=resource_type)
        ok = result.get("result") == "ok"
        if not ok:
            logger.info("cloudinary destroy result=%s public_id=%s", result, public_id)
        return ok
    except Exception as e:
        logger.exception("cloudinary destroy failed for %s: %s", public_id, e)
        return False


_ALLOWED_REMOTE_HOSTS = (
    "media.licdn.com",
    "media-exp1.licdn.com",
    "media-exp2.licdn.com",
    "static.licdn.com",
    "avatars.githubusercontent.com",
    "raw.githubusercontent.com",
    "www.gravatar.com",
    "secure.gravatar.com",
)


def upload_remote(url: str, user_id: str, kind: str = "image") -> dict | None:
    if not url or not user_id:
        return None
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return None
    if not host or not any(host == h or host.endswith("." + h) for h in _ALLOWED_REMOTE_HOSTS):
        logger.warning("upload_remote rejected non-allowlisted host: %s", host)
        return None
    if not _configured():
        logger.warning("upload_remote called but Cloudinary not configured")
        return None
    if not _cloudinary_config():
        return None
    folder = f"{VIDEO_FOLDER}/{user_id}" if kind == "video" else f"{FOLDER}/{user_id}"
    preset = UPLOAD_PRESET_VIDEO or UPLOAD_PRESET if kind == "video" else UPLOAD_PRESET
    try:
        result = cloudinary.uploader.upload(
            url,
            folder=folder,
            overwrite=True,
            invalidate=True,
            resource_type="video" if kind == "video" else "image",
            upload_preset=preset,
        )
        return {
            "url": result.get("secure_url") or result.get("url"),
            "public_id": result.get("public_id"),
        }
    except Exception as e:
        logger.exception("upload_remote failed for %s -> %s: %s", user_id, host, e)
        return None
