"""Pinned tags lead the Recipe Book filters; the meals are tags too."""

import pytest

from recipe_agent.domain.kitchen.engine import KitchenError

from .test_engine import fixture_state, run


def test_pinning_starts_from_the_defaults_the_household_has():
    state = run(fixture_state(), "tag.save", {"name": "Soup"})
    state = run(state, "tag.save", {"name": "小孩饭"})
    # Never chosen: nothing stored, so the defaults apply.
    assert "pinnedTags" not in state["settings"]
    state = run(state, "tag.pin", {"name": "Soup", "pinned": True})
    # "Baby-friendly" is a default but not a tag here, so it is not kept.
    assert state["settings"]["pinnedTags"] == ["breakfast", "lunch", "dinner", "小孩饭", "Soup"]
    state = run(state, "tag.pin", {"name": "lunch", "pinned": False})
    assert state["settings"]["pinnedTags"] == ["breakfast", "dinner", "小孩饭", "Soup"]
    # Pinning again moves nothing.
    state = run(state, "tag.pin", {"name": "Soup", "pinned": True})
    assert state["settings"]["pinnedTags"] == ["breakfast", "dinner", "小孩饭", "Soup"]


def test_a_renamed_tag_keeps_its_pin_and_a_deleted_one_drops_it():
    state = run(fixture_state(), "tag.save", {"name": "Soup"})
    state = run(state, "tag.pin", {"name": "Soup", "pinned": True})
    state = run(state, "tag.save", {"name": "Soups", "previous": "Soup"})
    assert state["settings"]["pinnedTags"][-1] == "Soups"
    state = run(state, "tag.delete", {"name": "Soups"})
    assert state["settings"]["pinnedTags"] == ["breakfast", "lunch", "dinner"]


def test_deleting_an_unpinned_tag_leaves_the_defaults_unchosen():
    state = run(fixture_state(), "tag.save", {"name": "Soup"})
    state = run(state, "tag.delete", {"name": "Soup"})
    assert "pinnedTags" not in state["settings"]


@pytest.mark.parametrize(
    "payload", [{"name": "Nope", "pinned": True}, {"name": "breakfast", "pinned": "yes"}]
)
def test_only_known_tags_can_be_pinned(payload):
    with pytest.raises(KitchenError):
        run(fixture_state(), "tag.pin", payload)
