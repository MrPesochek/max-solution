#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6", "jsonschema>=4.18"]
# ///

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import yaml  # type: ignore[import-untyped]
    from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover — подсказка для запуска без uv
    sys.exit("Нужны PyYAML и jsonschema: uv run scripts/data-api-check.py")

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PASSPORT = ROOT / "DATA-API.yaml"
EXTENSION_SUFFIX = ".extended.yaml"
VARIABLE_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_.-]*)\}")
PATH_PARAM_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_.-]*)\}")
JSON_INDEX_RE = re.compile(r"\[(\d+)\]")
HTTP_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")
SECRET_NAME_RE = re.compile(r"token|key|secret|password", re.IGNORECASE)


@dataclass
class Response:
    status: int
    headers: dict[str, str]
    body: bytes

    def json(self) -> Any:
        return json.loads(self.body.decode() or "null")


Transport = Callable[[str, str, dict[str, str], bytes | None], Response]


def urllib_transport(timeout: float = 20.0) -> Transport:
    def send(
        method: str, url: str, headers: dict[str, str], body: bytes | None
    ) -> Response:
        request = urllib.request.Request(url, data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as reply:
                return Response(reply.status, dict(reply.headers.items()), reply.read())
        except urllib.error.HTTPError as exc:
            return Response(exc.code, dict(exc.headers.items()), exc.read())

    return send


class MissingValue(Exception):
    """Шаблон ссылается на переменную, которой нет (упал шаг, который её извлекает)."""


class PassportError(Exception):
    pass


@dataclass
class Passport:
    doc: dict[str, Any]
    ext: dict[str, Any]
    root: Path

    @property
    def checks(self) -> list[dict[str, Any]]:
        return list(self.doc.get("checks") or [])

    @property
    def cleanup(self) -> list[dict[str, Any]]:
        return list(self.doc.get("cleanup") or [])

    @property
    def roles(self) -> dict[str, dict[str, Any]]:
        return dict(self.ext.get("roles") or {})

    def extension_of(self, check_id: str) -> dict[str, Any]:
        return dict((self.ext.get("checks") or {}).get(check_id) or {})

    def suite_ids(self, suite: str) -> list[str] | None:
        """Идентификаторы проверок набора; None — все проверки по порядку."""
        suites = self.ext.get("suites") or {}
        if not suites:
            if suite != "full":
                raise PassportError(
                    f"нет набора {suite!r}: расширение не описывает suites"
                )
            return None
        if suite not in suites:
            raise PassportError(f"нет набора {suite!r} в suites")
        selected = (suites[suite] or {}).get("checks", "all")
        return None if selected == "all" else list(selected)

    def secret_names(self) -> set[str]:
        return set(self.ext.get("secrets") or [])


def _load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise PassportError(f"{path}: ожидался YAML-объект")
    return data


def load_passport(path: Path) -> Passport:
    """Паспорт с расширением. Принимает и путь к DATA-API.yaml (расширение ищется рядом
    по имени `<имя>.extended.yaml`), и путь к расширению (паспорт — по полю `extends`)."""
    path = path.resolve()
    data = _load_yaml(path)
    if "extends" in data:
        base_path = (path.parent / str(data["extends"])).resolve()
        return Passport(_load_yaml(base_path), data, base_path.parent)
    extension_path = path.with_name(path.name.removesuffix(".yaml") + EXTENSION_SUFFIX)
    ext = _load_yaml(extension_path) if extension_path.exists() else {}
    return Passport(data, ext, path.parent)


def json_path(data: Any, expression: str) -> Any:
    """Значение по JSONPath-подмножеству эталона: `$.a.b[0].c`; допускается и `a.b.0.c`.
    KeyError, если поля нет."""
    tokens = _path_tokens(expression)
    current = data
    for token in tokens:
        if isinstance(current, list) and token.isdigit():
            index = int(token)
            if index >= len(current):
                raise KeyError(expression)
            current = current[index]
        elif isinstance(current, Mapping) and token in current:
            current = current[token]
        else:
            raise KeyError(expression)
    return current


def _path_tokens(expression: str) -> list[str]:
    """`$.a.b[0].c` → ["a", "b", "0", "c"]; индекс через точку (`$.items.0.id`) тоже принят."""
    flat = JSON_INDEX_RE.sub(r".\1", expression.removeprefix("$"))
    return [token for token in flat.split(".") if token != ""]


def link_token(value: str) -> str:
    """Токен из ссылки входа `.../#/auth/link?t=<токен>` или сам токен."""
    if "t=" not in value:
        return value.strip()
    fragment = value.split("#", 1)[-1]
    query = fragment.split("?", 1)[-1]
    return urllib.parse.parse_qs(query).get("t", [""])[0]


class Context:
    def __init__(self) -> None:
        self.vars: dict[str, Any] = {}

    def resolve(self, name: str) -> Any:
        if name in self.vars:
            return self.vars[name]
        raise MissingValue(name)

    def render(self, value: Any) -> Any:
        if isinstance(value, str):
            whole = VARIABLE_RE.fullmatch(value)
            if whole:
                return self.resolve(whole.group(1))
            return VARIABLE_RE.sub(lambda m: str(self.resolve(m.group(1))), value)
        if isinstance(value, list):
            return [self.render(item) for item in value]
        if isinstance(value, Mapping):
            return {key: self.render(item) for key, item in value.items()}
        return value


@dataclass
class Result:
    check_id: str
    title: str
    role: str
    request: str
    outcome: str
    status: int | None = None
    problems: list[str] = field(default_factory=list)
    seconds: float = 0.0


def evaluate(
    expected: Mapping[str, Any],
    extension: Mapping[str, Any],
    response: Response,
    ctx: Context,
) -> list[str]:
    problems: list[str] = []
    allowed = list(expected.get("statusCodes") or [])
    if allowed and response.status not in allowed:
        problems.append(f"статус {response.status}, ожидался {allowed}")
        code = _error_code(_safe_json(response))
        if code:
            problems.append(f"error.code = {code}")
        return problems
    headers = {key.lower(): value for key, value in response.headers.items()}
    content_type = expected.get("contentType")
    if content_type and not headers.get("content-type", "").startswith(content_type):
        problems.append(
            f"Content-Type {headers.get('content-type')!r}, ожидался {content_type}"
        )
    for name in extension.get("responseHeaders") or []:
        if name.lower() not in headers:
            problems.append(f"нет заголовка {name}")
    equals = extension.get("equals") or {}
    needs_body = expected.get("requiredFields") or expected.get("bodySchema") or equals
    if not needs_body:
        return problems
    try:
        body = response.json()
    except ValueError:
        problems.append("тело ответа — не JSON")
        return problems
    for path in expected.get("requiredFields") or []:
        try:
            json_path(body, path)
        except KeyError:
            problems.append(f"нет поля {path}")
    schema = expected.get("bodySchema")
    if schema:
        errors = sorted(
            Draft202012Validator(schema).iter_errors(body), key=lambda e: e.path
        )
        for error in errors[:3]:
            where = "/".join(str(p) for p in error.absolute_path) or "$"
            problems.append(f"bodySchema: {where}: {error.message}")
    for path, template in equals.items():
        want = ctx.render(template)
        try:
            got = json_path(body, path)
        except KeyError:
            problems.append(f"нет поля {path}")
            continue
        if got != want and str(got) != str(want):
            problems.append(f"{path} = {got!r}, ожидалось {want!r}")
    return problems


def _safe_json(response: Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return None


def _error_code(body: Any) -> str | None:
    try:
        return str(json_path(body, "$.error.code"))
    except (KeyError, TypeError):
        return None


class Runner:
    def __init__(
        self,
        passport: Passport,
        *,
        base_url: str,
        access: str = "demo",
        suite: str = "full",
        transport: Transport,
        env: Mapping[str, str],
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.passport = passport
        self.base_url = base_url.rstrip("/")
        self.access = access
        self.suite = suite
        self.transport = transport
        self.env = env
        self.sleep = sleep
        self.ctx = Context()
        self.results: list[Result] = []
        self.outcomes: dict[str, str] = {}
        self.selected_ids: set[str] = set()
        access_modes = passport.ext.get("access") or {}
        if access not in ("demo", *access_modes):
            raise PassportError(f"способ доступа {access!r} не описан в access")
        self.mode: dict[str, Any] = dict(access_modes.get(access) or {})
        self.logins: dict[str, dict[str, Any]] = {
            role["login"]: {"id": role_id, **role}
            for role_id, role in passport.roles.items()
            if role.get("access") == "session" and role.get("login")
        }
        key_mode = access_modes.get("integration_key") or {}
        preset = (
            env.get(str(key_mode.get("env", "")), "") if key_mode.get("env") else ""
        )
        if preset:
            self.ctx.vars[str(key_mode.get("variable", "integrationApiKey"))] = preset

    def send(self, spec: Mapping[str, Any]) -> tuple[str, Response]:
        method = str(spec["method"]).upper()
        request_spec = spec.get("request") or {}
        path = str(spec["path"])
        for name, value in self.ctx.render(request_spec.get("path") or {}).items():
            path = path.replace(
                "{" + name + "}", urllib.parse.quote(str(value), safe="")
            )
        url = f"{self.base_url}{path}"
        query = self.ctx.render(request_spec.get("query") or {})
        if query:
            url += "?" + urllib.parse.urlencode(query, doseq=True)
        headers = {
            str(k): str(v)
            for k, v in (
                (self.passport.doc.get("api") or {}).get("defaultHeaders") or {}
            ).items()
        }
        headers.update(
            {
                str(k): str(v)
                for k, v in self.ctx.render(request_spec.get("headers") or {}).items()
            }
        )
        headers.setdefault("Accept", "application/json")
        data: bytes | None = None
        if "body" in request_spec:
            data = json.dumps(
                self.ctx.render(request_spec["body"]), ensure_ascii=False
            ).encode()
            headers.setdefault("Content-Type", "application/json")
        return f"{method} {path}", self.transport(method, url, headers, data)

    def checks(self) -> list[dict[str, Any]]:
        selected = self.passport.suite_ids(self.suite)
        checks = self.passport.checks
        if selected is None:
            return checks
        by_id = {check["id"]: check for check in checks}
        missing = [check_id for check_id in selected if check_id not in by_id]
        if missing:
            raise PassportError(
                f"набор {self.suite!r} ссылается на неизвестные проверки: {missing}"
            )
        return [by_id[check_id] for check_id in selected]

    def _login_spec(
        self, check: Mapping[str, Any]
    ) -> tuple[dict[str, Any], str | None]:
        """Шаг входа с учётом способа доступа. Возвращает спецификацию и причину SKIP."""
        role = self.logins.get(str(check["id"]))
        if role is None or self.access == "demo" or "request" not in self.mode:
            return dict(check), None
        env_name = str(self.mode.get("token_env", "LOGIN_LINK_{USER_KEY}")).replace(
            "{USER_KEY}", str(role["user_key"]).upper()
        )
        raw = self.env.get(env_name, "")
        if not raw:
            return dict(
                check
            ), f"нет ссылки входа в {env_name} (см. access.{self.access}.issue)"
        self.ctx.vars["loginLinkToken"] = link_token(raw)
        replaced = dict(check)
        replaced.update(
            {k: v for k, v in self.mode["request"].items() if k in ("method", "path")}
        )
        replaced["request"] = {
            k: v
            for k, v in self.mode["request"].items()
            if k in ("headers", "query", "body")
        }
        return replaced, None

    def run_check(
        self, check: Mapping[str, Any], *, label: str | None = None
    ) -> Result:
        check_id = str(check["id"])
        result = Result(
            label or check_id, check.get("name", ""), check.get("role", ""), "", "FAIL"
        )
        started = time.monotonic()
        failed_deps = [
            d
            for d in check.get("dependsOn") or []
            if d in self.selected_ids and self.outcomes.get(d) != "PASS"
        ]
        if failed_deps:
            result.outcome = "SKIP"
            result.problems.append(f"не прошла зависимость: {', '.join(failed_deps)}")
            return result
        spec, skip_reason = self._login_spec(check)
        if skip_reason:
            result.outcome = "SKIP"
            result.problems.append(skip_reason)
            return result
        try:
            request, response = self.send(spec)
        except MissingValue as exc:
            result.outcome = "SKIP"
            result.problems.append(
                f"нет значения ${{{exc}}}: упал шаг, который его извлекает"
            )
            return result
        except OSError as exc:
            result.problems.append(f"стенд недоступен: {exc}")
            return result
        result.request, result.status = request, response.status
        extension = self.passport.extension_of(check_id)
        result.problems = evaluate(
            check.get("expected") or {}, extension, response, self.ctx
        )
        hint = (self.mode.get("hints") or {}).get(response.status)
        if result.problems and hint and check_id in self.logins:
            result.problems.append(str(hint))
        if not result.problems:
            body = response.json() if check.get("extract") else None
            for name, expression in (check.get("extract") or {}).items():
                self.ctx.vars[name] = json_path(body, expression)
            result.outcome = "PASS"
        result.seconds = time.monotonic() - started
        return result

    def run(self) -> list[Result]:
        checks = self.checks()
        self.selected_ids = {check["id"] for check in checks}
        index = {check["id"]: check for check in self.passport.checks}
        for check in checks:
            retry = self.passport.extension_of(check["id"]).get("retry") or {}
            attempts = int(retry.get("attempts", 1))
            result = self.run_check(check)
            for _ in range(attempts - 1):
                if result.status not in retry.get("on_status", []):
                    break
                self.sleep(float(retry.get("delay_seconds", 1)))
                source = index.get(retry.get("from", ""))
                if source is not None and self.run_check(source).outcome != "PASS":
                    break
                result = self.run_check(check)
            self.results.append(result)
            self.outcomes[check["id"]] = result.outcome
        self._cleanup()
        return self.results

    def _cleanup(self) -> None:
        """Шаги cleanup — только те, для которых все переменные уже получены: иначе
        удалять нечего (шаг, создающий объект, не выполнялся)."""
        for step in self.passport.cleanup:
            needed = set()
            for text in _strings(step.get("request") or {}):
                needed.update(VARIABLE_RE.findall(text))
            if needed - set(self.ctx.vars):
                continue
            self.results.append(self.run_check(step, label=f"cleanup:{step['id']}"))


def _strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


class OpenApiIndex:
    def __init__(self, root: Path, sources: list[Mapping[str, str]]) -> None:
        self.ops: list[tuple[str, str, dict[str, Any], dict[str, Any]]] = []
        for source in sources:
            doc = json.loads((root / source["file"]).read_text(encoding="utf-8"))
            prefix = source.get("prefix", "")
            for path, operations in doc.get("paths", {}).items():
                for method, operation in operations.items():
                    if method.upper() in HTTP_METHODS:
                        self.ops.append((method.upper(), prefix + path, operation, doc))

    def find(
        self, method: str, path: str
    ) -> tuple[str, dict[str, Any], dict[str, Any]] | None:
        for op_method, template, operation, doc in self.ops:
            if op_method == method and template == path:
                return template, operation, doc
        return None


def _deref(schema: Mapping[str, Any], doc: Mapping[str, Any]) -> Mapping[str, Any]:
    while "$ref" in schema:
        name = schema["$ref"].rsplit("/", 1)[-1]
        schema = doc["components"]["schemas"][name]
    return schema


def _options(
    schema: Mapping[str, Any], doc: Mapping[str, Any]
) -> list[Mapping[str, Any]]:
    schema = _deref(schema, doc)
    variants = schema.get("anyOf") or schema.get("oneOf") or schema.get("allOf")
    if variants:
        return [
            opt
            for v in variants
            for opt in _options(v, doc)
            if opt.get("type") != "null"
        ]
    return [schema]


def schema_has_path(
    schema: Mapping[str, Any], tokens: list[str], doc: Mapping[str, Any]
) -> bool:
    """Путь (`a`, `0`, `b`) описан в схеме ответа (через $ref, anyOf, items)."""
    if not tokens:
        return True
    head, rest = tokens[0], tokens[1:]
    for option in _options(schema, doc):
        if head.isdigit() and option.get("type") == "array":
            child = option.get("items", {})
        elif head in option.get("properties", {}):
            child = option["properties"][head]
        elif option.get("type") == "object" and "properties" not in option:
            return True
        else:
            continue
        if schema_has_path(child, rest, doc):
            return True
    return False


def _response_schema(
    operation: Mapping[str, Any], status: int
) -> Mapping[str, Any] | None:
    responses = operation.get("responses", {})
    response = responses.get(str(status)) or responses.get("default")
    if response is None:
        return None
    schema: Mapping[str, Any] = (
        response.get("content", {}).get("application/json", {}).get("schema", {})
    )
    return schema


def _schema_field_paths(
    schema: Mapping[str, Any], prefix: list[str]
) -> Iterable[list[str]]:
    """Пути полей, о которых говорит bodySchema (properties/required/prefixItems/items)."""
    for name in set(schema.get("required") or []) | set(schema.get("properties") or {}):
        yield [*prefix, name]
        child = (schema.get("properties") or {}).get(name)
        if isinstance(child, Mapping):
            yield from _schema_field_paths(child, [*prefix, name])
    for position, child in enumerate(schema.get("prefixItems") or []):
        yield from _schema_field_paths(child, [*prefix, str(position)])
    items = schema.get("items")
    if isinstance(items, Mapping):
        yield from _schema_field_paths(items, [*prefix, "0"])


def validate_request(
    spec: Mapping[str, Any],
    extension: Mapping[str, Any],
    index: OpenApiIndex,
    *,
    label: str,
) -> list[str]:
    method = str(spec["method"]).upper()
    found = index.find(method, str(spec["path"]))
    if found is None:
        return [f"{label}: {method} {spec['path']} нет в OpenAPI"]
    template, operation, doc = found
    request_spec = spec.get("request") or {}
    problems: list[str] = []
    params = {(p["in"], p["name"].lower()): p for p in operation.get("parameters", [])}
    secured = bool(operation.get("security") or doc.get("security"))
    for name in request_spec.get("headers") or {}:
        lowered = name.lower()
        if lowered in ("content-type", "accept") or (
            lowered == "authorization" and secured
        ):
            continue
        if ("header", lowered) not in params:
            problems.append(
                f"{label}: заголовок {name} не описан у {method} {template}"
            )
    for name in request_spec.get("query") or {}:
        if ("query", name.lower()) not in params:
            problems.append(
                f"{label}: query-параметр {name} не описан у {method} {template}"
            )
    supplied_headers = {h.lower() for h in (request_spec.get("headers") or {})}
    for (place, name), param in params.items():
        if place == "header" and param.get("required") and name not in supplied_headers:
            problems.append(
                f"{label}: обязательный заголовок {param['name']} не передан"
            )
    request_body = operation.get("requestBody")
    if "body" in request_spec:
        if request_body is None:
            problems.append(f"{label}: у {method} {template} нет тела запроса")
        else:
            schema = request_body["content"]["application/json"]["schema"]
            body_schema = _deref(schema, doc)
            properties = body_schema.get("properties", {})
            for key in request_spec["body"]:
                if key not in properties:
                    problems.append(f"{label}: поле тела {key} не описано в схеме")
            for key in body_schema.get("required", []):
                if key not in request_spec["body"]:
                    problems.append(
                        f"{label}: обязательное поле тела {key} не передано"
                    )
    elif request_body is not None and request_body.get("required"):
        problems.append(f"{label}: {method} {template} требует тело запроса")
    expected = spec.get("expected") or {}
    statuses = list(expected.get("statusCodes") or [])
    responses = operation.get("responses", {})
    for status in statuses:
        if str(status) not in responses and "default" not in responses:
            problems.append(f"{label}: код {status} не описан у {method} {template}")
    for status in statuses[:1]:
        schema = _response_schema(operation, status)
        if not schema:
            continue
        paths = [_path_tokens(p) for p in expected.get("requiredFields") or []]
        paths += [_path_tokens(p) for p in (spec.get("extract") or {}).values()]
        paths += [_path_tokens(p) for p in (extension.get("equals") or {})]
        paths += list(_schema_field_paths(expected.get("bodySchema") or {}, []))
        for tokens in paths:
            if not schema_has_path(schema, tokens, doc):
                problems.append(
                    f"{label}: поле ответа {'.'.join(tokens)} не описано (код {status})"
                )
    return problems


def validate_passport(passport: Passport) -> list[str]:
    """Согласованность паспорта, расширения и схем OpenAPI. Структуру по JSON Schema
    организаторов проверяет их валидатор; здесь — переменные, роли, наборы и поля."""
    doc, ext = passport.doc, passport.ext
    problems: list[str] = []
    if doc.get("schemaVersion") != "1.0":
        problems.append('schemaVersion должен быть "1.0"')
    checks = passport.checks
    if not checks:
        problems.append("нет проверок (checks)")
        return problems
    ids = [str(check.get("id")) for check in checks]
    for duplicate in sorted({x for x in ids if ids.count(x) > 1}):
        problems.append(f"повтор id проверки {duplicate}")
    roles = passport.roles
    logins = {
        role.get("login") for role in roles.values() if role.get("access") == "session"
    }
    for login in logins:
        if login not in ids:
            problems.append(f"roles: шаг входа {login} не найден среди проверок")
    for suite_name, suite in (ext.get("suites") or {}).items():
        selected = (suite or {}).get("checks", "all")
        if selected != "all":
            for check_id in selected:
                if check_id not in ids:
                    problems.append(
                        f"suites.{suite_name}: неизвестная проверка {check_id}"
                    )
    for check_id, extension in (ext.get("checks") or {}).items():
        if check_id not in ids:
            problems.append(
                f"checks.{check_id} в расширении: такой проверки нет в паспорте"
            )
        source = (extension or {}).get("retry", {}).get("from")
        if source and source not in ids:
            problems.append(
                f"checks.{check_id}: retry.from ссылается на неизвестную {source}"
            )
    key_variable = str(
        ((ext.get("access") or {}).get("integration_key") or {}).get("variable", "")
    )
    produced: set[str] = {"loginLinkToken"} | (
        {key_variable} if key_variable else set()
    )
    index = OpenApiIndex(passport.root, ext.get("openapi") or [])
    for check in checks:
        check_id = str(check.get("id"))
        label = f"проверка {check_id}"
        extension = passport.extension_of(check_id)
        if roles and check.get("role") not in roles:
            problems.append(
                f"{label}: роль {check.get('role')!r} не описана в roles расширения"
            )
        for dependency in check.get("dependsOn") or []:
            if dependency not in ids[: ids.index(check_id)]:
                problems.append(
                    f"{label}: dependsOn {dependency} не выполняется раньше"
                )
        placeholders = set(PATH_PARAM_RE.findall(str(check.get("path", ""))))
        supplied = set(((check.get("request") or {}).get("path") or {}).keys())
        if placeholders != supplied:
            problems.append(
                f"{label}: параметры пути {sorted(placeholders)} ≠ {sorted(supplied)}"
            )
        used: set[str] = set()
        for text in _strings(check.get("request") or {}):
            used.update(VARIABLE_RE.findall(text))
        for text in _strings(extension.get("equals") or {}):
            used.update(VARIABLE_RE.findall(text))
        for name in sorted(used - produced):
            problems.append(
                f"{label}: переменная ${{{name}}} не извлекается предыдущими шагами"
            )
        for name, expression in (check.get("extract") or {}).items():
            if not str(expression).startswith("$"):
                problems.append(
                    f"{label}: extract {name} должен быть JSONPath и начинаться с $"
                )
            produced.add(name)
        if not (check.get("expected") or {}).get("statusCodes"):
            problems.append(f"{label}: нет ожидаемых кодов ответа")
        if extension.get("openapi") != "none" and index.ops:
            problems += validate_request(check, extension, index, label=label)
    for step in passport.cleanup:
        label = f"cleanup {step.get('id')}"
        used = set()
        for text in _strings(step.get("request") or {}):
            used.update(VARIABLE_RE.findall(text))
        for name in sorted(used - produced):
            problems.append(
                f"{label}: переменная ${{{name}}} не извлекается проверками"
            )
        if index.ops:
            problems += validate_request(step, {}, index, label=label)
    return problems


def mask(text: str, secrets: list[str]) -> str:
    for secret in secrets:
        if secret and len(secret) >= 8:
            text = text.replace(secret, "***")
    return text


def secrets_of(runner: Runner) -> list[str]:
    names = runner.passport.secret_names()
    return [
        str(value)
        for name, value in runner.ctx.vars.items()
        if name in names or SECRET_NAME_RE.search(name)
    ]


def print_report(runner: Runner, out: Any = sys.stdout) -> None:
    secrets = secrets_of(runner)
    width = max((len(r.check_id) for r in runner.results), default=10)
    print(
        f"DATA-API: {runner.base_url} | доступ {runner.access} | набор {runner.suite}",
        file=out,
    )
    for result in runner.results:
        status = "---" if result.status is None else str(result.status)
        line = f"{result.outcome:4}  {result.check_id:<{width}}  {status}  {result.request}"
        print(mask(line, secrets), file=out)
        for problem in result.problems:
            print(mask(f"      - {problem}", secrets), file=out)
    passed = sum(r.outcome == "PASS" for r in runner.results)
    failed = sum(r.outcome == "FAIL" for r in runner.results)
    skipped = sum(r.outcome == "SKIP" for r in runner.results)
    print(f"Итог: {passed} pass, {failed} fail, {skipped} skip", file=out)


def json_report(runner: Runner) -> dict[str, Any]:
    secrets = secrets_of(runner)
    return {
        "base_url": runner.base_url,
        "access": runner.access,
        "suite": runner.suite,
        "results": [
            {
                "id": r.check_id,
                "title": r.title,
                "role": r.role,
                "request": r.request,
                "outcome": r.outcome,
                "status": r.status,
                "problems": [mask(p, secrets) for p in r.problems],
                "seconds": round(r.seconds, 3),
            }
            for r in runner.results
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Проверка API по паспорту DATA-API.yaml"
    )
    parser.add_argument("--passport", type=Path, default=DEFAULT_PASSPORT)
    parser.add_argument("--base-url", default=os.environ.get("BASE_URL"))
    parser.add_argument("--access", choices=("demo", "link"), default="demo")
    parser.add_argument("--suite", default="full")
    parser.add_argument("--json-report", type=Path, help="Записать отчёт в JSON")
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument(
        "--validate-only", action="store_true", help="Только сверка с OpenAPI"
    )
    args = parser.parse_args(argv)

    try:
        passport = load_passport(args.passport)
        problems = validate_passport(passport)
    except (OSError, PassportError, yaml.YAMLError) as exc:
        print(f"Паспорт не прочитан: {exc}", file=sys.stderr)
        return 2
    if problems:
        print("Паспорт расходится с OpenAPI или расширением:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 2
    if args.validate_only:
        print(f"Паспорт согласован с OpenAPI: {len(passport.checks)} проверок.")
        return 0
    if not args.base_url or "<" in args.base_url:
        print("Укажите адрес стенда: --base-url или BASE_URL", file=sys.stderr)
        return 2

    try:
        runner = Runner(
            passport,
            base_url=args.base_url,
            access=args.access,
            suite=args.suite,
            transport=urllib_transport(args.timeout),
            env=os.environ,
        )
        runner.run()
    except PassportError as exc:
        print(f"Ошибка паспорта: {exc}", file=sys.stderr)
        return 2
    print_report(runner)
    if args.json_report:
        args.json_report.write_text(
            json.dumps(json_report(runner), ensure_ascii=False, indent=2)
        )
    return 0 if all(r.outcome == "PASS" for r in runner.results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
