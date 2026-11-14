"""Pruebas de la API con clave y límite: orden, encabezados y log."""

# Debe coincidir con la clave que pone ``conftest.py``.
VALID_KEY = "tester-key-0123456789"
WRONG_KEY = "wrong-key-0123456789"
QUESTION = {"question": "¿Quién es EMP-0004?"}


def test_rejections_carry_the_request_id_and_are_logged_without_any_key(
    make_observed_client, read_log, log_stream
):
    client = make_observed_client({"RATE_LIMIT_PER_MINUTE": "1"})
    client.headers.pop("X-API-Key")
    missing = client.post("/ask", json=QUESTION)
    client.headers["X-API-Key"] = VALID_KEY
    answered = client.post("/ask", json=QUESTION)
    limited = client.post("/ask", json=QUESTION)
    wrong = client.post("/ask", json=QUESTION, headers={"X-API-Key": WRONG_KEY})

    assert [r.status_code for r in (missing, answered, limited, wrong)] == [
        401,
        200,
        429,
        401,
    ]
    for response in (missing, limited, wrong):
        assert response.headers["X-Request-ID"]
    rejected = [line for line in read_log() if line["event"] == "auth_rejected"]
    assert [line["reason"] for line in rejected] == ["missing", "invalid"]
    throttled = [line for line in read_log() if line["event"] == "rate_limited"]
    assert throttled[0]["client"] == "tester"
    assert throttled[0]["retry_after"] == 60
    text = log_stream.getvalue()
    assert VALID_KEY not in text
    assert WRONG_KEY not in text
