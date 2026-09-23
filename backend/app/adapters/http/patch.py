from typing import Any

from pydantic import BaseModel

from app.core.unset import UNSET


def field_or_unset(body: BaseModel, name: str) -> Any:
    if name not in body.model_fields_set:
        return UNSET
    return getattr(body, name)
