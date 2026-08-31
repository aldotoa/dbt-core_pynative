import datetime
import json
from decimal import Decimal
from typing import Any, Callable, Optional, Union

try:
    import orjson

    _HAS_ORJSON = True
except ImportError:
    orjson = None  # type: ignore
    _HAS_ORJSON = False


def _default_serializer(obj: Any) -> Any:
    if isinstance(obj, (datetime.date, datetime.datetime)):
        return obj.isoformat()
    if isinstance(obj, (set, frozenset)):
        return list(obj)
    if isinstance(obj, Decimal):
        return str(obj)
    if hasattr(obj, "to_dict") and callable(obj.to_dict):
        return obj.to_dict()
    if hasattr(obj, "__dict__"):
        return obj.__dict__
    raise TypeError(f"Type {type(obj)} not serializable")


def orjson_dumps_bytes(
    obj: Any,
    default: Optional[Callable[[Any], Any]] = None,
    option: Optional[int] = None,
) -> bytes:
    """Serialize object to bytes using orjson if available, falling back to json."""
    serializer = default or _default_serializer
    if _HAS_ORJSON:
        opt = option or 0
        try:
            return orjson.dumps(obj, default=serializer, option=opt)
        except TypeError:
            # Fallback if orjson encounters custom types it cannot handle directly
            return json.dumps(obj, default=serializer).encode("utf-8")
    else:
        return json.dumps(obj, default=serializer).encode("utf-8")


def orjson_dumps(
    obj: Any,
    default: Optional[Callable[[Any], Any]] = None,
    option: Optional[int] = None,
) -> str:
    """Serialize object to UTF-8 str using orjson if available, falling back to json."""
    if _HAS_ORJSON:
        return orjson_dumps_bytes(obj, default=default, option=option).decode("utf-8")
    serializer = default or _default_serializer
    return json.dumps(obj, default=serializer)


def orjson_loads(data: Union[str, bytes, bytearray]) -> Any:
    """Deserialize JSON from str, bytes, or bytearray using orjson if available, falling back to json."""
    if _HAS_ORJSON:
        if isinstance(data, str):
            data = data.encode("utf-8")
        return orjson.loads(data)
    else:
        if isinstance(data, (bytes, bytearray)):
            data = data.decode("utf-8")
        return json.loads(data)


def has_orjson() -> bool:
    """Check if orjson is available in the current runtime environment."""
    return _HAS_ORJSON
