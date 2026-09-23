from app.core.errors import ValidationFailed

_N10 = (2, 4, 10, 3, 5, 9, 4, 6, 8)
_N11 = (7, 2, 4, 10, 3, 5, 9, 4, 6, 8)
_N12 = (3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8)


def normalize_inn(raw: str) -> str:
    return "".join(ch for ch in raw if ch.isdigit())


def _checksum(digits: list[int], weights: tuple[int, ...]) -> int:
    return sum(w * d for w, d in zip(weights, digits, strict=True)) % 11 % 10


def is_valid_inn(normalized: str) -> bool:
    if not normalized.isdigit():
        return False
    digits = [int(ch) for ch in normalized]
    if len(digits) == 10:
        return _checksum(digits[:9], _N10) == digits[9]
    if len(digits) == 12:
        return _checksum(digits[:10], _N11) == digits[10] and (
            _checksum(digits[:11], _N12) == digits[11]
        )
    return False


def require_valid_inn(raw: str | None) -> str | None:
    """Пустое значение допустимо; заполненное обязано пройти контрольные цифры."""
    if raw is None or not raw.strip():
        return None
    normalized = normalize_inn(raw)
    if not is_valid_inn(normalized):
        raise ValidationFailed("Некорректный ИНН", field="inn")
    return normalized
