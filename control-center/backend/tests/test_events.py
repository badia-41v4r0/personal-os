import pytest
from starlette.websockets import WebSocketDisconnect

from app import events
from tests.conftest import ORIGIN


def test_eventos_rest_y_reanudacion(client, auth):
    a = events.publish("prueba.uno", {"n": 1})
    b = events.publish("prueba.dos", {"n": 2})
    got = client.get(f"/api/v1/events?after={a['id']}").json()
    assert [e["id"] for e in got] == [b["id"]]


def test_ws_rechaza_origen_ajeno(client, auth):
    cookie = f"cc_session={client.cookies.get('cc_session')}"
    with pytest.raises(WebSocketDisconnect) as e:
        with client.websocket_connect("/api/v1/ws", headers={"Origin": "https://malo.example", "Cookie": cookie}) as ws:
            ws.receive_json()
    assert e.value.code == 4401


def test_ws_rechaza_sin_sesion(client):
    client.cookies.clear()
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/v1/ws", headers={"Origin": ORIGIN}) as ws:
            ws.receive_json()


def test_ws_backlog_y_vivo(client, auth):
    first = events.publish("prueba.antes", {})
    cookie = f"cc_session={client.cookies.get('cc_session')}"
    with client.websocket_connect(f"/api/v1/ws?after={first['id'] - 1}",
                                  headers={"Origin": ORIGIN, "Cookie": cookie}) as ws:
        assert ws.receive_json()["type"] == "prueba.antes"
        events.publish("prueba.despues", {"x": 1})
        assert ws.receive_json()["type"] == "prueba.despues"
