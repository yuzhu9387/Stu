"""Conservative, deterministic scheduling for one cook and exclusive equipment."""

from copy import deepcopy
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from math import ceil, isfinite
from typing import Any
from zoneinfo import ZoneInfo


def portion_batches(portions: float, servings: float) -> int:
    """Count batches from decimal quantities without binary-float boundary drift."""
    return max(1, ceil(Decimal(str(portions)) / Decimal(str(servings))))


def schedule_tasks(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    """Active work occupies one cook; equipment stays reserved through unattended tails.

    Tasks are indivisible active-then-wait segments. This deliberately conservative
    estimate never assumes an unrecorded opportunity to share an oven or a burner.
    """
    pending = {task["id"]: task for task in tasks}
    if len(pending) != len(tasks):
        raise ValueError("Duplicate timing task IDs")
    finished: dict[str, float] = {}
    resources: dict[str, float] = {}
    rows: list[dict[str, Any]] = []
    active_total = 0.0
    while pending:
        ready = [
            t for t in pending.values() if all(dep in finished for dep in t.get("dependencies", []))
        ]
        if not ready:
            raise ValueError("Timing dependencies are missing or cyclic")

        def earliest_start(candidate: dict[str, Any]) -> float:
            return max(
                [
                    resources.get("cook", 0) if candidate.get("activeMinutes") else 0,
                    *(finished[d] for d in candidate.get("dependencies", [])),
                    *(resources.get(f"equipment:{e}", 0) for e in candidate.get("equipment", [])),
                ]
            )

        # Equipment waiting must not idle the cook while another task can start.
        # min is stable, preserving the user's order among equally available work.
        task = min(ready, key=earliest_start)
        active, elapsed = task.get("activeMinutes"), task.get("elapsedMinutes")
        if (
            task.get("incomplete")
            or not isinstance(active, (int, float))
            or not isinstance(elapsed, (int, float))
            or not isfinite(active)
            or not isfinite(elapsed)
            or active < 0
            or elapsed < active
            or elapsed <= 0
        ):
            raise ValueError(f"Complete timing is required for {task.get('name', task['id'])}")
        equipment = set(task.get("equipment", []))
        start = earliest_start(task)
        if active:
            resources["cook"] = start + active
        finish = start + elapsed
        for device in equipment:
            resources[f"equipment:{device}"] = finish
        finished[task["id"]] = finish
        active_total += active
        rows.append(
            {
                "id": task["id"],
                "startMinutes": start,
                "activeEndMinutes": start + active,
                "finishMinutes": finish,
            }
        )
        del pending[task["id"]]
    elapsed = max(finished.values(), default=0)
    ordinary_elapsed = max(
        (finished[t["id"]] for t in tasks if t.get("type") != "Baking"), default=0
    )
    last_active_end = max(
        (r["activeEndMinutes"] for r in rows if r["activeEndMinutes"] > r["startMinutes"]),
        default=0,
    )
    return {
        "activeMinutes": active_total,
        "elapsedMinutes": elapsed,
        "ordinaryElapsedMinutes": ordinary_elapsed,
        "bakingWaitingMinutes": max(0, elapsed - max(ordinary_elapsed, last_active_end)),
        "tasks": rows,
    }


def recompute_plan_timing(state: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    """Recompute meal and prep time from recipes, without judging the plan.

    A household rule broken here (a repeat, a busy day, a long prep session, a
    dish with no recipe yet) is reported by `plan_rule_violations` and shown in
    the plan analysis; it does not stop the plan being saved or confirmed. A
    dish with no recipe keeps the minutes recorded on its meal.
    """
    result = deepcopy(plan)
    recipes = {r["id"]: r for r in state["recipes"]}
    inventory = {i["id"]: i for i in state["inventory"]}
    prep_ids = {p["id"] for p in plan["prep"]}
    for meal in result["meals"]:
        if not meal.get("included", True):
            # The household decided not to cook this slot, so it costs nothing.
            continue
        tasks = []
        for component in meal["components"]:
            # Ready stock/prep still requires the meal's recorded finishing work.
            if component.get("prepId") in prep_ids:
                continue
            stock = inventory.get(component.get("inventoryId"))
            if stock and stock.get("prepared"):
                continue
            recipe = recipes.get(component.get("recipeId"))
            if recipe is None:
                continue
            batches = portion_batches(component["portions"], recipe["servings"])
            tasks.append(
                {
                    **recipe,
                    "id": component["id"],
                    "dependencies": [],
                    "activeMinutes": recipe["activeMinutes"] * batches,
                    "elapsedMinutes": recipe["elapsedMinutes"] * batches,
                }
            )
        if tasks:
            schedule = schedule_tasks(tasks)
            meal["activeMinutes"] = max(meal["activeMinutes"], schedule["activeMinutes"])
            meal["elapsedMinutes"] = max(
                meal["elapsedMinutes"], schedule["elapsedMinutes"], meal["activeMinutes"]
            )
        else:
            schedule_tasks([{**meal, "name": meal["id"]}])
    for task in result["prep"]:
        recipe = recipes.get(task.get("recipeId"))
        if recipe:
            schedule_tasks([{**recipe, "dependencies": []}])
            batches = portion_batches(task["plannedPortions"], recipe["servings"])
            task["activeMinutes"] = max(task["activeMinutes"], recipe["activeMinutes"] * batches)
            task["elapsedMinutes"] = max(task["elapsedMinutes"], recipe["elapsedMinutes"] * batches)
            task["equipment"] = sorted(set(task["equipment"] + recipe.get("equipment", [])))
    schedule_tasks(result["prep"])
    return result


def plan_rule_violations(state: dict[str, Any], plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Every household rule the plan breaks, in a stable order.

    Kinds: "repeat" (a dish too soon again), "recipe" (a dish cooked fresh with
    no recipe, so its time is a guess), "daily" (a day over the cooking limit)
    and "prep" (prep over its limit). Each has a readable `message`.
    """
    from recipe_agent.domain.kitchen.repetition import repeat_conflicts, repeat_message

    violations: list[dict[str, Any]] = [
        {"kind": "repeat", "message": repeat_message(conflict), **conflict}
        for conflict in repeat_conflicts(state, plan)
    ]
    recipes = {r["id"] for r in state["recipes"]}
    inventory = {i["id"]: i for i in state["inventory"]}
    prep_ids = {p["id"] for p in plan["prep"]}
    daily: dict[str, float] = {}
    for meal in plan["meals"]:
        if not meal.get("included", True):
            continue
        for component in meal["components"]:
            stock = inventory.get(component.get("inventoryId"))
            ready = component.get("prepId") in prep_ids or (stock and stock.get("prepared"))
            if not ready and component.get("recipeId") not in recipes and not stock:
                violations.append(
                    {
                        "kind": "recipe",
                        "message": f"Recipe and timing required for {component['name']}",
                        "dish": component["name"],
                        "mealIds": [meal["id"]],
                    }
                )
        daily[meal["day"]] = daily.get(meal["day"], 0) + meal["activeMinutes"]
    limit = state["settings"]["maxDailyActiveMinutes"]
    for day, active in sorted(daily.items()):
        if active > limit:
            violations.append(
                {
                    "kind": "daily",
                    "message": f"{day} needs {active:g} active minutes; reduce daily cooking",
                    "day": day,
                    "minutes": active,
                    "limit": limit,
                }
            )
    prep = schedule_tasks(plan["prep"])
    prep_limit = state["settings"]["maxPrepMinutes"]
    if prep["ordinaryElapsedMinutes"] > prep_limit:
        violations.append(
            {
                "kind": "prep",
                "message": f"Ordinary prep needs {prep['ordinaryElapsedMinutes']:g} elapsed "
                "minutes; reduce prep",
                "minutes": prep["ordinaryElapsedMinutes"],
                "limit": prep_limit,
            }
        )
    if prep["activeMinutes"] > prep_limit:
        violations.append(
            {
                "kind": "prep",
                "message": f"Prep needs {prep['activeMinutes']:g} active minutes including "
                "baking; reduce prep",
                "minutes": prep["activeMinutes"],
                "limit": prep_limit,
            }
        )
    return violations


def validate_plan_timing(state: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    """Recompute timing and refuse the first broken rule (strict callers only)."""
    result = recompute_plan_timing(state, plan)
    violations = plan_rule_violations(state, result)
    if violations:
        raise ValueError(violations[0]["message"])
    return result


def due_week(now: datetime, settings: dict[str, Any]) -> str | None:
    """Friday's configured local time through Sunday catches up for next Monday."""
    if now.tzinfo is None:
        raise ValueError("Scheduler requires an aware UTC timestamp")
    local = now.astimezone(ZoneInfo(settings["timezone"]))
    monday = local.date() - timedelta(days=local.weekday())
    hour, minute = map(int, settings["generateTime"].split(":"))
    due = datetime.combine(monday + timedelta(days=4), time(hour, minute), local.tzinfo)
    if local < due:
        return None
    return (monday + timedelta(days=7)).isoformat()


def validate_week(value: str) -> date:
    day = date.fromisoformat(value)
    if day.weekday() != 0:
        raise ValueError("weekStart must be a Monday")
    return day
