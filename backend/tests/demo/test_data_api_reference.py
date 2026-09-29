import asyncio
import subprocess
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
import yaml
from httpx import ASGITransport, AsyncClient

from app.demo import seed
from app.infra.config import Settings
from app.main import create_app
from tests.demo.test_data_api_passport import (
    BASE_URL,
    PASSPORT,
    REPO_ROOT,
    _bridge,
    _outcomes,
    _report,
    checker,
)

VENDOR = REPO_ROOT / "scripts" / "vendor" / "example-data-api"
VALIDATOR = VENDOR / "validate_data_api.py"
SCHEMA = VENDOR / "DATA-API.schema.json"
OPENAPI_INDEX = REPO_ROOT / "openapi" / "data-api.json"


def run_validator(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(VALIDATOR), *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


def test_vendored_validator_is_complete() -> None:
    for name in ("validate_data_api.py", "DATA-API.schema.json", "licence.md", "requirements.txt"):
        assert (VENDOR / name).is_file(), name
    schema = yaml.safe_load(SCHEMA.read_text(encoding="utf-8"))
    assert schema["properties"]["schemaVersion"]["const"] == "1.0"


def test_reference_validator_accepts_passport() -> None:
    result = run_validator(str(PASSPORT))
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "ПОДТВЕРЖДЕНИЕ" in output, output
    assert "ВНИМАНИЕ" not in output, output


def test_reference_validator_cross_checks_our_openapi_index() -> None:
    """Пути и методы сверяются со сводной картой openapi/data-api.json (api.openapi)."""
    doc = yaml.safe_load(PASSPORT.read_text(encoding="utf-8"))
    assert (PASSPORT.parent / doc["api"]["openapi"]).resolve() == OPENAPI_INDEX
    explicit = run_validator(
        str(PASSPORT), "--openapi", str(OPENAPI_INDEX), "--schema", str(SCHEMA)
    )
    assert explicit.returncode == 0, explicit.stdout + explicit.stderr


def test_reference_validator_rejects_broken_passport(tmp_path: Path) -> None:
    """Контроль, что валидатор действительно работает: старый формат и лишние поля — код 1."""
    doc = yaml.safe_load(PASSPORT.read_text(encoding="utf-8"))
    doc["schemaVersion"] = "2.0"
    doc["checks"][0]["extra"] = True
    doc["checks"][-1]["dependsOn"] = ["no-such-check"]
    broken = tmp_path / "DATA-API.yaml"
    broken.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    result = run_validator(str(broken), "--openapi", str(OPENAPI_INDEX))
    assert result.returncode == 1, result.stdout + result.stderr
    assert "НЕДЕЙСТВИТЕЛЬНЫЙ" in result.stdout
    assert "schemaVersion" in result.stdout
    assert "no-such-check" in result.stdout


def test_passport_keeps_placeholders_explicit_and_secret_free() -> None:
    doc = yaml.safe_load(PASSPORT.read_text(encoding="utf-8"))
    assert doc["api"]["baseUrl"].startswith("https://")
    assert doc["solution"]["teamId"]
    for check in doc["checks"]:
        headers = (check.get("request") or {}).get("headers") or {}
        authorization = headers.get("Authorization", "${}")
        assert "${" in authorization, f"{check['id']}: литеральный Authorization"
    assert "rk_" not in PASSPORT.read_text(encoding="utf-8")


@pytest_asyncio.fixture
async def client(settings: Settings) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url=BASE_URL) as http:
        yield http


@pytest.mark.usefixtures("clean_db")
async def test_reference_passport_passes_against_application(client: AsyncClient) -> None:
    """Чистый DATA-API.yaml (без DATA-API.extended.yaml) исполняется против приложения:
    только то, что понимает формат организаторов — extract/${...}, dependsOn, cleanup."""
    await seed.run()
    passport: Any = checker.load_passport(PASSPORT)
    plain = checker.Passport(passport.doc, {}, passport.root)
    runner = checker.Runner(
        plain,
        base_url=BASE_URL,
        transport=_bridge(client, asyncio.get_running_loop()),
        env={},
        sleep=lambda _: None,
    )

    await asyncio.to_thread(runner.run)

    outcomes = _outcomes(runner)
    assert set(outcomes.values()) == {"PASS"}, _report(runner)
    assert len(outcomes) == len(plain.checks) + len(plain.cleanup)
    assert outcomes["cleanup:revoke-check-key"] == "PASS"
