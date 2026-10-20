from decimal import Decimal
import pytest
from fastapi.testclient import TestClient
from api.domain import BillInput, analyze, cents, draft_message, mask, words_changed
from api.index import app


def sample(**changes):
    return dict(dict(provider="Broadband", currency="INR", bill_date="2026-10-01",
        total="1378.82", expected="1178.82", promise_source="Plan email", confirmed=True,
        lines=[dict(description="Plan", amount="999", kind="base"),
               dict(description="GST", amount="179.82", kind="tax", tax_rate="18", tax_base="999"),
               dict(description="Add-on", amount="200", kind="extra")]), **changes)


def test_exact_money_and_unexplained():
    r = analyze(BillInput(**sample()))
    assert (r["gap_cents"], r["line_sum_cents"], r["verdict"], r["flagged_positions"]) == (20000, 137882, "unexplained", [2])
    assert cents(Decimal("0.105")) == 11


def test_checks_out_and_explained():
    data = sample(total="1178.82")
    data["lines"].pop()
    assert analyze(BillInput(**data))["verdict"] == "checks_out"
    data = sample()
    data["lines"][2]["accepted"] = True
    r = analyze(BillInput(**data))
    assert r["verdict"] == "explained" and r["unexplained_cents"] == 0


def test_tax_excluded_and_credit():
    data = sample(total="1178.82", expected="999", promise_includes_tax=False, expected_tax_rate="18")
    data["lines"].pop()
    assert analyze(BillInput(**data))["verdict"] == "checks_out"
    data["total"] = "1078.82"
    data["lines"].append(dict(description="Agreed credit", amount="-100", kind="credit", accepted=True))
    assert analyze(BillInput(**data))["verdict"] == "explained"


def test_tax_mismatch_and_late_fee():
    data = sample(total="1379.82", paid_date="2026-10-03", due_date="2026-10-05")
    data["lines"][1]["amount"] = "180.82"
    data["lines"][2].update(kind="late_fee", accepted=True)
    r = analyze(BillInput(**data))
    assert r["flagged_positions"] == [1, 2] and r["verdict"] == "unexplained"


def test_total_mismatch_even_when_promise_matches():
    data = sample(expected="1378.82")
    data["lines"][2]["amount"] = "150"
    r = analyze(BillInput(**data))
    assert r["total_mismatch_cents"] == 5000 and r["verdict"] == "unexplained"


def test_repeats_only_across_months_same_provider_currency():
    previous = [dict(provider=p, currency="INR", bill_date=d, description="Add-on", amount_cents=20000)
                for p,d in [("Broadband","2026-09-01"),("Other","2026-08-01"),("Broadband","2026-10-02")]]
    assert analyze(BillInput(**sample()), previous)["lines"][2]["repeated_on"] == ["2026-09-01"]


def test_masking_and_edit_distance():
    assert "9876543210" not in mask("Phone: 9876543210")
    assert "me@example.com" not in mask("Contact me@example.com")
    assert words_changed("please review this bill", "please check this bill today") == 2
    assert words_changed("", "") == 0
    assert words_changed("hello", "") == 1


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_MODE", "local")
    monkeypatch.setenv("LOCAL_DB", str(tmp_path / "test.db"))
    monkeypatch.delenv("VERCEL", raising=False)
    import api.store
    monkeypatch.setattr(api.store, "ROOT", tmp_path)
    with TestClient(app) as c:
        c.get("/api/bills")
        yield c


def test_full_flow_and_owner_isolation(client):
    created = client.post("/api/bills", json=sample())
    assert created.status_code == 200, created.text
    bid = created.json()["id"]
    assert len(client.get("/api/bills").json()) == 1
    assert client.get(f"/api/bills/{bid}/snapshot").status_code == 200
    response = client.post(f"/api/bills/{bid}/draft", json={"positions":[2], "tone":"firm"})
    assert response.status_code == 200
    draft = response.json()
    assert "INR 200.00" in draft["draft_text"]
    event = client.post(f'/api/messages/{draft["id"]}/events', json={"action":"sent","final_text":draft["draft_text"]}).json()
    assert event["words_changed"] == 0 and event["success_bar_met"]
    with TestClient(app) as stranger:
        assert stranger.get("/api/bills").json() == []
        assert stranger.get(f"/api/bills/{bid}").status_code == 404
        assert stranger.delete(f"/api/bills/{bid}").status_code == 404
        assert stranger.post(f'/api/messages/{draft["id"]}/events', json={"action":"sent","final_text":"hi"}).status_code == 404
    assert client.delete(f"/api/bills/{bid}").status_code == 200
    assert client.get("/api/bills").json() == []


def test_validation_and_csrf(client):
    assert client.post("/api/bills", json=sample(confirmed=False)).status_code == 422
    assert client.post("/api/bills", json=sample(expected="-1")).status_code == 422
    assert client.post("/api/bills", json=sample(lines=[])).status_code == 422
    assert client.post("/api/bills", json=sample(), headers={"Origin":"https://attacker.example"}).status_code == 403
    assert client.post("/api/extract", files={"file":("x.png",b"bad","image/png")}, data={"consent":"false"}).status_code == 400


def test_invalid_draft_line(client):
    bid = client.post("/api/bills", json=sample()).json()["id"]
    assert client.post(f"/api/bills/{bid}/draft", json={"positions":[999]}).status_code == 422


def test_rephrase_preserves_money(monkeypatch):
    from api import ai
    monkeypatch.setattr(ai, "completion", lambda _: {"opening":"review", "closing":"clarify"})
    draft = draft_message(sample(), analyze(BillInput(**sample())), [2])
    revised = ai.rephrase(draft, "polite")
    assert all(v in revised for v in ["INR 1378.82", "INR 1178.82", "INR 200.00"])


def test_rephrase_rejects_ai_numbers(monkeypatch):
    from api import ai
    from fastapi import HTTPException
    monkeypatch.setattr(ai, "completion", lambda _: {"opening":"You owe me 500.", "closing":"Thanks."})
    with pytest.raises(HTTPException):
        ai.rephrase("Hello.\n\nINR 100.00\n\nThanks.", "firm")
