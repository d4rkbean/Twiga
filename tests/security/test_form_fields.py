"""FastAPI 0.123.2 and later read an empty optional form field as missing (None).
Twiga's routes tell "" from None (a hidden field left empty means "off", an
absent one "unchanged"): the pinned version must keep the empty string."""

from fastapi import FastAPI, Form
from fastapi.testclient import TestClient


def test_an_empty_optional_form_field_stays_an_empty_string():
    app = FastAPI()

    @app.post("/form")
    def form(value: str | None = Form(None)):
        return {"value": value}

    client = TestClient(app)

    assert client.post("/form", data={"value": ""}).json() == {"value": ""}
    assert client.post("/form", data={}).json() == {"value": None}
