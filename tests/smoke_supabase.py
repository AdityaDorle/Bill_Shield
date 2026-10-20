"""Live synthetic cloud lifecycle test. Creates and removes its own test bill."""
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1] / ".env")
os.environ["STORAGE_MODE"] = "supabase"
from fastapi.testclient import TestClient
from api.index import app

with TestClient(app) as client:
    response = client.get("/api/bills")
    if response.status_code != 200:
        print("Supabase not ready:", response.json().get("detail"))
        sys.exit(1)
    print("Supabase authenticated and schema readable.")
    data = {"provider":"BillShield automated smoke test", "currency":"INR", "bill_date":"2026-10-20",
            "total":"110", "expected":"100", "promise_source":"Synthetic test only", "confirmed":True,
            "lines":[{"description":"Plan","amount":"100","kind":"base"},{"description":"Test add-on","amount":"10","kind":"extra"}]}
    response = client.post("/api/bills", json=data)
    assert response.status_code == 200, response.text
    bid = response.json()["id"]
    try:
        assert response.json()["snapshot_warning"] is None
        draft = client.post(f"/api/bills/{bid}/draft", json={"positions":[1],"tone":"polite"})
        assert draft.status_code == 200, draft.text
        d = draft.json()
        event = client.post(f'/api/messages/{d["id"]}/events',json={"action":"edited","final_text":d["draft_text"]})
        assert event.status_code == 200, event.text
        snapshot = client.get(f"/api/bills/{bid}/snapshot", follow_redirects=False)
        assert snapshot.status_code == 307, snapshot.text
        with TestClient(app) as stranger:
            assert stranger.get(f"/api/bills/{bid}").status_code == 404
        print("Cloud bill, lines, promise, finding, draft, event, private snapshot, and ownership isolation passed.")
    finally:
        response = client.delete(f"/api/bills/{bid}")
        assert response.status_code == 200, response.text
        print("Synthetic test bill and its snapshot deleted.")
