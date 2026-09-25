"""Ingredient arithmetic belongs to the service, not the language model."""

import unicodedata
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo


def normalized(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def unit_amount(unit: str) -> tuple[str, float]:
    unit = normalized(unit)
    for names, canonical, factor in (
        ("g gram grams 克", "g", 1),
        ("kg kilogram kilograms 千克 公斤", "g", 1000),
        ("ml 毫升", "ml", 1),
        ("l liter liters 升", "ml", 1000),
        ("piece pieces pcs 个", "pcs", 1),
        ("portion portions 份", "portions", 1),
    ):
        if unit in names.split():
            return canonical, factor
    return unit, 1


def allocate_prep_inputs(
    state: dict[str, Any], plan: dict[str, Any], new_task_ids: set[str]
) -> None:
    """Reserve known raw amounts for new batches; execution consumes them later."""
    today = datetime.now(ZoneInfo(state["settings"]["timezone"])).date().isoformat()
    stock_date = max(today, plan["weekStart"])
    stock = {i["id"]: i for i in state["inventory"] if not i["prepared"]}
    balances = {
        key: 0 if i.get("expiresOn") and i["expiresOn"] < stock_date else i["portions"]
        for key, i in stock.items()
    }
    for meal in plan["meals"]:
        if meal["status"] != "planned" or not meal.get("included", True):
            continue
        for c in meal["components"]:
            if not c.get("prepId") and c.get("inventoryId") in balances:
                key = c["inventoryId"]
                balances[key] = max(0, balances[key] - c["portions"])
    for task in plan["prep"]:
        if task["id"] in new_task_ids or task["status"] != "planned":
            continue
        # Inventory edits can make an earlier reservation unavailable. Leave the
        # cooking instructions intact, and purchase the uncovered amount.
        inputs = []
        for entry in task["inputs"]:
            key = entry["inventoryId"]
            used = min(entry["portions"], balances.get(key, 0))
            if used:
                inputs.append({"inventoryId": key, "portions": used})
                balances[key] -= used
        task["inputs"] = inputs
    recipes = {r["id"]: r for r in state["recipes"]}
    for task in plan["prep"]:
        if task["id"] not in new_task_ids:
            continue
        recipe = recipes[task["recipeId"]]
        allocations: dict[str, float] = {}
        for ingredient in recipe["ingredients"]:
            if not ingredient.get("quantity") or not ingredient.get("unit"):
                continue
            unit, factor = unit_amount(ingredient["unit"])
            need = ingredient["quantity"] * factor * task["plannedPortions"] / recipe["servings"]
            for key, item in stock.items():
                if normalized(ingredient["name"]) not in {
                    normalized(item["name"]),
                    normalized(item.get("nameEn") or ""),
                }:
                    continue
                portion_size = (
                    item.get("portionGrams") if unit == "g" else 1 if unit == "portions" else 0
                )
                if not portion_size:
                    continue
                portions = min(balances[key], need / portion_size)
                if portions > 0:
                    allocations[key] = allocations.get(key, 0) + portions
                    balances[key] -= portions
                    need -= portions * portion_size
        task["inputs"] = [
            {"inventoryId": key, "portions": value} for key, value in allocations.items()
        ]


def shopping_list(
    state: dict[str, Any], plan: dict[str, Any], as_of: str | None = None
) -> tuple[list[dict[str, Any]], list[str]]:
    today = as_of or datetime.now(ZoneInfo(state["settings"]["timezone"])).date().isoformat()
    stock_date = max(today, plan["weekStart"])
    stock = {i["id"]: i for i in state["inventory"]}
    balances = {
        i["id"]: 0 if i.get("expiresOn") and i["expiresOn"] < stock_date else i["portions"]
        for i in stock.values()
    }
    recipes = {r["id"]: r for r in state["recipes"]}
    prep = {t["id"]: t for t in plan["prep"]}
    capacity = {t["id"]: t["plannedPortions"] for t in prep.values() if t["status"] == "planned"}
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    warnings: list[str] = []

    def add_recipe(identifier: str | None, portions: float, name: str) -> None:
        if portions <= 0:
            return
        recipe = recipes.get(identifier or "")
        if not recipe or not recipe["ingredients"]:
            warnings.append(f"{name}: add recipe ingredients.")
            return
        for ingredient in recipe["ingredients"]:
            if not ingredient.get("quantity") or not ingredient.get("unit", "").strip():
                warnings.append(f"{ingredient['name']} ({name}): check the recipe amount.")
                continue
            unit, factor = unit_amount(ingredient["unit"])
            key = (normalized(ingredient["name"]), unit)
            row = rows.setdefault(
                key,
                {
                    "name": ingredient["name"],
                    "unit": unit,
                    "group": ingredient.get("group") or "Other",
                    "required": 0,
                    "inStock": 0,
                    "toBuy": 0,
                    "dishes": [],
                },
            )
            row["required"] += ingredient["quantity"] * factor * portions / recipe["servings"]
            if name not in row["dishes"]:
                row["dishes"].append(name)

    for task in prep.values():
        if task["status"] == "planned":
            add_recipe(task.get("recipeId"), task["plannedPortions"], task["name"])
    for meal in sorted(plan["meals"], key=lambda m: (m["day"], m["slot"])):
        if not meal.get("included", True) or meal["status"] != "planned":
            continue
        for component in meal["components"]:
            need = component["portions"]
            task = prep.get(component.get("prepId"))
            inventory_id = component.get("inventoryId")
            if task and task["status"] == "planned":
                covered = min(need, capacity[task["id"]])
                need -= covered
                capacity[task["id"]] -= covered
                if need:
                    warnings.append(f"{task['name']}: prep is short by {need:g} portions.")
            else:
                if task and task["status"] == "completed":
                    inventory_id = task.get("outputInventoryId")
                stored = stock.get(inventory_id)
                if stored and (not stored.get("expiresOn") or stored["expiresOn"] >= meal["day"]):
                    used = min(need, balances[inventory_id])
                    balances[inventory_id] -= used
                    need -= used
            add_recipe(
                component.get("recipeId")
                or (task or {}).get("recipeId")
                or stock.get(inventory_id, {}).get("recipeId"),
                need,
                component["name"],
            )
    for (name, unit), row in rows.items():
        for item in stock.values():
            if item["prepared"] or name not in {
                normalized(item["name"]),
                normalized(item.get("nameEn") or ""),
            }:
                continue
            portions = balances[item["id"]]
            if portions <= 0 or row["inStock"] >= row["required"]:
                continue
            factor = item.get("portionGrams") if unit == "g" else 1 if unit == "portions" else None
            if not factor:
                warnings.append(
                    f"{item['name']}: {portions:g} portions in fridge; check the amount in {unit}."
                )
                continue
            used = min(row["required"] - row["inStock"], portions * factor)
            row["inStock"] += used
            balances[item["id"]] -= used / factor
            if row["group"] == "Other":
                row["group"] = item["type"]
        row["required"] = round(row["required"], 4)
        row["inStock"] = round(row["inStock"], 4)
        row["toBuy"] = round(max(0, row["required"] - row["inStock"]), 4)
    return list(rows.values()), list(dict.fromkeys(warnings))
