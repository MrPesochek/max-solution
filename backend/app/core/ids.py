import uuid

_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
_INDEX = {ch: i for i, ch in enumerate(_ALPHABET)}
_WIDTH = 22

PREFIXES = {
    "user": "usr",
    "organization": "org",
    "membership": "mem",
    "invitation": "inv",
    "location": "loc",
    "equipment": "eq",
    "category": "cat",
    "city": "city",
    "district": "dst",
    "provider_profile": "prv",
    "service_contract": "ctr",
    "service_binding": "sb",
    "request": "req",
    "assignment": "asg",
    "offer": "off",
    "visit_proposal": "vp",
    "repair_quote": "rq",
    "cancellation": "cnl",
    "message": "msg",
    "attachment": "att",
    "review": "rev",
    "review_reply": "rvr",
    "moderation_case": "mod",
    "verification_case": "ver",
    "warranty_authorization": "wa",
    "integration_client": "ic",
    "webhook_subscription": "whs",
    "event": "evt",
    "delivery": "dlv",
    "notification": "ntf",
}


class InvalidPublicId(ValueError):
    pass


def _b62encode(value: int) -> str:
    chars = []
    for _ in range(_WIDTH):
        value, rem = divmod(value, 62)
        chars.append(_ALPHABET[rem])
    return "".join(reversed(chars))


def _b62decode(text: str) -> int:
    if len(text) != _WIDTH:
        raise InvalidPublicId("bad length")
    value = 0
    for ch in text:
        try:
            value = value * 62 + _INDEX[ch]
        except KeyError:
            raise InvalidPublicId("bad character") from None
    if value >= 1 << 128:
        raise InvalidPublicId("out of range")
    return value


def encode(kind: str, internal_id: uuid.UUID) -> str:
    return f"{PREFIXES[kind]}_{_b62encode(internal_id.int)}"


def decode(kind: str, public_id: str) -> uuid.UUID:
    prefix, sep, body = public_id.partition("_")
    if not sep or prefix != PREFIXES[kind]:
        raise InvalidPublicId(f"expected {PREFIXES[kind]}_ id")
    return uuid.UUID(int=_b62decode(body))


def encode_opt(kind: str, internal_id: uuid.UUID | None) -> str | None:
    return encode(kind, internal_id) if internal_id is not None else None
