"""Strict whole-interface localization."""

import json
from collections.abc import Mapping
from enum import StrEnum
from importlib.resources import files
from typing import Self


class Locale(StrEnum):
    """Locales supported across every product surface."""

    EN_US = "en-US"
    ZH_CN = "zh-CN"


class MissingTranslationError(LookupError):
    """Raised when a requested translation does not exist."""


class CatalogParityError(ValueError):
    """Raised when locale catalogs do not expose identical keys."""


class Translator:
    """Render messages without silently mixing languages."""

    def __init__(self, catalogs: Mapping[Locale, Mapping[str, str]]) -> None:
        self._catalogs = {locale: dict(catalog) for locale, catalog in catalogs.items()}
        self._validate_parity()

    @classmethod
    def from_package(cls) -> Self:
        locale_root = files("recipe_agent.locales")
        catalogs: dict[Locale, dict[str, str]] = {}
        for locale in Locale:
            resource = locale_root.joinpath(f"{locale.value}.json")
            raw_catalog = json.loads(resource.read_text(encoding="utf-8"))
            if not isinstance(raw_catalog, dict) or not all(
                isinstance(key, str) and isinstance(value, str)
                for key, value in raw_catalog.items()
            ):
                raise ValueError(f"Invalid translation catalog: {resource.name}")
            catalogs[locale] = raw_catalog
        return cls(catalogs)

    def keys(self, locale: Locale) -> frozenset[str]:
        return frozenset(self._catalogs[locale])

    def render(
        self,
        locale: Locale,
        key: str,
        values: Mapping[str, object] | None = None,
    ) -> str:
        try:
            template = self._catalogs[locale][key]
        except KeyError as error:
            raise MissingTranslationError(f"Missing {locale.value} translation: {key}") from error
        return template.format_map(dict(values or {}))

    def _validate_parity(self) -> None:
        reference_locale = Locale.EN_US
        reference_keys = set(self._catalogs[reference_locale])
        for locale in Locale:
            locale_keys = set(self._catalogs.get(locale, {}))
            if locale_keys != reference_keys:
                missing = sorted(reference_keys - locale_keys)
                extra = sorted(locale_keys - reference_keys)
                raise CatalogParityError(
                    f"Catalog {locale.value} differs; missing={missing}, extra={extra}"
                )
