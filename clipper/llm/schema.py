"""Minimal JSON Schema validator for LLM responses.

Covers the subset the pipeline's schemas use: type (incl. lists of types),
properties, required, additionalProperties (bool or schema), items, enum,
const, minimum/maximum, exclusiveMinimum/exclusiveMaximum, minItems/maxItems,
minLength/maxLength. No $ref, no combinators: keep step schemas flat.
"""

from __future__ import annotations

import json
import re
from typing import Any

from clipper.llm.errors import SchemaError

_TYPES = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
    # bool is a subclass of int in Python, never a number in JSON.
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
}

_FENCE = re.compile(r"^\s*```(?:json)?\s*\n(.*?)\n\s*```\s*$", re.DOTALL)


def parse_json(text: str) -> Any:
    """Parse a model's text answer as JSON, tolerating a single surrounding
    markdown code fence. Anything else is a SchemaError."""
    match = _FENCE.match(text)
    if match:
        text = match.group(1)
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError) as exc:
        raise SchemaError(f"reponse LLM non JSON : {exc} ; debut : {str(text)[:200]!r}") from exc


def validate(value: Any, schema: dict[str, Any], path: str = "$") -> None:
    """Raise SchemaError naming the first path where value breaks schema."""
    if "type" in schema:
        types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_TYPES[t](value) for t in types):
            raise SchemaError(f"{path} : type attendu {'|'.join(types)}, recu {value!r}")
    if "enum" in schema and value not in schema["enum"]:
        raise SchemaError(f"{path} : {value!r} hors de {schema['enum']}")
    if "const" in schema and value != schema["const"]:
        raise SchemaError(f"{path} : attendu {schema['const']!r}, recu {value!r}")

    if _TYPES["number"](value):
        if "minimum" in schema and value < schema["minimum"]:
            raise SchemaError(f"{path} : {value} < minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            raise SchemaError(f"{path} : {value} > maximum {schema['maximum']}")
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            raise SchemaError(f"{path} : {value} <= {schema['exclusiveMinimum']}")
        if "exclusiveMaximum" in schema and value >= schema["exclusiveMaximum"]:
            raise SchemaError(f"{path} : {value} >= {schema['exclusiveMaximum']}")

    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            raise SchemaError(f"{path} : chaine plus courte que {schema['minLength']}")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            raise SchemaError(f"{path} : chaine plus longue que {schema['maxLength']}")

    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            raise SchemaError(f"{path} : moins de {schema['minItems']} element(s)")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            raise SchemaError(f"{path} : plus de {schema['maxItems']} element(s)")
        if "items" in schema:
            for i, item in enumerate(value):
                validate(item, schema["items"], f"{path}[{i}]")

    if isinstance(value, dict):
        props = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                raise SchemaError(f"{path} : cle requise manquante {key!r}")
        extra = schema.get("additionalProperties", True)
        for key, item in value.items():
            if key in props:
                validate(item, props[key], f"{path}.{key}")
            elif extra is False:
                raise SchemaError(f"{path} : cle inattendue {key!r}")
            elif isinstance(extra, dict):
                validate(item, extra, f"{path}.{key}")
