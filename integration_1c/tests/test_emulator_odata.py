from __future__ import annotations

import httpx
import pytest

from emulator.main import build_state, create_app
from emulator.odata_query import QueryError, parse_filter
from tests.conftest import emulator_settings

BASE = "/unf_demo/odata/standard.odata"
AUTH = ("odata", "odata-test")


@pytest.fixture
async def odata():
    app = create_app(state=build_state(emulator_settings(), in_memory=True))
    transport = httpx.ASGITransport(app=app)
    async with (
        httpx.AsyncClient(transport=transport, base_url="http://onec.test", auth=AUTH) as client,
        app.router.lifespan_context(app),
    ):
        yield client


async def _create_order(odata, **fields):
    counterparty = (
        await odata.post(
            f"{BASE}/Catalog_Контрагенты?$format=json",
            json={"Description": "ООО Кафе", "ИНН": "7701000001"},
        )
    ).json()
    body = {"Контрагент_Key": counterparty["Ref_Key"], **fields}
    response = await odata.post(f"{BASE}/Document_ЗаказНаряд?$format=json", json=body)
    assert response.status_code == 201
    return response.json()


async def test_collection_format(odata) -> None:
    response = await odata.get(f"{BASE}/Catalog_СостоянияЗаказНарядов?$format=json")

    assert response.status_code == 200
    payload = response.json()
    assert payload["odata.metadata"].endswith(f"{BASE}/$metadata#Catalog_СостоянияЗаказНарядов")
    names = [item["Description"] for item in payload["value"]]
    assert names[:3] == ["Новый", "Принят", "Отказ"]
    item = payload["value"][0]
    assert len(item["Ref_Key"]) == 36
    assert item["DeletionMark"] is False
    assert isinstance(item["DataVersion"], str) and item["DataVersion"]


async def test_created_document_shape(odata) -> None:
    doc = await _create_order(
        odata, Комментарий="тест", Работы=[{"Содержание": "Диагностика", "Сумма": 1500}]
    )

    assert doc["odata.metadata"].endswith("#Document_ЗаказНаряд/@Element")
    assert doc["Number"] == "ЗН00-000001"
    assert doc["Posted"] is False
    assert doc["Начало"] == "0001-01-01T00:00:00"
    assert doc["СуммаДокумента"] == 1500
    assert doc["Работы"][0]["LineNumber"] == "1"
    assert doc["Контрагент@navigationLinkUrl"] == (
        f"Document_ЗаказНаряд(guid'{doc['Ref_Key']}')/Контрагент"
    )


async def test_filter_select_top_orderby(odata) -> None:
    first = await _create_order(odata, Комментарий="первый")
    second = await _create_order(odata, Комментарий="второй")
    await _create_order(odata, Комментарий="третий")

    guid_filter = f"Ref_Key eq guid'{first['Ref_Key']}' or Ref_Key eq guid'{second['Ref_Key']}'"
    response = await odata.get(
        f"{BASE}/Document_ЗаказНаряд",
        params={"$format": "json", "$filter": guid_filter, "$select": "Ref_Key,DataVersion"},
    )
    value = response.json()["value"]
    assert {v["Ref_Key"] for v in value} == {first["Ref_Key"], second["Ref_Key"]}
    assert all(set(v) == {"Ref_Key", "DataVersion"} for v in value)

    response = await odata.get(
        f"{BASE}/Document_ЗаказНаряд",
        params={"$format": "json", "$orderby": "Number desc", "$top": "2", "$select": "Number"},
    )
    assert [v["Number"] for v in response.json()["value"]] == ["ЗН00-000003", "ЗН00-000002"]

    response = await odata.get(
        f"{BASE}/Document_ЗаказНаряд",
        params={"$format": "json", "$filter": "Комментарий eq 'второй' and Posted eq false"},
    )
    assert [v["Ref_Key"] for v in response.json()["value"]] == [second["Ref_Key"]]

    response = await odata.get(
        f"{BASE}/Document_ЗаказНаряд",
        params={"$format": "json", "$filter": "substringof('ер', Комментарий)"},
    )
    assert len(response.json()["value"]) == 1


async def test_patch_changes_data_version_and_replaces_table(odata) -> None:
    doc = await _create_order(
        odata, Работы=[{"Содержание": "a", "Сумма": 1}, {"Содержание": "b", "Сумма": 2}]
    )
    url = f"{BASE}/Document_ЗаказНаряд(guid'{doc['Ref_Key']}')?$format=json"

    patched = (await odata.patch(url, json={"Работы": [{"Содержание": "c", "Сумма": 5}]})).json()

    assert patched["DataVersion"] != doc["DataVersion"]
    assert [r["Содержание"] for r in patched["Работы"]] == ["c"]
    assert patched["СуммаДокумента"] == 5
    assert patched["Number"] == doc["Number"]


async def test_post_and_unpost(odata) -> None:
    doc = await _create_order(odata)
    key = doc["Ref_Key"]

    response = await odata.post(f"{BASE}/Document_ЗаказНаряд(guid'{key}')/Post()?$format=json")
    assert response.status_code == 200
    posted = (await odata.get(f"{BASE}/Document_ЗаказНаряд(guid'{key}')?$format=json")).json()
    assert posted["Posted"] is True
    assert posted["DataVersion"] != doc["DataVersion"]

    await odata.post(f"{BASE}/Document_ЗаказНаряд(guid'{key}')/Unpost()?$format=json")
    unposted = (await odata.get(f"{BASE}/Document_ЗаказНаряд(guid'{key}')?$format=json")).json()
    assert unposted["Posted"] is False


async def test_posting_without_counterparty_fails_like_1c(odata) -> None:
    doc = (await odata.post(f"{BASE}/Document_ЗаказНаряд?$format=json", json={})).json()

    response = await odata.post(f"{BASE}/Document_ЗаказНаряд(guid'{doc['Ref_Key']}')/Post()")

    assert response.status_code == 500
    assert "Контрагент" in response.json()["odata.error"]["message"]["value"]


async def test_errors_use_odata_format(odata) -> None:
    unknown = await odata.post(f"{BASE}/Document_ЗаказНаряд?$format=json", json={"НетТакого": 1})
    assert unknown.status_code == 400
    assert unknown.json()["odata.error"]["message"]["lang"] == "ru"

    missing = await odata.get(
        f"{BASE}/Document_ЗаказНаряд(guid'00000000-0000-0000-0000-000000000001')?$format=json"
    )
    assert missing.status_code == 404

    bad_filter = await odata.get(
        f"{BASE}/Document_ЗаказНаряд", params={"$format": "json", "$filter": "Нет eq 1"}
    )
    assert bad_filter.status_code == 400

    no_set = await odata.get(f"{BASE}/Document_Нет?$format=json")
    assert no_set.status_code == 404


async def test_basic_auth_required(odata) -> None:
    response = await odata.get(f"{BASE}/Catalog_Контрагенты?$format=json", auth=("odata", "wrong"))
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"].startswith("Basic")


async def test_metadata_lists_entity_sets(odata) -> None:
    response = await odata.get(f"{BASE}/$metadata")
    assert response.status_code == 200
    assert '<EntitySet Name="Document_ЗаказНаряд"' in response.text
    assert "Document_ЗаказНаряд_Работы_RowType" in response.text


def test_filter_parser_literals() -> None:
    fields = {"Date", "Сумма", "Ref_Key", "Posted"}
    predicate = parse_filter(
        "Date ge datetime'2026-09-01T00:00:00' and (Сумма gt 100 or not Posted eq true)", fields
    )
    assert predicate({"Date": "2026-09-02T10:00:00", "Сумма": 50, "Posted": False})
    assert not predicate({"Date": "2026-08-31T10:00:00", "Сумма": 500, "Posted": False})
    with pytest.raises(QueryError):
        parse_filter("Сумма gt", fields)


def test_seed_adds_new_states_to_existing_base() -> None:
    from emulator import store
    from emulator.metadata import SEED_STATES, STATES

    state = build_state(emulator_settings(), in_memory=True)
    store.seed(state.conn)
    names = [s["Description"] for s in store.list_all(state.conn, STATES)]
    assert names == SEED_STATES
    for row in store.list_all(state.conn, STATES):
        if row["Description"] == "Отмена не согласована":
            state.conn.execute("DELETE FROM objects WHERE ref_key = ?", (row["Ref_Key"],))
    store.seed(state.conn)
    store.seed(state.conn)
    names = [s["Description"] for s in store.list_all(state.conn, STATES)]
    assert sorted(names) == sorted(SEED_STATES)
