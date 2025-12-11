from fastapi.testclient import TestClient

from testik.api import app, reset_state


def get_client() -> TestClient:
    reset_state()
    return TestClient(app)


def test_auth_and_me_flow():
    client = get_client()

    auth_resp = client.post(
        "/auth/telegram",
        json={"telegram_id": 12345, "username": "tester"},
    )
    assert auth_resp.status_code == 200
    auth_data = auth_resp.json()
    user_id = auth_data["user"]["id"]

    me_resp = client.get("/me", params={"user_id": user_id})
    assert me_resp.status_code == 200
    me_data = me_resp.json()

    assert me_data["user"]["telegram_id"] == 12345
    assert me_data["skills"]["memory_level"] == 1
    assert me_data["skills"]["reaction_level"] == 1


def test_game_session_increases_xp():
    client = get_client()

    auth_resp = client.post(
        "/auth/telegram",
        json={"telegram_id": 555, "username": "player"},
    )
    user_id = auth_resp.json()["user"]["id"]

    start_resp = client.post(
        "/game/session/start",
        json={"user_id": user_id, "game_type": "memory_pairs", "difficulty": "easy"},
    )
    assert start_resp.status_code == 200
    session_id = start_resp.json()["session_id"]

    finish_resp = client.post(
        "/game/session/finish",
        json={
            "session_id": session_id,
            "result": {
                "moves_count": 20,
                "mistakes": 2,
                "time_ms": 50_000,
            },
        },
    )
    assert finish_resp.status_code == 200
    finish_data = finish_resp.json()

    gained = finish_data["gained_xp"]
    assert gained["memory_xp"] > 0
    assert gained["memory_xp"] > gained["reaction_xp"]

    # Check that /me reflects updated XP
    me_resp = client.get("/me", params={"user_id": user_id})
    skills = me_resp.json()["skills"]
    assert skills["memory_xp"] >= gained["memory_xp"] - 1

