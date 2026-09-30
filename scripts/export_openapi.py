from __future__ import annotations

import copy
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = REPO_ROOT / "openapi"

_BACKEND_DIR = REPO_ROOT / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

os.environ.setdefault("APP_ENV", "local")
os.environ.setdefault("DEMO_LOGIN_ENABLED", "true")

ERROR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["error"],
    "properties": {
        "error": {
            "type": "object",
            "required": ["code", "message", "request_id", "details"],
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Машиночитаемый код ошибки, например NOT_FOUND.",
                },
                "message": {
                    "type": "string",
                    "description": "Сообщение на русском для лога/UI.",
                },
                "request_id": {
                    "type": "string",
                    "description": "Идентификатор запроса — тот же, что в заголовке X-Request-ID.",
                },
                "details": {
                    "type": "object",
                    "description": "Дополнительные поля ошибки, зависят от кода.",
                    "additionalProperties": True,
                },
            },
        }
    },
}


def _with_error_schema(schema: dict[str, Any]) -> dict[str, Any]:
    schema = copy.deepcopy(schema)
    components = schema.setdefault("components", {})
    schemas = components.setdefault("schemas", {})
    schemas["ErrorResponse"] = ERROR_SCHEMA

    error_response = {
        "description": "Ошибка. Формат одинаковый для всех методов.",
        "content": {
            "application/json": {
                "schema": {"$ref": "#/components/schemas/ErrorResponse"}
            }
        },
    }
    for path_item in schema.get("paths", {}).values():
        for method, operation in path_item.items():
            if method not in {"get", "post", "patch", "put", "delete"}:
                continue
            operation.setdefault("responses", {})["default"] = error_response
    return schema


def _filter_paths(schema: dict[str, Any], *, prefix: str) -> dict[str, Any]:
    schema = copy.deepcopy(schema)
    schema["paths"] = {
        path: item
        for path, item in schema.get("paths", {}).items()
        if path.startswith(prefix)
    }
    return schema


def build_app_api_schema() -> dict[str, Any]:
    from app.adapters.app_api import API_PREFIX
    from app.main import create_app

    raw = create_app().openapi()
    filtered = _filter_paths(raw, prefix=API_PREFIX)
    filtered["info"]["title"] = "Сервис ремонта оборудования — пользовательский API"
    return _with_error_schema(filtered)


def build_operator_api_schema() -> dict[str, Any]:
    from app.adapters.http.errors import install_error_handlers
    from app.adapters.operator import build_operator_router
    from fastapi import FastAPI

    app = FastAPI(
        title="Сервис ремонта оборудования — API оператора",
        version="1.0.0",
        openapi_url="/operator-api/v1/openapi.json",
    )
    install_error_handlers(app)
    app.include_router(build_operator_router())
    return _with_error_schema(app.openapi())


def build_integration_api_schema() -> dict[str, Any]:
    from app.adapters.integration_api import build_app

    return _with_error_schema(build_app().openapi())


SERVICE_PROBES: dict[str, dict[str, Any]] = {
    "/healthz": {
        "get": {
            "summary": "Живость процесса API",
            "responses": {"200": {"description": '{"status": "ok"}'}},
        }
    },
    "/readyz": {
        "get": {
            "summary": "Готовность: схема БД соответствует миграциям",
            "responses": {
                "200": {"description": '{"status": "ok"}'},
                "503": {"description": '{"status": "unavailable"}'},
            },
        }
    },
}

_HTTP_METHODS = ("get", "post", "put", "patch", "delete")


def _index_parameter(parameter: dict[str, Any]) -> dict[str, Any]:
    slim = {
        key: parameter[key] for key in ("name", "in", "required") if key in parameter
    }
    if parameter.get("in") == "path":
        slim["schema"] = {"type": "string"}
    return slim


def _index_operation(operation: dict[str, Any], source: str) -> dict[str, Any]:
    slim: dict[str, Any] = {"x-source": source}
    for key in ("operationId", "summary", "tags"):
        if key in operation:
            slim[key] = operation[key]
    if operation.get("parameters"):
        slim["parameters"] = [_index_parameter(p) for p in operation["parameters"]]
    if "requestBody" in operation:
        slim["requestBody"] = {
            "required": bool(operation["requestBody"].get("required")),
            "content": {
                media: {} for media in operation["requestBody"].get("content", {})
            },
        }
    slim["responses"] = {
        code: {"description": response.get("description", "")}
        if code[:1] in "123"
        else {"$ref": "#/components/responses/Error"}
        for code, response in operation.get("responses", {}).items()
    }
    return slim


def build_data_api_index(schemas: dict[str, dict[str, Any]]) -> dict[str, Any]:
    paths: dict[str, dict[str, Any]] = {}
    for filename, prefix in (
        ("app-api.json", ""),
        ("integration-api.json", "/api/v1"),
        ("operator-api.json", ""),
    ):
        for path, item in schemas[filename]["paths"].items():
            paths[prefix + path] = {
                method: _index_operation(operation, filename)
                for method, operation in item.items()
                if method in _HTTP_METHODS
            }
    paths.update(copy.deepcopy(SERVICE_PROBES))
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "Сервис ремонта оборудования — карта путей для DATA-API",
            "version": schemas["app-api.json"]["info"].get("version", "1.0.0"),
            "description": (
                "Пути и методы всех контуров относительно адреса стенда; схемы запросов "
                "и ответов — в файле, указанном в x-source операции."
            ),
        },
        "paths": paths,
        "components": {
            "responses": {
                "Error": {
                    "description": "Ошибка в едином формате ErrorResponse (см. x-source)."
                }
            }
        },
    }


def build_all() -> dict[str, dict[str, Any]]:
    schemas = {
        "app-api.json": build_app_api_schema(),
        "operator-api.json": build_operator_api_schema(),
        "integration-api.json": build_integration_api_schema(),
    }
    schemas["data-api.json"] = build_data_api_index(schemas)
    return schemas


def write_all(output_dir: Path = OUTPUT_DIR) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for filename, schema in build_all().items():
        assert schema.get("openapi", "").startswith("3.1"), (
            f"{filename}: ожидается OpenAPI 3.1, получено {schema.get('openapi')!r}"
        )
        path = output_dir / filename
        path.write_text(
            json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        written.append(path)
    return written


def main() -> None:
    for path in write_all():
        print(f"записано: {path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
