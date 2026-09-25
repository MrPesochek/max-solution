from __future__ import annotations

import base64
import binascii
import hmac
import json
import re
from typing import Any
from xml.sax.saxutils import escape

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from emulator import store
from emulator.metadata import ENTITIES, EntityDef
from emulator.odata_query import (
    QueryError,
    apply_orderby,
    parse_filter,
    parse_int,
    parse_select,
)
from emulator.state import EmulatorState

router = APIRouter()

_RESOURCE_RE = re.compile(
    r"^(?P<entity>[^(/]+)"
    r"(?:\(guid'(?P<key>[0-9a-fA-F-]{36})'\))?"
    r"(?:/(?P<op>Post|Unpost)(?:\(\))?)?$"
)
_JSON = "application/json;odata=minimalmetadata;charset=utf-8"


def odata_error(status_code: int, message: str, code: str = "-1") -> JSONResponse:
    return JSONResponse(
        {"odata.error": {"code": code, "message": {"lang": "ru", "value": message}}},
        status_code=status_code,
        media_type=_JSON,
    )


def _state(request: Request) -> EmulatorState:
    result: EmulatorState = request.app.state.emulator
    return result


def _authorized(request: Request) -> bool:
    settings = _state(request).settings
    header = request.headers.get("authorization", "")
    scheme, _, encoded = header.partition(" ")
    if scheme.lower() != "basic" or not encoded:
        return False
    try:
        username, _, password = base64.b64decode(encoded).decode("utf-8").partition(":")
    except (binascii.Error, UnicodeDecodeError):
        return False
    return hmac.compare_digest(
        username.encode(), settings.odata_username.encode()
    ) & hmac.compare_digest(password.encode(), settings.odata_password.encode())


def _metadata_url(request: Request, base: str) -> str:
    return f"{str(request.base_url).rstrip('/')}/{base}/odata/standard.odata/$metadata"


def _with_links(definition: EntityDef, obj: dict[str, Any]) -> dict[str, Any]:
    result = dict(obj)
    if definition.kind == "register":
        return result
    ref = obj.get("Ref_Key")
    for name in definition.fields:
        if name.endswith("_Key"):
            short = name[: -len("_Key")]
            result[f"{short}@navigationLinkUrl"] = f"{definition.name}(guid'{ref}')/{short}"
    return result


def _project(obj: dict[str, Any], select: list[str] | None) -> dict[str, Any]:
    if select is None:
        return obj
    return {name: obj.get(name) for name in select}


async def _read_body(request: Request) -> dict[str, Any] | JSONResponse:
    limit = _state(request).settings.max_body_bytes
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        return odata_error(413, "Превышен допустимый размер запроса")
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            return odata_error(413, "Превышен допустимый размер запроса")
        chunks.append(chunk)
    try:
        body = json.loads(b"".join(chunks) or b"{}")
    except json.JSONDecodeError:
        return odata_error(400, "Ошибка разбора JSON")
    if not isinstance(body, dict):
        return odata_error(400, "Ожидается объект JSON")
    return body


@router.api_route("/{base}/odata/standard.odata/{resource:path}", methods=["GET", "POST", "PATCH"])
async def odata(request: Request, base: str, resource: str) -> Response:
    state = _state(request)
    if base != state.settings.base_name:
        return odata_error(404, "Публикация не найдена")
    if not _authorized(request):
        response = odata_error(401, "Требуется аутентификация")
        response.headers["WWW-Authenticate"] = 'Basic realm="1C:Enterprise"'
        return response
    fmt = request.query_params.get("$format", "json")
    if fmt not in {"json", "application/json"}:
        return odata_error(400, "Эмулятор поддерживает только $format=json")

    resource = resource.strip("/")
    if resource == "":
        sets = [{"name": name, "url": name} for name in ENTITIES]
        return JSONResponse(
            {"odata.metadata": _metadata_url(request, base), "value": sets}, media_type=_JSON
        )
    if resource == "$metadata":
        return Response(_metadata_xml(), media_type="application/xml")

    match = _RESOURCE_RE.match(resource)
    if match is None or match.group("entity") not in ENTITIES:
        return odata_error(404, f"Ресурс не найден: {resource}")
    definition = ENTITIES[match.group("entity")]
    key, op = match.group("key"), match.group("op")
    try:
        if op is not None:
            if request.method != "POST" or key is None:
                return odata_error(405, "Метод не поддерживается")
            store.set_posted(state.conn, definition.name, key, op == "Post")
            return Response(status_code=200)
        if key is not None:
            return await _element(request, base, definition, key)
        return await _collection(request, base, definition)
    except store.StoreError as exc:
        return odata_error(exc.status_code, exc.message)
    except QueryError as exc:
        return odata_error(400, str(exc))


async def _collection(request: Request, base: str, definition: EntityDef) -> Response:
    state = _state(request)
    metadata = f"{_metadata_url(request, base)}#{definition.name}"
    if request.method == "POST":
        body = await _read_body(request)
        if isinstance(body, JSONResponse):
            return body
        created = store.create(state.conn, definition.name, body)
        payload = {"odata.metadata": f"{metadata}/@Element", **_with_links(definition, created)}
        return JSONResponse(payload, status_code=201, media_type=_JSON)
    if request.method != "GET":
        return odata_error(405, "Метод не поддерживается")

    params = request.query_params
    fields = set(definition.all_fields()) | set(definition.tables)
    items = store.list_all(state.conn, definition.name)
    if params.get("$filter"):
        predicate = parse_filter(params["$filter"], fields)
        items = [item for item in items if predicate(item)]
    items = apply_orderby(items, params.get("$orderby"), fields)
    skip = parse_int(params.get("$skip"), "$skip") or 0
    top = parse_int(params.get("$top"), "$top")
    items = items[skip:] if top is None else items[skip : skip + top]
    select = parse_select(params.get("$select"), fields)
    value = [_project(item, select) if select else _with_links(definition, item) for item in items]
    if select:
        metadata += "&$select=" + ",".join(select)
    return JSONResponse({"odata.metadata": metadata, "value": value}, media_type=_JSON)


async def _element(request: Request, base: str, definition: EntityDef, key: str) -> Response:
    state = _state(request)
    metadata = f"{_metadata_url(request, base)}#{definition.name}/@Element"
    if request.method == "PATCH":
        body = await _read_body(request)
        if isinstance(body, JSONResponse):
            return body
        updated = store.update(state.conn, definition.name, key, body)
        return JSONResponse(
            {"odata.metadata": metadata, **_with_links(definition, updated)}, media_type=_JSON
        )
    if request.method != "GET":
        return odata_error(405, "Метод не поддерживается")
    found = store.get(state.conn, definition.name, key)
    if found is None:
        return odata_error(404, "Объект не найден", code="9")
    fields = set(definition.all_fields()) | set(definition.tables)
    select = parse_select(request.query_params.get("$select"), fields)
    payload = _project(found, select) if select else _with_links(definition, found)
    return JSONResponse({"odata.metadata": metadata, **payload}, media_type=_JSON)


def _edm_type(value: Any) -> str:
    if isinstance(value, bool):
        return "Edm.Boolean"
    if isinstance(value, int | float):
        return "Edm.Double"
    if isinstance(value, str) and value.startswith("0001-01-01T"):
        return "Edm.DateTime"
    if isinstance(value, str) and len(value) == 36 and value.count("-") == 4:
        return "Edm.Guid"
    return "Edm.String"


def _metadata_xml() -> str:
    """Сокращённое описание метаданных: только типы и свойства эмулируемых объектов."""
    types: list[str] = []
    sets: list[str] = []
    for definition in ENTITIES.values():
        props = "".join(
            f'<Property Name="{escape(n)}" Type="{_edm_type(v)}" Nullable="true"/>'
            for n, v in definition.all_fields().items()
        )
        for table, columns in definition.tables.items():
            row_type = f"{definition.name}_{table}_RowType"
            row_props = "".join(
                f'<Property Name="{escape(n)}" Type="{_edm_type(v)}" Nullable="true"/>'
                for n, v in columns.items()
            )
            types.append(f'<ComplexType Name="{escape(row_type)}">{row_props}</ComplexType>')
            props += (
                f'<Property Name="{escape(table)}" '
                f'Type="Collection(StandardODATA.{escape(row_type)})" Nullable="true"/>'
            )
        key = "" if definition.kind == "register" else '<Key><PropertyRef Name="Ref_Key"/></Key>'
        types.append(f'<EntityType Name="{escape(definition.name)}">{key}{props}</EntityType>')
        sets.append(
            f'<EntitySet Name="{escape(definition.name)}" '
            f'EntityType="StandardODATA.{escape(definition.name)}"/>'
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<edmx:Edmx xmlns:edmx="http://schemas.microsoft.com/ado/2007/06/edmx" Version="1.0">'
        '<edmx:DataServices m:DataServiceVersion="3.0" '
        'xmlns:m="http://schemas.microsoft.com/ado/2007/08/dataservices/metadata">'
        '<Schema Namespace="StandardODATA" xmlns="http://schemas.microsoft.com/ado/2009/11/edm">'
        + "".join(types)
        + '<EntityContainer Name="EnterpriseV8" m:IsDefaultEntityContainer="true">'
        + "".join(sets)
        + "</EntityContainer></Schema></edmx:DataServices></edmx:Edmx>"
    )
