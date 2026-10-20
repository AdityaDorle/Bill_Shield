import hashlib
import json
import os
import secrets
import sqlite3
from pathlib import Path

import requests
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[1]
TABLES = {
    "bills": "provider text, currency text, bill_date text, input_json text, masked_file_link text, created_at text",
    "line_items": "bill_id text, position integer, description text, amount_cents integer, kind text",
    "promises": "bill_id text, expected_cents integer, source text, valid_from text",
    "findings": "bill_id text, promise_id text, verdict text, calculation_json text, created_at text",
    "finding_lines": "bill_id text, finding_id text, line_id text",
    "draft_messages": "bill_id text, finding_id text, draft_text text, tone text, created_at text",
    "message_lines": "bill_id text, message_id text, line_id text",
    "message_events": "bill_id text, message_id text, action text, event_time text, final_text text, words_changed integer",
}


def mode():
    return os.getenv("STORAGE_MODE", "local")


def connect():
    path = Path(os.getenv("LOCAL_DB", str(ROOT / ".local" / "billshield.db")))
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    for table, cols in TABLES.items():
        db.execute(f"create table if not exists {table} (id text primary key, owner_id text not null, {cols})")
        db.execute(f"create index if not exists {table}_owner on {table}(owner_id)")
    return db


def cloud(path, token="", method="GET", data=None, content=None, content_type=None):
    base = os.getenv("SUPABASE_URL", "").rstrip("/")
    key = os.getenv("SUPABASE_PUBLISHABLE_KEY", "")
    if not base or not key:
        raise HTTPException(503, "Set SUPABASE_URL and SUPABASE_PUBLISHABLE_KEY.")
    headers = {"apikey": key, "Prefer": "return=representation"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if content_type:
        headers["Content-Type"] = content_type
    try:
        result = requests.request(method, base + path, headers=headers, json=data, data=content, timeout=25)
    except requests.RequestException:
        raise HTTPException(503, "Supabase could not be reached. Please retry.")
    if not result.ok:
        # Never expose provider payloads, cookies, or credentials to the browser.
        raise HTTPException(503, f"Supabase request failed ({result.status_code}). Run supabase/schema.sql and enable anonymous sign-ins.")
    return result.json() if result.content else None


def identity(request, response):
    secure = os.getenv("COOKIE_SECURE", "false").lower() == "true"
    opts = dict(httponly=True, samesite="strict", secure=secure, max_age=60 * 60 * 24 * 30)
    if mode() == "supabase":
        token = request.cookies.get("bs_access", "")
        if token:
            try:
                user = cloud("/auth/v1/user", token)
                return user["id"], token
            except HTTPException:
                refresh = request.cookies.get("bs_refresh", "")
                if not refresh:
                    raise HTTPException(401, "Your session expired. Clear this site's cookies to start again.")
                auth = cloud("/auth/v1/token?grant_type=refresh_token", method="POST", data={"refresh_token": refresh})
        else:
            auth = cloud("/auth/v1/signup", method="POST", data={})
        response.set_cookie("bs_access", auth["access_token"], **opts)
        response.set_cookie("bs_refresh", auth["refresh_token"], **opts)
        return auth["user"]["id"], auth["access_token"]
    if os.getenv("VERCEL"):
        raise HTTPException(503, "Production requires STORAGE_MODE=supabase. Local SQLite is not durable on Vercel.")
    token = request.cookies.get("bs_local", "")
    if len(token) != 64:
        token = secrets.token_hex(32)
        response.set_cookie("bs_local", token, **opts)
    return hashlib.sha256(token.encode()).hexdigest(), ""


class Store:
    def __init__(self, owner, token=""):
        self.owner, self.token = owner, token

    def rows(self, table, **filters):
        assert table in TABLES
        filters = {"owner_id": self.owner, **filters}
        if mode() == "supabase":
            from urllib.parse import urlencode
            return cloud("/rest/v1/" + table + "?" + urlencode({k: "eq." + str(v) for k, v in filters.items()}), self.token)
        with connect() as db:
            return [dict(r) for r in db.execute(f"select * from {table} where " + " and ".join(f"{k}=?" for k in filters), list(filters.values()))]

    def insert_many(self, records):
        if mode() == "supabase":
            # One RPC transaction prevents partially saved bills and broken links.
            return cloud("/rest/v1/rpc/save_records", self.token, "POST", {"records": records})
        with connect() as db:
            for table, rows in records.items():
                assert table in TABLES
                for row in rows:
                    assert row["owner_id"] == self.owner
                    db.execute(f"insert into {table} ({','.join(row)}) values ({','.join('?' for _ in row)})", list(row.values()))

    def bill(self, bill_id):
        rows = self.rows("bills", id=bill_id)
        if not rows:
            raise HTTPException(404, "Bill not found.")
        return rows[0]

    def file(self, bill_id, content=None):
        self.bill(bill_id)
        path = f"{self.owner}/{bill_id}.svg"
        if mode() == "supabase":
            if content is not None:
                cloud("/storage/v1/object/masked-bills/" + path, self.token, "POST", content=content, content_type="image/svg+xml")
                return
            result = cloud("/storage/v1/object/sign/masked-bills/" + path, self.token, "POST", {"expiresIn": 60})
            return os.environ["SUPABASE_URL"].rstrip("/") + "/storage/v1" + result["signedURL"]
        target = ROOT / ".local" / "files" / self.owner / f"{bill_id}.svg"
        if content is not None:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        else:
            if not target.exists():
                raise HTTPException(404, "No masked snapshot is available.")
            return target

    def delete(self, bill_id):
        self.bill(bill_id)
        if mode() == "supabase":
            cloud("/rest/v1/bills?id=eq." + bill_id, self.token, "DELETE")
            cloud("/storage/v1/object/masked-bills", self.token, "DELETE", {"prefixes": [f"{self.owner}/{bill_id}.svg"]})
        else:
            with connect() as db:
                for table in reversed(TABLES):
                    key = "id" if table == "bills" else "bill_id"
                    db.execute(f"delete from {table} where {key}=? and owner_id=?", (bill_id, self.owner))
            (ROOT / ".local" / "files" / self.owner / f"{bill_id}.svg").unlink(missing_ok=True)
