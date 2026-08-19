import logging
import os
import time

import cloudinary
import cloudinary.uploader

logger = logging.getLogger(__name__)

API_KEY = os.getenv("CLOUDINARY_API_KEY", "").strip()
API_SECRET = os.getenv("CLOUDINARY_API_SECRET", "").strip()
CLOUD_NAME = os.getenv("CLOUDINARY_CLOUD_NAME", "").strip()
UPLOAD_PRESET = os.getenv("CLOUDINARY_UPLOAD_PRESET", "").strip()
FOLDER = os.getenv("CLOUDINARY_FOLDER", "foliospace/avatars").strip()


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


def sign_upload_params(user_id: str) -> dict | None:
    if not _configured():
        logger.warning("Cloudinary not configured; avatar upload disabled")
        return None
    timestamp = int(time.time())
    folder = f"{FOLDER}/{user_id}"
    params_to_sign = {
        "folder": folder,
        "timestamp": timestamp,
        "upload_preset": UPLOAD_PRESET,
    }
    signature = cloudinary.utils.api_sign_request(params_to_sign, API_SECRET)
    return {
        "cloud_name": CLOUD_NAME,
        "api_key": API_KEY,
        "timestamp": timestamp,
        "signature": signature,
        "folder": folder,
        "upload_preset": UPLOAD_PRESET,
    }


def destroy_avatar(public_id: str) -> bool:
    if not _configured() or not public_id:
        return False
    if not _cloudinary_config():
        return False
    try:
        result = cloudinary.uploader.destroy(public_id, invalidate=True)
        ok = result.get("result") == "ok"
        if not ok:
            logger.info("cloudinary destroy result=%s public_id=%s", result, public_id)
        return ok
    except Exception as e:
        logger.exception("cloudinary destroy failed for %s: %s", public_id, e)
        return False
