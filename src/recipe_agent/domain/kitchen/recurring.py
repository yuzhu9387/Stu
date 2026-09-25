"""Weekly meal rules. Batch identities and consumed inventory never cross weeks."""

from copy import deepcopy
from datetime import date, timedelta
from typing import Any
from uuid import NAMESPACE_URL, uuid5


def key(meal: dict[str, Any]) -> tuple[int, str]:
    return date.fromisoformat(meal["day"]).weekday(), meal["slot"]


def apply_recurring(state: dict[str, Any], plan: dict[str, Any]) -> None:
    original = deepcopy(plan)
    changed_ids = set()
    for rule in state["settings"].get("recurringMeals", []):
        day = (date.fromisoformat(plan["weekStart"]) + timedelta(days=rule["weekday"])).isoformat()
        old = next(
            (m for m in plan["meals"] if m["day"] == day and m["slot"] == rule["slot"]), None
        )
        if old and (old["status"] != "planned" or old["locked"]):
            continue
        fresh = deepcopy(rule["meal"])
        fresh.update(
            id=old["id"]
            if old
            else str(uuid5(NAMESPACE_URL, f"{plan['id']}:{day}:{rule['slot']}")),
            day=day,
            status="planned",
            included=True,
            locked=True,
            liked=False,
        )
        tasks = deepcopy(rule["prep"])
        mapping = {
            t["id"]: str(
                uuid5(
                    NAMESPACE_URL,
                    f"recurring:{plan['id']}:{rule['weekday']}:{rule['slot']}:{t['id']}",
                )
            )
            for t in tasks
        }
        for task in tasks:
            needed = sum(
                c["portions"] for c in fresh["components"] if c.get("prepId") == task["id"]
            )
            if needed and task["plannedPortions"]:
                factor = needed / task["plannedPortions"]
                task["plannedPortions"] = needed
                task["activeMinutes"] *= factor
                task["elapsedMinutes"] *= factor
            task.update(
                id=mapping[task["id"]],
                status="planned",
                actualPortions=0,
                liked=False,
                inputs=[],
                dependencies=[mapping[d] for d in task["dependencies"] if d in mapping],
            )
            task.pop("outputInventoryId", None)
            if not any(t["id"] == task["id"] for t in plan["prep"]):
                plan["prep"].append(task)
        for c in fresh["components"]:
            c.pop("inventoryId", None)
            if c.get("prepId") in mapping:
                c["prepId"] = mapping[c["prepId"]]
            else:
                c.pop("prepId", None)
        changed_ids.add(fresh["id"])
        if old:
            old.clear()
            old.update(fresh)
        else:
            plan["meals"].append(fresh)

    from recipe_agent.domain.kitchen.engine import reconcile_prep
    from recipe_agent.domain.kitchen.scheduling import recompute_plan_timing

    if not changed_ids:
        return
    plan["prep"] = reconcile_prep(original, plan)
    # Locked dishes still need honest cooking/prep timing in their new week.
    if state.get("recipes") and "status" in plan:
        updated = recompute_plan_timing(state, plan)
        for meal in plan["meals"]:
            if meal["id"] in changed_ids:
                meal.update(next(m for m in updated["meals"] if m["id"] == meal["id"]))
        plan["prep"] = [
            next(t for t in updated["prep"] if t["id"] == task["id"])
            if task["status"] == "planned"
            else task
            for task in plan["prep"]
        ]


def toggle_recurring(
    state: dict[str, Any], plan: dict[str, Any], meal: dict[str, Any], locked: bool
) -> None:
    base = next((p for p in state["plans"] if p["id"] == plan.get("basePlanId")), None)
    current_base = base and plan.get("baseVersion") == base["version"]
    if base and not current_base:
        raise ValueError(
            "Confirmed plan changed; reconcile this draft before changing weekly locks"
        )
    weekday, slot = key(meal)
    rules = state["settings"].setdefault("recurringMeals", [])
    rules[:] = [r for r in rules if (r["weekday"], r["slot"]) != (weekday, slot)]
    if locked:
        if not meal.get("included", True):
            raise ValueError("Include this meal before locking it every week")
        ids = {c.get("prepId") for c in meal["components"]}
        # Dependencies must travel with the batch template as well.
        while True:
            expanded = ids | {d for t in plan["prep"] if t["id"] in ids for d in t["dependencies"]}
            if expanded == ids:
                break
            ids = expanded
        template = deepcopy(meal)
        for c in template["components"]:
            stock = next((i for i in state["inventory"] if i["id"] == c.get("inventoryId")), None)
            if not c.get("recipeId") and stock and stock.get("recipeId"):
                c["recipeId"] = stock["recipeId"]
        rules.append(
            {
                "weekday": weekday,
                "slot": slot,
                "meal": template,
                "prep": deepcopy([t for t in plan["prep"] if t["id"] in ids]),
            }
        )
    for p in state["plans"]:
        if p is plan:
            continue
        previous = deepcopy(p)
        changed = False
        for m in p["meals"]:
            if key(m) == (weekday, slot):
                m["locked"] = locked and m["status"] != "planned"
                if locked and p["weekStart"] == plan["weekStart"] and m["status"] == "planned":
                    identifier = m["id"]
                    m.clear()
                    m.update(deepcopy(meal))
                    m["id"] = identifier
                    # Versions within one week must protect the same meal and
                    # batch references. Only future weeks need new batch IDs.
                    for task in plan["prep"]:
                        if task["id"] not in ids:
                            continue
                        existing = next((t for t in p["prep"] if t["id"] == task["id"]), None)
                        if existing is None:
                            p["prep"].append(deepcopy(task))
                        elif existing["status"] == "planned":
                            existing.clear()
                            existing.update(deepcopy(task))
                changed = True
        if locked:
            apply_recurring(state, p)
        if changed:
            from recipe_agent.domain.kitchen.engine import reconcile_prep

            p["prep"] = reconcile_prep(previous, p)
            p["version"] += 1
            p.pop("fulfillment", None)
    if base and current_base:
        plan["baseVersion"] = base["version"]
