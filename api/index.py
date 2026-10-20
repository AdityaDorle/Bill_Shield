import html
import json
import os
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
from . import ai
from .domain import BillInput, analyze, cents, draft_message, mask, money, words_changed
from .store import ROOT, Store, identity, mode

app = FastAPI(title="BillShield", docs_url="/api/docs")
limits = defaultdict(deque)


@app.middleware("http")
async def protections(request, call_next):
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("origin")
        if origin and origin.rstrip("/") != str(request.base_url).rstrip("/"):
            return Response("Cross-origin writes are not allowed.", status_code=403)
        try:
            size = int(request.headers.get("content-length", 0))
        except ValueError:
            return Response("Invalid content length.", status_code=400)
        if size > 12 * 1024 * 1024:
            return Response("Upload exceeds 10 MB.", status_code=413)
    result = await call_next(request)
    result.headers["X-Content-Type-Options"] = "nosniff"
    result.headers["Referrer-Policy"] = "same-origin"
    result.headers["X-Frame-Options"] = "DENY"
    result.headers["Cache-Control"] = "no-store"
    result.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob: data:; connect-src 'self'; frame-src 'self' blob:; object-src 'none'; base-uri 'self'; form-action 'self'"
    return result


def storage(request: Request, response: Response):
    return Store(*identity(request, response))


def rate_limit(store):
    now = time.monotonic()
    hits = limits[store.owner]
    while hits and now - hits[0] > 60:
        hits.popleft()
    if len(hits) >= 8:
        raise HTTPException(429, "Please wait a minute before making another AI request.")
    hits.append(now)


def stamp():
    return datetime.now(timezone.utc).isoformat()


def row(store, **data):
    return {"id": str(uuid4()), "owner_id": store.owner, **data}


@app.get("/api/health")
def health():
    return {"ok": True, "storage": mode(), "ai_configured": bool(os.getenv("GROQ_API_KEY"))}


@app.post("/api/extract")
def extract(file: UploadFile = File(...), consent: bool = Form(False), store=Depends(storage)):
    if not consent:
        raise HTTPException(400, "Confirm that this bill may be sent to Groq for extraction.")
    rate_limit(store)
    raw = file.file.read(10 * 1024 * 1024 + 1)
    if len(raw) > 10 * 1024 * 1024:
        raise HTTPException(413, "Maximum upload size is 10 MB.")
    return ai.extract(raw, raw.startswith(b"%PDF"))


@app.get("/api/bills")
def list_bills(store=Depends(storage)):
    bills = store.rows("bills")
    findings = {r["bill_id"]: r for r in store.rows("findings")}
    events = store.rows("message_events")
    return [{
        **{key: b[key] for key in ("id", "provider", "currency", "bill_date", "created_at")},
        "finding": json.loads(findings[b["id"]]["calculation_json"]),
        "sent": any(e["bill_id"] == b["id"] and e["action"] == "sent" for e in events),
    } for b in sorted(bills, key=lambda x: x["created_at"], reverse=True) if b["id"] in findings]


@app.post("/api/bills")
def create_bill(body: BillInput, store=Depends(storage)):
    # Persist only reviewed structured fields. Original uploads are never written to disk.
    clean = body.model_dump(mode="json")
    for key in ("provider", "promise_source", "evidence"):
        clean[key] = mask(clean[key])
    for line in clean["lines"]:
        line["description"] = mask(line["description"])
    body = BillInput.model_validate(clean)
    old_bills = {b["id"]: b for b in store.rows("bills")}
    previous = [{**line, **{k: old_bills[line["bill_id"]][k] for k in ("provider", "currency", "bill_date")}}
        for line in store.rows("line_items") if line["bill_id"] in old_bills]
    finding = analyze(body, previous)
    bill = row(store, provider=body.provider, currency=body.currency, bill_date=body.bill_date.isoformat(),
               input_json=json.dumps(clean), masked_file_link="", created_at=stamp())
    bill["masked_file_link"] = f'/api/bills/{bill["id"]}/snapshot'
    lines = [row(store, bill_id=bill["id"], position=i, description=x.description,
                 amount_cents=cents(x.amount), kind=x.kind) for i, x in enumerate(body.lines)]
    promise = row(store, bill_id=bill["id"], expected_cents=cents(body.expected),
                  source=body.promise_source, valid_from=(body.promise_date or body.bill_date).isoformat())
    result = row(store, bill_id=bill["id"], promise_id=promise["id"], verdict=finding["verdict"],
                 calculation_json=json.dumps(finding), created_at=stamp())
    store.insert_many({"bills": [bill], "line_items": lines, "promises": [promise], "findings": [result],
        "finding_lines": [row(store, bill_id=bill["id"], finding_id=result["id"], line_id=l["id"]) for l in lines]})
    # Store a sanitized reconstruction, not a deceptively "redacted" original photograph.
    text = ["BILLSHIELD / REVIEWED BILL SNAPSHOT", "Reconstructed from confirmed fields; not the original bill.",
            f'{body.provider} | {body.currency} | {body.bill_date}', ""] + [
                f'{i+1}. {l["description"]}   {body.currency} {money(l["amount_cents"])}' for i, l in enumerate(lines)
            ] + ["", f'Printed total: {body.currency} {money(cents(body.total))}']
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="950" height="{80+len(text)*30}"><rect width="100%" height="100%" fill="#fff"/>'
    svg += "".join(f'<text x="30" y="{45+i*30}" font-family="monospace" font-size="15">{html.escape(t)}</text>' for i, t in enumerate(text)) + "</svg>"
    warning = None
    try:
        store.file(bill["id"], svg.encode())
    except HTTPException:
        warning = "Review saved, but the sanitized snapshot could not be stored. Check the private storage bucket."
    return {"id": bill["id"], "finding": finding, "snapshot_warning": warning}


@app.get("/api/bills/{bill_id}")
def get_bill(bill_id: UUID, store=Depends(storage)):
    bid = str(bill_id)
    bill = store.bill(bid)
    return {**bill, "input": json.loads(bill["input_json"]),
            "lines": sorted(store.rows("line_items", bill_id=bid), key=lambda x: x["position"]),
            "finding": json.loads(store.rows("findings", bill_id=bid)[0]["calculation_json"]),
            "drafts": sorted(store.rows("draft_messages", bill_id=bid), key=lambda x: x["created_at"]),
            "events": sorted(store.rows("message_events", bill_id=bid), key=lambda x: x["event_time"])}


@app.get("/api/bills/{bill_id}/snapshot")
def snapshot(bill_id: UUID, store=Depends(storage)):
    location = store.file(str(bill_id))
    return RedirectResponse(location) if isinstance(location, str) else FileResponse(location, media_type="image/svg+xml")


@app.delete("/api/bills/{bill_id}")
def delete_bill(bill_id: UUID, store=Depends(storage)):
    store.delete(str(bill_id))
    return {"deleted": True}


class DraftInput(BaseModel):
    positions: list[int] = Field(min_length=1, max_length=100)
    tone: Literal["polite", "firm", "concise"] = "polite"
    use_ai: bool = False


@app.post("/api/bills/{bill_id}/draft")
def create_draft(bill_id: UUID, body: DraftInput, store=Depends(storage)):
    bid = str(bill_id)
    bill = store.bill(bid)
    finding = store.rows("findings", bill_id=bid)[0]
    result = json.loads(finding["calculation_json"])
    positions = sorted(set(body.positions))
    if any(p < 0 or p >= len(result["lines"]) for p in positions):
        raise HTTPException(422, "Select valid bill lines.")
    text = draft_message(bill, result, positions, body.tone)
    if body.use_ai:
        rate_limit(store)
        text = ai.rephrase(text, body.tone)
    draft = row(store, bill_id=bid, finding_id=finding["id"], draft_text=text, tone=body.tone, created_at=stamp())
    lines = store.rows("line_items", bill_id=bid)
    store.insert_many({"draft_messages": [draft], "message_lines": [
        row(store, bill_id=bid, message_id=draft["id"], line_id=l["id"]) for l in lines if l["position"] in positions]})
    return draft


class EventInput(BaseModel):
    action: Literal["copied", "email_opened", "sent", "edited"]
    final_text: str = Field(min_length=1, max_length=8000)


@app.post("/api/messages/{message_id}/events")
def event(message_id: UUID, body: EventInput, store=Depends(storage)):
    drafts = store.rows("draft_messages", id=str(message_id))
    if not drafts:
        raise HTTPException(404, "Draft not found.")
    draft = drafts[0]
    cleaned = mask(body.final_text)
    event = row(store, bill_id=draft["bill_id"], message_id=draft["id"], action=body.action,
                final_text=cleaned, event_time=stamp(), words_changed=words_changed(draft["draft_text"], body.final_text))
    store.insert_many({"message_events": [event]})
    return {**event, "success_bar_met": body.action == "sent" and event["words_changed"] < 20}


# Vercel serves public/ at the CDN and may omit it from the function bundle.
# Only the local server needs this mount.
if not os.getenv("VERCEL") and (ROOT / "public").is_dir():
    app.mount("/", StaticFiles(directory=ROOT / "public", html=True), name="public")
