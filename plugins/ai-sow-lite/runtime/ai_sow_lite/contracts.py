"""P00 strict JSON, semantic digests and local Draft 2020-12 contracts."""
from __future__ import annotations

from functools import lru_cache
import hashlib
import json
from pathlib import Path
from typing import TypeAlias

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

JsonValue: TypeAlias = None | bool | int | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]
PLUGIN_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_NAMES = ("model", "pending-items", "decisions", "evidence", "protocol", "artifacts")


def _validate_json(value: object) -> None:
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise TypeError("JSON object keys must be strings")
        for key, child in value.items():
            key.encode("utf-8", errors="strict")
            _validate_json(child)
    elif isinstance(value, list):
        for child in value:
            _validate_json(child)
    elif isinstance(value, str):
        value.encode("utf-8", errors="strict")
    elif value is not None and not isinstance(value, (bool, int)):
        raise TypeError("digest values cannot contain floats or non-JSON types")


def strict_json_loads(text: str | bytes) -> JsonValue:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def reject_number(_):
        raise ValueError("non-integer JSON number")

    if isinstance(text, bytes):
        text = text.decode("utf-8", errors="strict")
    value = json.loads(text, object_pairs_hook=pairs, parse_constant=reject_number, parse_float=reject_number)
    try:
        _validate_json(value)
    except (TypeError, UnicodeError) as exc:
        raise ValueError("invalid JSON value") from exc
    return value


def load_json(path: Path) -> JsonValue:
    return strict_json_loads(path.read_bytes())


def canonical_json_bytes(value: object) -> bytes:
    _validate_json(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def semantic_digest(value: object) -> str:
    return "json-v1:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@lru_cache(maxsize=1)
def _schemas():
    schemas = {name: load_json(PLUGIN_ROOT / "contracts" / f"{name}.schema.json") for name in SCHEMA_NAMES}
    registry = Registry().with_resources((schema["$id"], Resource.from_contents(schema)) for schema in schemas.values())
    return schemas, registry


@lru_cache(maxsize=None)
def schema_validator(name: str, definition: str | None = None) -> Draft202012Validator:
    schemas, registry = _schemas()
    if name not in schemas:
        raise ValueError("unknown schema")
    schema = schemas[name] if definition is None else {"$ref": f"{name}.schema.json#/$defs/{definition}"}
    return Draft202012Validator(schema, registry=registry)
