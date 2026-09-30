from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx
import pytest

from connector import db as db_module
from connector import repo
from connector.main import create_app as create_connector
from connector.onec_client import OneCClient
from connector.platform_client import PlatformClient
from connector.profile import load_profile
from connector.settings import Settings as ConnectorSettings
from connector.state import AppState
from connector.webhooks import drain_background_tasks
from emulator import store
from emulator.main import build_state as build_emulator_state
from emulator.main import create_app as create_emulator
from emulator.metadata import ORDER, PROPERTIES, STATES
from emulator.settings import Settings as EmulatorSettings
from emulator.state import EmulatorState
from tests.fake_platform import FakePlatform, build_app, make_envelope, signed_headers

logging.getLogger("httpx").setLevel(logging.WARNING)

SECRET = "test-secret-value"
ODATA_URL = "http://onec.test/unf_demo/odata/standard.odata"


def emulator_settings() -> EmulatorSettings:
    return EmulatorSettings(
        base_name="unf_demo",
        odata_username="odata",
        odata_password="odata-test",
        ui_password="user-pass",
        session_secret="test-session-secret",
    )


def connector_settings(tmp_path: str, **overrides: Any) -> ConnectorSettings:
    values: dict[str, Any] = {
        "platform_api_base_url": "http://platform.test/api/v1",
        "platform_allow_http": True,
        "platform_api_key": "test-api-key",
        "public_base_url": "http://connector.test",
        "onec_odata_url": ODATA_URL,
        "onec_username": "odata",
        "onec_password": "odata-test",
        "onec_allow_http": True,
        "profile": "unf",
        "database_path": f"{tmp_path}/connector.sqlite3",
        "background_retry_attempts": 3,
        "background_retry_base_delay_seconds": 0.01,
        "http_timeout_seconds": 2.0,
        "bootstrap_retry_seconds": 0.05,
    }
    values.update(overrides)
    return ConnectorSettings(**values)


@dataclass
class Harness:
    client: httpx.AsyncClient
    state: AppState
    platform: FakePlatform
    emulator: EmulatorState
    emulator_client: httpx.AsyncClient

    async def drain(self) -> None:
        await drain_background_tasks(self.state, timeout_seconds=5.0)

    def subscribe(self) -> None:
        repo.save_subscription(
            self.state.conn,
            subscription_id="whs_1",
            secret=SECRET,
            url="http://connector.test/webhooks/platform",
            status="active",
        )

    async def deliver(
        self,
        event_type: str,
        request_id: str,
        *,
        version: int | None = None,
        event_id: str | None = None,
        delivery_id: str = "dlv_1",
        data: dict[str, Any] | None = None,
    ) -> httpx.Response:
        card = self.platform.requests.get(request_id)
        envelope = make_envelope(
            event_id=event_id or f"evt_{event_type}_{request_id}_{version}",
            event_type=event_type,
            resource_id=request_id,
            resource_version=version if version is not None else (card or {}).get("version"),
            data=data,
        )
        body = json.dumps(envelope).encode()
        headers = signed_headers(
            SECRET, body, event_id=envelope["event_id"], delivery_id=delivery_id
        )
        response = await self.client.post("/webhooks/platform", content=body, headers=headers)
        await self.drain()
        return response

    def doc(self, request_id: str) -> dict[str, Any]:
        link = repo.get_link(self.state.conn, request_id)
        assert link is not None, "документ 1С для заявки не создан"
        found = store.get(self.emulator.conn, ORDER, str(link["ref_key"]))
        assert found is not None
        return found

    def prop(self, request_id: str, name: str) -> str | None:
        keys = {
            p["Description"]: p["Ref_Key"] for p in store.list_all(self.emulator.conn, PROPERTIES)
        }
        for row in self.doc(request_id).get("ДополнительныеРеквизиты") or []:
            if row["Свойство_Key"] == keys[name]:
                return str(row["Значение"])
        return None

    def edit(self, request_id: str, *, post: bool = True, **changes: Any) -> dict[str, Any]:
        doc = self.doc(request_id)
        body: dict[str, Any] = {}
        if "state" in changes:
            states = {
                s["Description"]: s["Ref_Key"] for s in store.list_all(self.emulator.conn, STATES)
            }
            body["СостояниеЗаказа_Key"] = states[changes.pop("state")]
        if "props" in changes:
            keys = {
                p["Description"]: p["Ref_Key"]
                for p in store.list_all(self.emulator.conn, PROPERTIES)
            }
            rows = [
                {k: v for k, v in r.items() if k != "LineNumber"}
                for r in doc.get("ДополнительныеРеквизиты") or []
            ]
            for name, value in changes.pop("props").items():
                rows = [r for r in rows if r["Свойство_Key"] != keys[name]]
                rows.append({"Свойство_Key": keys[name], "Значение": value})
            body["ДополнительныеРеквизиты"] = rows
        body.update(changes)
        updated = store.update(self.emulator.conn, ORDER, doc["Ref_Key"], body)
        if post:
            updated = store.set_posted(self.emulator.conn, ORDER, doc["Ref_Key"], True)
        return updated

    def item_key(self, name: str) -> str:
        from emulator.metadata import ITEMS

        return next(
            i["Ref_Key"]
            for i in store.list_all(self.emulator.conn, ITEMS)
            if i["Description"] == name
        )

    async def poll(self) -> int:
        from connector.services import outbound

        return await outbound.poll_once(self.state)

    async def ui_login(self) -> None:
        page = await self.emulator_client.get("/login")
        token = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
        assert token
        await self.emulator_client.post(
            "/login", data={"password": "user-pass", "csrf_token": token.group(1)}
        )

    async def ui_form_token(self, ref_key: str) -> str:
        page = await self.emulator_client.get(f"/ui/orders/{ref_key}")
        token = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
        assert token, page.text[:300]
        return token.group(1)


@pytest.fixture
async def harness(tmp_path: object) -> AsyncIterator[Harness]:
    platform = FakePlatform()
    platform_transport = httpx.ASGITransport(app=build_app(platform))

    emulator_state = build_emulator_state(emulator_settings(), in_memory=True)
    emulator_app = create_emulator(state=emulator_state)
    emulator_transport = httpx.ASGITransport(app=emulator_app)

    settings = connector_settings(str(tmp_path))
    state = AppState(
        conn=db_module.connect_memory(),
        client=PlatformClient(settings, transport=platform_transport),
        onec=OneCClient(settings, transport=emulator_transport),
        profile=load_profile(settings.profile_path()),
        settings=settings,
    )
    connector_app = create_connector(state=state, run_loops=False)

    async with (
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=connector_app), base_url="http://connector.test"
        ) as http_client,
        httpx.AsyncClient(transport=emulator_transport, base_url="http://onec.test") as emu_client,
        connector_app.router.lifespan_context(connector_app),
        emulator_app.router.lifespan_context(emulator_app),
    ):
        yield Harness(
            client=http_client,
            state=state,
            platform=platform,
            emulator=emulator_state,
            emulator_client=emu_client,
        )

    await state.client.aclose()
    await state.onec.aclose()
    state.conn.close()
    emulator_state.conn.close()
