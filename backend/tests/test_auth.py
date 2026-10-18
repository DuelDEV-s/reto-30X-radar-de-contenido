def test_without_pin_api_is_open(client):
    assert client.get("/api/brands").status_code == 200
    assert client.get("/api/auth/status").json() == {"required": False, "authenticated": True}


def test_pin_protects_api(client, monkeypatch):
    monkeypatch.setenv("APP_PIN", "123456")
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/brands").status_code == 401
    assert client.post("/api/auth/login", json={"pin": "000000"}).status_code == 401
    assert client.get("/api/brands", headers={"X-App-Pin": "123456"}).status_code == 200

    assert client.post("/api/auth/login", json={"pin": "123456"}).status_code == 200
    assert client.get("/api/auth/status").json() == {"required": True, "authenticated": True}
    assert client.get("/api/brands").status_code == 200

    client.post("/api/auth/logout")
    assert client.get("/api/brands").status_code == 401

