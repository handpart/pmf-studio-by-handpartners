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

import os, json
from datetime import datetime, timezone

TOKENS_DB_PATH = os.environ.get("TOKENS_DB_PATH", "tokens_db.json")

def validate_token_simple(token: str):
    if not token:
        return False, {"error": "token_missing"}

    if not os.path.exists(TOKENS_DB_PATH):
        return False, {"error": "token_db_missing"}

    try:
        with open(TOKENS_DB_PATH, "r", encoding="utf-8") as f:
            db = json.load(f)
    except Exception:
        return False, {"error": "token_db_broken"}

    rec = db.get(token)
    if not rec:
        return False, {"error": "token_not_found"}

    if not rec.get("active", True):
        return False, {"error": "token_inactive"}

    exp = rec.get("expires_at")
    if exp:
        try:
            exp_dt = datetime.fromisoformat(exp.replace("Z", "+00:00"))
            if exp_dt < datetime.now(timezone.utc):
                return False, {"error": "token_expired"}
        except Exception:
            return False, {"error": "token_expiry_parse_error"}

    return True, rec

