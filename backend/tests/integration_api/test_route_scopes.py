import pytest

from app.adapters.integration_api import api_routes, build_app, route_scopes
from app.infra.config import Settings
from app.modules.integration.policy import SCOPES


def test_every_route_declares_exactly_one_scope(settings: Settings) -> None:
    missing = []
    for route in api_routes():
        declared = route_scopes(route)
        if len(declared) != 1:
            missing.append(f"{sorted(route.methods)} {route.path}: {len(declared)}")
    assert missing == []


def test_every_policy_scope_is_used(settings: Settings) -> None:
    used = {scope for route in api_routes() for rs in route_scopes(route) for scope in rs.scopes}
    assert used == set(SCOPES)


def test_mutations_require_idempotency_key(settings: Settings) -> None:
    schema = build_app().openapi()
    lacking = []
    for path, item in schema["paths"].items():
        for method, operation in item.items():
            if method not in {"post", "patch", "put", "delete"}:
                continue
            headers = {p["name"] for p in operation.get("parameters", []) if p["in"] == "header"}
            if "Idempotency-Key" not in headers:
                lacking.append(f"{method.upper()} {path}")
    assert lacking == []


def test_openapi_uses_bearer_scheme_and_server_prefix(settings: Settings) -> None:
    schema = build_app().openapi()
    assert schema["servers"][0]["url"] == "/api/v1"
    assert schema["components"]["securitySchemes"]["bearer"]["scheme"] == "bearer"
    for item in schema["paths"].values():
        for operation in item.values():
            names = {p["name"].lower() for p in operation.get("parameters", [])}
            assert "authorization" not in names
            assert operation["security"] == [{"bearer": []}]
            assert "x-required-scopes" in operation


def test_event_envelope_data_is_documented(settings: Settings) -> None:
    envelope = build_app().openapi()["components"]["schemas"]["EventEnvelopeView"]
    assert envelope["properties"]["data"]["type"] == "object"
    assert envelope["properties"]["data"]["description"]
    assert "request.assigned" in envelope["properties"]["type"]["enum"]


@pytest.mark.parametrize("scope", ["nonsense:read"])
def test_unknown_scope_cannot_be_declared(scope: str) -> None:
    from app.adapters.integration_api.deps import RequireScope

    with pytest.raises(ValueError):
        RequireScope(scope)
