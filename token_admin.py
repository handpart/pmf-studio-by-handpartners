#!/usr/bin/env python3
"""Token admin tool for PMF Studio.

기능:
- 토큰 생성 (--create)
- 목록 조회 (--list)
- 회수 (--revoke TOKEN)
- 기간 연장 (--extend TOKEN DAYS)
"""
import argparse
import json
import os
from datetime import datetime, timedelta, timezone

TOKENS_DB_PATH = os.environ.get("TOKENS_DB_PATH", "tokens_db.json")

def _load_db():
    if not os.path.exists(TOKENS_DB_PATH):
        return {}
    try:
        with open(TOKENS_DB_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _save_db(db):
    with open(TOKENS_DB_PATH, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

def create_token(days: int, label: str, perm: str):
    import uuid
    token = uuid.uuid4().hex
    expires_at = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
    db = _load_db()
    db[token] = {
        "label": label,
        "perm": perm,
        "expires_at": expires_at,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "active": True
    }
    _save_db(db)
    return token, expires_at

def list_tokens():
    db = _load_db()
    for t, r in db.items():
        print(t, "|", r.get("label",""), "|", r.get("perm",""), "|", r.get("expires_at",""), "| active:", r.get("active",True))

def revoke_token(token):
    db = _load_db()
    if token in db:
        db[token]["active"] = False
        _save_db(db)
        print("Revoked:", token)
    else:
        print("Token not found")

def extend_token(token, add_days):
    db = _load_db()
    if token in db:
        from datetime import datetime, timedelta
        old = datetime.fromisoformat(db[token]["expires_at"])
        new = (old + timedelta(days=add_days)).isoformat()
        db[token]["expires_at"] = new
        _save_db(db)
        print("Extended:", token, "new expiry:", new)
    else:
        print("Token not found")

if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Token admin tool")
    p.add_argument("--create", action="store_true", help="Create a token")
    p.add_argument("--days", type=int, default=7, help="Days until expiry")
    p.add_argument("--label", type=str, default="", help="Label/name")
    p.add_argument("--perm", type=str, default="trial", help="Permission tag")
    p.add_argument("--list", action="store_true", help="List tokens")
    p.add_argument("--revoke", type=str, help="Revoke token (provide token string)")
    p.add_argument("--extend", nargs=2, metavar=("TOKEN","DAYS"), help="Extend token by DAYS")
    args = p.parse_args()

    if args.create:
        token, exp = create_token(args.days, args.label, args.perm)
        print("TOKEN:", token)
        print("URL example: https://your-deployed-url/report?token=" + token)
        print("Expires at (UTC):", exp)
    elif args.list:
        list_tokens()
    elif args.revoke:
        revoke_token(args.revoke)
    elif args.extend:
        tok, days = args.extend
        extend_token(tok, int(days))
    else:
        p.print_help()
