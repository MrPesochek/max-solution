#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from collections.abc import Iterable
from typing import Any

DEFAULT_BASE_URL = "https://hakathon.baseclub.lol/api/v1"
DEFAULT_TOKEN = "max_7d8hdiwh"

CHECKS = (
    ("/me", ("organization_id", "client_id", "scopes")),
    ("/requests?limit=5", ("items",)),
    ("/marketplace/requests?limit=5", ("items",)),
    ("/equipment?limit=5", ("items",)),
    ("/service-bindings?limit=5", ("items",)),
    ("/reviews?limit=5", ("items",)),
    ("/events?limit=5", ("events",)),
)


def request_json(base_url: str, path: str, token: str, timeout: float) -> Any:
    url = f"{base_url.rstrip('/')}{path}"
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                raise RuntimeError(f"{path}: HTTP {response.status}")
            return json.load(response)
    except urllib.error.HTTPError as error:
        body = error.read().decode(errors="replace")
        raise RuntimeError(f"{path}: HTTP {error.code}: {body}") from error


def missing_fields(body: Any, required: Iterable[str]) -> list[str]:
    if not isinstance(body, dict):
        return list(required)
    return [field for field in required if field not in body]


def main() -> int:
    parser = argparse.ArgumentParser(description="Проверка доступа жюри к интеграционному API")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--token", default=os.getenv("JURY_API_TOKEN", DEFAULT_TOKEN))
    parser.add_argument("--timeout", type=float, default=10)
    args = parser.parse_args()

    failed = False
    for path, required in CHECKS:
        try:
            body = request_json(args.base_url, path, args.token, args.timeout)
            missing = missing_fields(body, required)
            if missing:
                raise RuntimeError(f"нет полей: {', '.join(missing)}")
            print(f"OK  {path}")
        except (OSError, RuntimeError, ValueError) as error:
            failed = True
            print(f"FAIL {error}", file=sys.stderr)

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
