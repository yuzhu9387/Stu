"""Calendar-day dish rotation, independent of likes and generation provider."""

import re
import unicodedata
from datetime import date
from typing import Any


def name_aliases(value: str) -> set[str]:
    """Match punctuation/case variants and explicit bilingual parenthetical names."""
    normalized = unicodedata.normalize("NFKC", value).casefold()
    names = [normalized, *re.split(r"[()/|]", normalized)]
    return {key for part in names if (key := "".join(c for c in part if c.isalnum()))}


# Plain everyday accompaniments are not distinct dishes. This intentionally small
# exact-name set does not exempt rice dishes, porridges, noodles or mixed meals.
PLAIN_STAPLES = {
    "rice",
    "steamedrice",
    "plainsteamedrice",
    "cookedrice",
    "whiterice",
    "brownrice",
    "cookedbrownrice",
    "米饭",
    "白米饭",
    "糙米饭",
    "清水",
    "water",
    "milk",
    "牛奶",
    "plainbread",
    "白面包",
}


def meal_dishes(
    state: dict[str, Any], plan: dict[str, Any], meal: dict[str, Any]
) -> list[dict[str, Any]]:
    recipes = {item["id"]: item for item in state["recipes"]}
    inventory = {item["id"]: item for item in state["inventory"]}
    prep = {item["id"]: item for item in plan["prep"]}
    dishes = []
    for component in meal["components"]:
        stock = inventory.get(component.get("inventoryId"), {})
        task = prep.get(component.get("prepId"), {})
        identifier = component.get("recipeId") or stock.get("recipeId") or task.get("recipeId")
        recipe = recipes.get(identifier, {})
        name = recipe.get("name") or stock.get("name") or task.get("name") or component["name"]
        aliases = name_aliases(name)
        name_parts = {
            key
            for part in re.split(r"[()/|]", unicodedata.normalize("NFKC", name).casefold())
            if (key := "".join(c for c in part if c.isalnum()))
        }
        if name_parts and name_parts <= PLAIN_STAPLES and len(recipe.get("ingredients", [])) <= 3:
            continue
        keys = {f"name:{alias}" for alias in aliases - PLAIN_STAPLES}
        if identifier:
            keys.add(f"recipe:{identifier}")
        dishes.append({"name": name, "keys": keys, "recipeId": identifier})
    return dishes


def adjacent_history(state: dict[str, Any], plan: dict[str, Any]) -> list[dict[str, Any]]:
    """One authoritative plan per other week, with per-meal execution fallback."""
    authoritative: dict[str, dict[str, Any]] = {}
    for other in state["plans"]:
        if other["weekStart"] == plan["weekStart"]:
            continue
        current = authoritative.get(other["weekStart"])
        priority = (other["status"] == "confirmed", other["version"], other["id"])
        if current is None or priority > (
            current["status"] == "confirmed",
            current["version"],
            current["id"],
        ):
            authoritative[other["weekStart"]] = other
    records = []
    for other in authoritative.values():
        for meal in other["meals"]:
            if meal.get("included", True) and (
                meal["status"] == "completed"
                or (other["status"] == "confirmed" and meal["status"] == "planned")
            ):
                for dish in meal_dishes(state, other, meal):
                    records.append({**dish, "day": meal["day"], "external": True})
    return records


def repetition_context(state: dict[str, Any], week_start: str) -> dict[str, Any]:
    gap = state["settings"].get("recipeRepeatGapDays", 1)
    start = date.fromisoformat(week_start)
    history = [
        {key: value for key, value in record.items() if key not in {"keys", "external"}}
        for record in adjacent_history(state, {"weekStart": week_start})
        if -gap <= (date.fromisoformat(record["day"]) - start).days <= 6 + gap
    ]
    return {
        "interveningDays": gap,
        "minimumCalendarDayDifference": gap + 1,
        "rule": f"The same dish on different days must be at least {gap + 1} calendar days apart.",
        "nearbyHistory": history,
        "plainStaplesMayRepeat": True,
    }


def repeat_conflicts(state: dict[str, Any], plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Every pair of the same dish too close together, in the order found.

    Each conflict names the dish, both days, and the plan meals involved
    (a neighbouring week's meal has no id here).
    """
    if not plan.get("weekStart"):
        return []  # Standalone prep timing has no calendar to check.
    gap = state["settings"].get("recipeRepeatGapDays", 1)
    records = [{**record, "meal": None} for record in adjacent_history(state, plan)]
    for meal in plan["meals"]:
        if meal["status"] == "skipped" or not meal.get("included", True):
            continue
        for dish in meal_dishes(state, plan, meal):
            records.append({**dish, "day": meal["day"], "external": False, "meal": meal["id"]})
    records.sort(key=lambda entry: entry["day"])
    conflicts = []
    for index, current in enumerate(records):
        current_day = date.fromisoformat(current["day"])
        for previous in reversed(records[:index]):
            difference = (current_day - date.fromisoformat(previous["day"])).days
            if difference > gap:
                break
            if (
                difference > 0
                and not (current["external"] and previous["external"])
                and current["keys"] & previous["keys"]
            ):
                conflicts.append(
                    {
                        "dish": current["name"],
                        "days": [previous["day"], current["day"]],
                        "mealIds": [m for m in (previous["meal"], current["meal"]) if m],
                        "gap": gap,
                    }
                )
    return conflicts


def repeat_message(conflict: dict[str, Any]) -> str:
    first, second = conflict["days"]
    return (
        f"Dish repeat: {conflict['dish']} on {first} and {second}; "
        f"leave at least {conflict['gap']} full day(s) between repeats"
    )


def validate_plan_repetition(state: dict[str, Any], plan: dict[str, Any]) -> None:
    """Refuse a plan whose dishes repeat too soon (strict callers only)."""
    conflicts = repeat_conflicts(state, plan)
    if conflicts:
        raise ValueError(repeat_message(conflicts[0]))


def blocked_dishes(
    state: dict[str, Any], plan: dict[str, Any], meal_ids: set[str]
) -> dict[str, list[dict[str, str]]]:
    """For each meal about to change, the dishes it cannot use.

    Only meals that stay as they are (and neighbouring weeks) count: a dish on
    a fixed meal within the repeat gap of the changing meal's day would break
    the rotation rule. Repeats among the changing meals themselves are left to
    the proposal and checked afterwards.
    """
    gap = state["settings"].get("recipeRepeatGapDays", 1)
    fixed = adjacent_history(state, plan)
    for meal in plan["meals"]:
        if meal["id"] in meal_ids or meal["status"] == "skipped":
            continue
        if not meal.get("included", True):
            continue
        for dish in meal_dishes(state, plan, meal):
            fixed.append({**dish, "day": meal["day"], "slot": meal["slot"]})
    blocked: dict[str, list[dict[str, str]]] = {}
    for meal in plan["meals"]:
        if meal["id"] not in meal_ids or not meal.get("day"):
            continue
        day = date.fromisoformat(meal["day"])
        seen: dict[str, dict[str, str]] = {}
        for record in fixed:
            difference = abs((day - date.fromisoformat(record["day"])).days)
            if 0 < difference <= gap:
                entry = {"dish": record["name"], "usedOn": record["day"]}
                if record.get("recipeId"):
                    entry["recipeId"] = record["recipeId"]
                seen.setdefault(record["name"], entry)
        if seen:
            blocked[meal["id"]] = sorted(seen.values(), key=lambda item: item["dish"])
    return blocked
