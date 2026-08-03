"""The machine-readable tool capability matrix.

One entry per registered MCP tool, authored as JSON in
``capability_matrix.json`` next to this module. Tests enforce that the matrix
covers exactly the registered tool set and that declared parameter names exist
on the real tool schemas. A tool without an entry is denied in cloud mode.
"""

import json
from pathlib import Path

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator


_RESULT_PATH_RE = re.compile(
    r"^(?:\$|[A-Za-z_][A-Za-z0-9_]*(?:\[\])?"
    r"(?:\.(?:[A-Za-z_][A-Za-z0-9_]*|\*)(?:\[\])?)*)$"
)


class ResultTerritoryRecord(BaseModel):
    """One exact path to property-bearing records in a typed result."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str
    model: str
    location_mode: Literal[
        "structured_property",
        "address",
        "property_address",
        "location_values",
        "county_sale",
        "geo",
        "non_geographic_text",
        "permit_property",
        "permit_collection",
        "stalled_signal",
    ]
    location_fields: tuple[str, ...]
    allow_extra_fields: bool = False

    @field_validator("path")
    @classmethod
    def _valid_path(cls, value: str) -> str:
        normalized = value.strip()
        if _RESULT_PATH_RE.fullmatch(normalized) is None:
            raise ValueError("result record path is malformed")
        return normalized

    @field_validator("model")
    @classmethod
    def _nonempty_model(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("result record model must not be empty")
        return normalized

    @field_validator("location_fields")
    @classmethod
    def _valid_location_fields(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(field.strip() for field in value)
        if not normalized or any(not field for field in normalized):
            raise ValueError("result location fields must not be empty")
        if len(normalized) != len(set(normalized)):
            raise ValueError("result location fields must be unique")
        return normalized


class ResultLocationBinding(BaseModel):
    """One typed relationship between request and/or result location paths."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    left_source: Literal["request", "result"]
    left_path: str
    left_mode: Literal["location", "geo"]
    right_source: Literal["request", "result"]
    right_path: str
    right_mode: Literal["location", "geo"]
    relation: Literal["exact", "exact_multiset", "pairwise_exact", "each_within"]

    @field_validator("left_path", "right_path")
    @classmethod
    def _valid_binding_path(cls, value: str) -> str:
        normalized = value.strip()
        if _RESULT_PATH_RE.fullmatch(normalized) is None:
            raise ValueError("location binding path is malformed")
        return normalized

    @model_validator(mode="after")
    def _meaningful_result_binding(self) -> "ResultLocationBinding":
        if self.left_source == self.right_source == "request":
            raise ValueError("location binding must validate a result path")
        if self.relation == "each_within" and (
            self.left_mode != "geo" or self.right_mode != "location"
        ):
            raise ValueError("each-within binding requires geo to location")
        return self


class ResultTerritoryContract(BaseModel):
    """One complete typed representation accepted from a tool result."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    envelope_model: str
    request_location_param: str | None = None
    result_location_field: str | None = None
    location_bindings: tuple[ResultLocationBinding, ...] = ()
    records: tuple[ResultTerritoryRecord, ...]
    forbid_nonempty_paths: tuple[str, ...] = ()

    @field_validator("envelope_model")
    @classmethod
    def _nonempty_envelope_model(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("result envelope model must not be empty")
        return normalized

    @field_validator("request_location_param", "result_location_field")
    @classmethod
    def _normalize_optional_field(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("result location binding fields must not be empty")
        return normalized

    @field_validator("forbid_nonempty_paths")
    @classmethod
    def _valid_forbidden_paths(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(path.strip() for path in value)
        if any(_RESULT_PATH_RE.fullmatch(path) is None for path in normalized):
            raise ValueError("forbidden result path is malformed")
        if len(normalized) != len(set(normalized)):
            raise ValueError("forbidden result paths must be unique")
        return normalized

    @model_validator(mode="after")
    def _complete_binding_and_unique_paths(self) -> "ResultTerritoryContract":
        if (self.request_location_param is None) != (
            self.result_location_field is None
        ):
            raise ValueError("result location binding must declare both fields")
        if not self.records:
            raise ValueError("result territory contract must declare records")
        binding_keys = tuple(
            (
                binding.left_source,
                binding.left_path,
                binding.left_mode,
                binding.right_source,
                binding.right_path,
                binding.right_mode,
                binding.relation,
            )
            for binding in self.location_bindings
        )
        if len(binding_keys) != len(set(binding_keys)):
            raise ValueError("result location bindings must be unique")
        paths = tuple(record.path for record in self.records)
        if len(paths) != len(set(paths)):
            raise ValueError("result territory record paths must be unique")
        return self


class RequestTerritoryContract(BaseModel):
    """One complete alternative representation of property-bearing input."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    records: tuple[ResultTerritoryRecord, ...]
    forbid_present_paths: tuple[str, ...] = ()
    envelope_path: str | None = None
    envelope_model: str | None = None
    allow_envelope_extra_fields: bool = False

    @model_validator(mode="after")
    def _nonempty_unique_paths(self) -> "RequestTerritoryContract":
        if not self.records:
            raise ValueError("request territory contract must declare records")
        paths = tuple(record.path for record in self.records)
        if len(paths) != len(set(paths)):
            raise ValueError("request territory record paths must be unique")
        forbidden = tuple(path.strip() for path in self.forbid_present_paths)
        if any(_RESULT_PATH_RE.fullmatch(path) is None for path in forbidden):
            raise ValueError("forbidden request path is malformed")
        if len(forbidden) != len(set(forbidden)):
            raise ValueError("forbidden request paths must be unique")
        if (self.envelope_path is None) != (self.envelope_model is None):
            raise ValueError(
                "request envelope validation requires both path and model"
            )
        if (
            self.envelope_path is not None
            and _RESULT_PATH_RE.fullmatch(self.envelope_path.strip()) is None
        ):
            raise ValueError("request envelope path is malformed")
        if self.envelope_model is not None and not self.envelope_model.strip():
            raise ValueError("request envelope model must not be empty")
        return self


class ToolCapability(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    tool: str
    allowed_profiles: tuple[str, ...]
    sensitive: bool = False
    sensitive_params: tuple[str, ...] = ()
    territory_params: tuple[str, ...] = ()
    property_reference_params: tuple[str, ...] = ()
    request_territory_records: tuple[ResultTerritoryRecord, ...] = ()
    request_territory_contracts: tuple[RequestTerritoryContract, ...] = ()
    result_territory_contracts: tuple[ResultTerritoryContract, ...] = ()
    # Identity-shaped argument names (see engine.RESERVED_IDENTITY_ARGS) that
    # are legitimate business parameters on THIS tool and must survive cloud
    # sanitization instead of being stripped as identity-smuggling attempts.
    preserve_params: tuple[str, ...] = ()
    ownership_relevant: bool = False
    quota: str | None = None
    approval: str | None = None
    module: str = ""

    @model_validator(mode="after")
    def _unique_result_contract_models(self) -> "ToolCapability":
        if len(self.property_reference_params) != len(
            set(self.property_reference_params)
        ):
            raise ValueError("property reference parameters must be unique")
        if set(self.property_reference_params) & set(self.territory_params):
            raise ValueError(
                "property reference parameters cannot also be territory parameters"
            )
        request_paths = tuple(
            record.path for record in self.request_territory_records
        )
        if len(request_paths) != len(set(request_paths)):
            raise ValueError("request territory record paths must be unique")
        request_contract_keys = tuple(
            (
                tuple(
                    (
                        record.path,
                        record.model,
                        record.location_mode,
                        record.location_fields,
                    )
                    for record in contract.records
                ),
                contract.forbid_present_paths,
                contract.envelope_path,
                contract.envelope_model,
            )
            for contract in self.request_territory_contracts
        )
        if len(request_contract_keys) != len(set(request_contract_keys)):
            raise ValueError("request territory contracts must be unique")
        models = tuple(
            contract.envelope_model for contract in self.result_territory_contracts
        )
        if len(models) != len(set(models)):
            raise ValueError("result territory contract models must be unique")
        for contract in self.result_territory_contracts:
            if any(record.allow_extra_fields for record in contract.records):
                raise ValueError(
                    "result territory contracts cannot allow undeclared fields"
                )
            if (
                contract.request_location_param is not None
                and contract.request_location_param not in self.territory_params
            ):
                raise ValueError(
                    "result request-location binding must name a territory parameter"
                )
            for binding in contract.location_bindings:
                for source, path in (
                    (binding.left_source, binding.left_path),
                    (binding.right_source, binding.right_path),
                ):
                    if source != "request":
                        continue
                    root_param = path.split(".", 1)[0].removesuffix("[]")
                    if root_param not in self.territory_params:
                        raise ValueError(
                            "result location binding request path must name a "
                            "territory parameter"
                        )
        return self


_MATRIX_PATH = Path(__file__).with_name("capability_matrix.json")


def _load() -> dict[str, ToolCapability]:
    if not _MATRIX_PATH.exists():
        return {}
    raw = json.loads(_MATRIX_PATH.read_text(encoding="utf-8"))
    return {
        name: ToolCapability.model_validate({"tool": name, **entry})
        for name, entry in raw.items()
    }


CAPABILITIES: dict[str, ToolCapability] = _load()


def capability_for(tool_name: str) -> ToolCapability | None:
    return CAPABILITIES.get(tool_name)


def export_matrix() -> dict[str, dict]:
    """The matrix as plain JSON-ready data."""
    return {
        name: cap.model_dump(exclude={"tool"}) for name, cap in CAPABILITIES.items()
    }
