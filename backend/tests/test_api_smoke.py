import io


def test_ping(client):
    resp = client.get("/api/ping")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["msg"] == "pong"


def test_demo_seed_detect_flow(client):
    resp = client.post("/api/demo/reset")
    assert resp.status_code == 200

    resp = client.post("/api/demo/seed")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["inserted"] == 12

    resp = client.post("/api/detect")
    assert resp.status_code == 200
    body = resp.get_json()
    assert len(body["subscriptions"]) == 3


def test_textract_mock(client):
    data = {"file": (io.BytesIO(b"fake"), "invoice.pdf")}
    resp = client.post("/api/textract", data=data, content_type="multipart/form-data")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["parsed"]["vendor"] == "Adobe Inc."
