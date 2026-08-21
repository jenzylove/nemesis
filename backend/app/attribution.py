from abc import ABC
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .models import ChainName

EntityType = Literal["exchange", "bridge", "mixer", "protocol", "service"]


class EntityAttribution(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entity_name: str = Field(min_length=1, max_length=160)
    entity_type: EntityType
    address: str = Field(pattern=r"^0x[a-fA-F0-9]{40}$")
    chain: ChainName
    source: str = Field(min_length=1, max_length=240)
    confidence: float = Field(ge=0, le=1)
    evidence_type: str = Field(min_length=1, max_length=120)

    @field_validator("address")
    @classmethod
    def normalize_address(cls, value: str) -> str:
        return value.lower()

    @property
    def actionable(self) -> bool:
        return self.entity_type in {"exchange", "service"}


class EntityAttributionProvider(ABC):
    async def lookup(self, chain: ChainName, address: str) -> EntityAttribution | None:
        raise NotImplementedError


class CuratedAttributionProvider(EntityAttributionProvider):
    def __init__(self, entries: list[EntityAttribution] | None = None):
        self.entries: dict[tuple[str, str], EntityAttribution] = {}
        for entry in entries or default_curated_attributions():
            self.entries[(entry.chain, entry.address.lower())] = entry

    async def lookup(self, chain: ChainName, address: str) -> EntityAttribution | None:
        return self.entries.get((chain, address.lower()))


def default_curated_attributions() -> list[EntityAttribution]:
    source = "Base official contract registry"
    evidence_type = "official_contract_registry"
    return [
        EntityAttribution(
            entity_name="Base L1 Standard Bridge",
            entity_type="bridge",
            address="0x3154cf16ccdb4c6d922629664174b904d80f2c35",
            chain="ethereum",
            source=source,
            confidence=1.0,
            evidence_type=evidence_type,
        ),
        EntityAttribution(
            entity_name="Base Optimism Portal",
            entity_type="bridge",
            address="0x49048044d57e1c92a77f79988d21fa8faf74e97e",
            chain="ethereum",
            source=source,
            confidence=1.0,
            evidence_type=evidence_type,
        ),
        EntityAttribution(
            entity_name="Base L2 Standard Bridge",
            entity_type="bridge",
            address="0x4200000000000000000000000000000000000010",
            chain="base",
            source=source,
            confidence=1.0,
            evidence_type=evidence_type,
        ),
    ]
