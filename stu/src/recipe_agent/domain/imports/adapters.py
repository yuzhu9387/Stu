"""Deterministic adapter selection for supported recipe inputs."""

from typing import Protocol
from uuid import UUID

from recipe_agent.domain.imports.contracts import ExtractedInput, ImportCommand, InputKind


class ExternalPlatformError(RuntimeError):
    """An external content source could not be read."""


class UnsupportedInputError(ValueError):
    """No registered adapter supports an import command."""


class InputAdapter(Protocol):
    priority: int

    def supports(self, command: ImportCommand) -> bool: ...

    async def extract(self, raw_input_id: UUID, command: ImportCommand) -> ExtractedInput: ...


class AdapterRegistry:
    def __init__(self, adapters: list[InputAdapter]) -> None:
        self._adapters = sorted(
            adapters,
            key=lambda adapter: getattr(adapter, "priority", 0),
            reverse=True,
        )

    def resolve(self, command: ImportCommand) -> InputAdapter:
        for adapter in self._adapters:
            if adapter.supports(command):
                return adapter
        raise UnsupportedInputError(f"Unsupported import kind: {command.kind}")

    async def extract(self, raw_input_id: UUID, command: ImportCommand) -> ExtractedInput:
        supported = [adapter for adapter in self._adapters if adapter.supports(command)]
        if not supported:
            raise UnsupportedInputError(f"Unsupported import kind: {command.kind}")
        last_error: ExternalPlatformError | None = None
        for adapter in supported:
            try:
                return await adapter.extract(raw_input_id, command)
            except ExternalPlatformError as error:
                last_error = error
        if last_error is not None:
            raise last_error
        raise UnsupportedInputError(f"Unsupported import kind: {command.kind}")


class TextAdapter:
    priority = 50

    def supports(self, command: ImportCommand) -> bool:
        return command.kind is InputKind.TEXT

    async def extract(self, raw_input_id: UUID, command: ImportCommand) -> ExtractedInput:
        return ExtractedInput(text=command.source)


class ImageAdapter:
    priority = 50

    def supports(self, command: ImportCommand) -> bool:
        return command.kind is InputKind.IMAGE and command.object_key is not None

    async def extract(self, raw_input_id: UUID, command: ImportCommand) -> ExtractedInput:
        return ExtractedInput(text=command.source, object_keys=(command.object_key or "",))


class ExcelAdapter:
    priority = 50

    def supports(self, command: ImportCommand) -> bool:
        return command.kind is InputKind.EXCEL and command.object_key is not None

    async def extract(self, raw_input_id: UUID, command: ImportCommand) -> ExtractedInput:
        return ExtractedInput(text=command.source, object_keys=(command.object_key or "",))


class XiaohongshuURLAdapter:
    priority = 100

    def supports(self, command: ImportCommand) -> bool:
        return command.kind is InputKind.URL and "xiaohongshu.com" in command.source.casefold()

    async def extract(self, raw_input_id: UUID, command: ImportCommand) -> ExtractedInput:
        raise ExternalPlatformError("Xiaohongshu extraction requires a configured browser worker")


class GenericURLAdapter:
    priority = 10

    def supports(self, command: ImportCommand) -> bool:
        return command.kind is InputKind.URL and command.source.casefold().startswith(
            ("http://", "https://")
        )

    async def extract(self, raw_input_id: UUID, command: ImportCommand) -> ExtractedInput:
        raise ExternalPlatformError("URL extraction requires a configured fetch worker")
