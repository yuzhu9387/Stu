"""Provider-neutral AI boundary."""

from typing import Protocol, TypeVar

from pydantic import BaseModel

StructuredModel = TypeVar("StructuredModel", bound=BaseModel)


class AIProvider(Protocol):
    async def parse_structured(
        self, prompt: str, schema: type[StructuredModel]
    ) -> StructuredModel: ...

    async def embed(self, texts: list[str]) -> list[list[float]]: ...
