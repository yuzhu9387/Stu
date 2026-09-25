import pytest

from recipe_agent.domain.identity.locale import (
    Locale,
    MissingTranslationError,
    Translator,
)


def test_locale_catalogs_have_identical_keys() -> None:
    translator = Translator.from_package()

    assert translator.keys(Locale.EN_US) == translator.keys(Locale.ZH_CN)


def test_translator_renders_only_the_selected_language() -> None:
    translator = Translator.from_package()

    assert translator.render(Locale.EN_US, "agent.stage.acting", {"tool": "save_recipe"}) == (
        "Acting: running save_recipe."
    )
    assert translator.render(Locale.ZH_CN, "agent.stage.acting", {"tool": "save_recipe"}) == (
        "执行：正在运行 save_recipe。"
    )


def test_translator_rejects_unknown_keys() -> None:
    translator = Translator.from_package()

    with pytest.raises(MissingTranslationError):
        translator.render(Locale.EN_US, "missing.key")
