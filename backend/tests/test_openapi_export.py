import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "export_openapi.py"
CONTOURS = ["app-api.json", "operator-api.json", "integration-api.json"]
ALL_FILES = [*CONTOURS, "data-api.json"]


def _load_export_module():
    spec = importlib.util.spec_from_file_location("export_openapi", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


export_openapi = _load_export_module()


@pytest.fixture(scope="module")
def schemas() -> dict[str, dict]:
    return export_openapi.build_all()


@pytest.mark.parametrize("filename", ALL_FILES)
def test_schema_is_openapi_31_and_not_empty(schemas: dict[str, dict], filename: str) -> None:
    schema = schemas[filename]
    assert schema["openapi"].startswith("3.1")
    assert schema["paths"], f"{filename}: схема не содержит путей"
    assert schema["info"]["title"]


@pytest.mark.parametrize("filename", CONTOURS)
def test_schema_has_uniform_error_format(schemas: dict[str, dict], filename: str) -> None:
    schema = schemas[filename]
    error_schema = schema["components"]["schemas"]["ErrorResponse"]
    error_props = error_schema["properties"]["error"]["properties"]
    assert set(error_props) == {"code", "message", "request_id", "details"}

    referenced = False
    for path_item in schema["paths"].values():
        for method, operation in path_item.items():
            if method not in {"get", "post", "patch", "put", "delete"}:
                continue
            for response in operation.get("responses", {}).values():
                schema_ref = (
                    response.get("content", {}).get("application/json", {}).get("schema", {})
                )
                if schema_ref.get("$ref", "").endswith("/ErrorResponse"):
                    referenced = True
    assert referenced, f"{filename}: ни одна операция не ссылается на ErrorResponse"


@pytest.mark.parametrize("filename", CONTOURS)
def test_every_mutation_documents_409_and_our_422(schemas: dict[str, dict], filename: str) -> None:
    """Роутеры объявляют стандартные ответы (ТЗ 10.3): 409 у произвольной мутации,
    а 422 — в нашем формате, а не дефолтном `HTTPValidationError` FastAPI."""
    schema = schemas[filename]
    found_409 = False
    for path_item in schema["paths"].values():
        for method, operation in path_item.items():
            if method not in {"post", "patch", "put", "delete"}:
                continue
            responses = operation.get("responses", {})
            if "409" in responses:
                found_409 = True
                ref = responses["409"]["content"]["application/json"]["schema"]["$ref"]
                assert ref.endswith("/ErrorResponse")
            if "422" in responses:
                ref = responses["422"]["content"]["application/json"]["schema"]["$ref"]
                assert ref.endswith("/ErrorResponse"), (
                    f"{filename}: 422 должен описывать ErrorResponse, а не HTTPValidationError"
                )
    assert found_409, f"{filename}: ни одна мутация не описывает 409"
    assert "HTTPValidationError" not in schema.get("components", {}).get("schemas", {})


def test_app_api_paths_are_scoped_to_prefix(schemas: dict[str, dict]) -> None:
    assert all(path.startswith("/app-api/v1") for path in schemas["app-api.json"]["paths"])


def test_operator_api_paths_are_scoped_to_prefix(schemas: dict[str, dict]) -> None:
    assert all(
        path.startswith("/operator-api/v1") for path in schemas["operator-api.json"]["paths"]
    )


def test_integration_api_has_expected_paths(schemas: dict[str, dict]) -> None:
    assert "/requests" in schemas["integration-api.json"]["paths"]
    assert "/webhook-subscriptions" in schemas["integration-api.json"]["paths"]


def test_write_all_produces_files(tmp_path: Path) -> None:
    written = export_openapi.write_all(output_dir=tmp_path)
    names = {p.name for p in written}
    assert names == set(ALL_FILES)
    for path in written:
        assert path.stat().st_size > 0


@pytest.mark.parametrize("filename", ALL_FILES)
def test_committed_schema_matches_code(schemas: dict[str, dict], filename: str) -> None:
    """Закоммиченный `openapi/*.json` — часть поставки (ТЗ 10.1): он обязан совпадать
    с тем, что строится из кода. Расхождение — перегенерировать `scripts/export_openapi.py`."""
    committed = json.loads((REPO_ROOT / "openapi" / filename).read_text(encoding="utf-8"))
    assert committed == schemas[filename], (
        f"openapi/{filename} устарел: выполните `uv run python scripts/export_openapi.py`"
    )


def test_integration_api_declares_servers_and_bearer(schemas: dict[str, dict]) -> None:
    schema = schemas["integration-api.json"]
    assert schema["servers"][0]["url"] == "/api/v1"
    assert schema["components"]["securitySchemes"]["bearer"]["scheme"] == "bearer"
    upload = schema["paths"]["/requests/{request_id}/attachments"]["post"]["responses"]
    assert {"413", "415"} <= set(upload)


def test_data_api_index_covers_every_contour_path(schemas: dict[str, dict]) -> None:
    """Карта путей для DATA-API: все пути трёх контуров с префиксом монтирования,
    служебные пробы, без схем тел — только путь, метод, параметры и коды ответов."""
    index = schemas["data-api.json"]
    paths = index["paths"]
    for filename, prefix in (
        ("app-api.json", ""),
        ("integration-api.json", "/api/v1"),
        ("operator-api.json", ""),
    ):
        for path, item in schemas[filename]["paths"].items():
            assert prefix + path in paths, f"{filename}: {path} нет в карте"
            for method in item:
                operation = paths[prefix + path][method]
                assert operation["x-source"] == filename
                assert set(operation["responses"]) == set(item[method]["responses"])
                assert "content" not in json.dumps(operation["responses"])
    assert paths["/healthz"]["get"]["responses"] == {"200": {"description": '{"status": "ok"}'}}
    assert "get" in paths["/readyz"]
    assert "schemas" not in index.get("components", {})
    assert "/api/v1/me" in paths and "/app-api/v1/me" in paths
