import json
import os
from datetime import datetime, timezone

TOKENS_DB_PATH = os.environ.get("TOKENS_DB_PATH", "tokens_db.json")

def _load_tokens():
    if not os.path.exists(TOKENS_DB_PATH):
        return {}
    try:
        with open(TOKENS_DB_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def validate_token_simple(token: str):
    """
    Return (is_valid: bool, payload: dict_or_error)
    payload when valid: {token, label, perm, expires_at (iso)}
    """
    if not token:
        return False, {"error": "missing_token"}

    db = _load_tokens()
    rec = db.get(token)
    if not rec:
        return False, {"error": "token_not_found"}

    if not rec.get("active", True):
        return False, {"error": "token_revoked"}

    expires = rec.get("expires_at")
    if not expires:
        return False, {"error": "no_expiry_set"}

    try:
        exp_dt = datetime.fromisoformat(expires)
    except Exception:
        return False, {"error": "invalid_expiry_format"}

    now = datetime.now(timezone.utc)
    if exp_dt.tzinfo is None:
        exp_dt = exp_dt.replace(tzinfo=timezone.utc)
    if now > exp_dt:
        return False, {"error": "token_expired", "expired_at": expires}

    return True, {
        "token": token,
        "label": rec.get("label", ""),
        "perm": rec.get("perm", ""),
        "expires_at": expires
    }
