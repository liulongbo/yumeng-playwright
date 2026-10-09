import re
from decimal import Decimal

from .domain import CollectorError, NumberRange, NumericValue, QuoteValue

_NUMBER = re.compile(r"^(\d+(?:\.\d+)?)(万|[wW])?(\+)?$")
_SIGNED_DECIMAL = re.compile(r"^[+-]?\d+(?:\.\d+)?$")


def number(raw: str, *, unit: str, ratio_input: str = "percent") -> NumericValue:
    text = raw.strip().replace(",", "")
    if unit == "ratio":
        mode = ratio_input
        if mode == "auto":
            mode = "percent" if text.endswith("%") else "decimal"
        if mode not in {"percent", "decimal"}:
            raise CollectorError("MODULE_COLLECTION_FAILED", "UNCONFIRMED_RATIO_UNIT")
        if mode == "percent":
            if not text.endswith("%"):
                raise CollectorError("MODULE_COLLECTION_FAILED", "UNCONFIRMED_RATIO_UNIT")
            digits = text[:-1].strip()
            scale = Decimal(100)
        else:
            if text.endswith("%"):
                raise CollectorError("MODULE_COLLECTION_FAILED", "UNCONFIRMED_RATIO_UNIT")
            digits = text
            scale = Decimal(1)
        if not _SIGNED_DECIMAL.fullmatch(digits):
            raise CollectorError("MODULE_COLLECTION_FAILED", "UNCONFIRMED_RATIO_UNIT")
        amount = Decimal(digits) / scale
        if abs(amount) > 1:
            raise CollectorError("MODULE_COLLECTION_FAILED", "INVALID_RATIO")
        precision = len(digits.split(".")[1]) if "." in digits else 0
        return NumericValue(amount=amount, quantum=(Decimal(10) ** -precision) / scale)
    match = _NUMBER.fullmatch(text)
    if not match:
        raise CollectorError("MODULE_COLLECTION_FAILED", "INVALID_NUMBER")
    digits, suffix, lower = match.groups()
    scale = Decimal(10000) if suffix else Decimal(1)
    precision = len(digits.split(".")[1]) if "." in digits else 0
    return NumericValue(
        amount=Decimal(digits) * scale,
        bound="lower" if lower else "approximate" if suffix else "exact",
        quantum=Decimal(10) ** -precision * scale,
    )


def quote(raw: str, *, currency: str, cooperation_form: str) -> QuoteValue:
    if raw.strip() == "面议":
        return QuoteValue(negotiable=True, currency=currency, cooperation_form=cooperation_form)
    parts = re.split(r"\s*[-~～]\s*", raw.strip())
    if len(parts) > 2:
        raise CollectorError("MODULE_COLLECTION_FAILED", "INVALID_QUOTE")
    nums = [number(p, unit="money") for p in parts]
    if any(n.bound != "exact" for n in nums):
        # Preserve unsupported precision as a failure, never pretend exact money.
        raise CollectorError("MODULE_COLLECTION_FAILED", "UNVERIFIED_QUOTE_PRECISION")
    return QuoteValue(
        amount=NumberRange(min=nums[0].amount, max=nums[-1].amount),
        currency=currency,
        cooperation_form=cooperation_form,
    )


def consistent(a: NumericValue, b: NumericValue) -> bool:
    if a.bound == "lower" or b.bound == "lower":
        return a == b
    if a.bound == b.bound == "exact":
        return a.amount == b.amount
    # Registered rounding rule: nearest display quantum, inclusive half-unit tolerance.
    return abs(a.amount - b.amount) <= max(a.quantum, b.quantum) / 2
