"""Pruebas de ``app.pii``: detección y reemplazo de datos personales."""

from app.pii import redact

EMAIL = "ana.lopez@example.com"
PHONE = "+52 55 1234 5678"
CURP = "GODE561231HDFRRN09"
RFC = "GODE561231AB1"
CARD = "4111-1111-1111-1111"
NSS = "12345678901"
CARD_WITHOUT_LUHN = "4111 1111 1111 1112"


def test_each_personal_data_type_is_replaced_but_ids_and_bad_cards_are_kept():
    text = (
        f"Correo {EMAIL} y otro@example.com, tel {PHONE}, CURP {CURP}, "
        f"RFC {RFC}, tarjeta {CARD}, NSS {NSS}. "
        f"Pregunto por EMP-0001 con la referencia {CARD_WITHOUT_LUHN}."
    )

    result = redact(text)

    for marker in ("[EMAIL]", "[PHONE]", "[CURP]", "[RFC]", "[CARD]", "[NSS]"):
        assert marker in result.text
    for value in (EMAIL, PHONE, CURP, RFC, CARD, NSS):
        assert value not in result.text
    assert "EMP-0001" in result.text
    assert CARD_WITHOUT_LUHN in result.text
    assert list(result.types) == ["card", "curp", "email", "nss", "phone", "rfc"]
    assert result.count == 7
