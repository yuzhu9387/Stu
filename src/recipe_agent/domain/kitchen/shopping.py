"""Ingredient arithmetic belongs to the service, not the language model."""

import re
import unicodedata
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo


def normalized(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


# Water and seasonings are in every kitchen, so they never go on the list.
PANTRY = frozenset(
    normalized(name)
    for name in (
        "水",
        "清水",
        "温水",
        "凉水",
        "冷水",
        "开水",
        "热水",
        "冰水",
        "盐",
        "食盐",
        "细盐",
        "海盐",
        "糖",
        "白糖",
        "白砂糖",
        "砂糖",
        "冰糖",
        "红糖",
        "油",
        "食用油",
        "植物油",
        "花生油",
        "菜籽油",
        "玉米油",
        "橄榄油",
        "香油",
        "芝麻油",
        "酱油",
        "生抽",
        "老抽",
        "蚝油",
        "醋",
        "白醋",
        "陈醋",
        "香醋",
        "米醋",
        "料酒",
        "黄酒",
        "胡椒粉",
        "白胡椒粉",
        "黑胡椒",
        "黑胡椒粉",
        "花椒",
        "八角",
        "桂皮",
        "香叶",
        "五香粉",
        "十三香",
        "孜然",
        "孜然粉",
        "淀粉",
        "玉米淀粉",
        "生粉",
        "鸡精",
        "味精",
        "番茄酱",
        "water",
        "salt",
        "sugar",
        "oil",
        "cooking oil",
        "vegetable oil",
        "olive oil",
        "sesame oil",
        "soy sauce",
        "light soy sauce",
        "dark soy sauce",
        "oyster sauce",
        "vinegar",
        "cooking wine",
        "pepper",
        "black pepper",
        "white pepper",
        "cornstarch",
        "starch",
        "msg",
        "ketchup",
    )
)
_SEASONING_GROUP = re.compile(r"调味|调料|seasoning|condiment|spice", re.IGNORECASE)


def pantry_staple(ingredient: dict[str, Any]) -> bool:
    """Water or a seasoning, by name or by the recipe's own group for it."""
    return normalized(ingredient["name"]) in PANTRY or bool(
        _SEASONING_GROUP.search(ingredient.get("group") or "")
    )


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
            for use in c.get("uses") or []:
                if use["inventoryId"] in balances:
                    key = use["inventoryId"]
                    balances[key] = max(0, balances[key] - use["portions"])
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

    def add_recipe(
        identifier: str | None, portions: float, name: str, have: frozenset[str] = frozenset()
    ) -> None:
        """Buy a recipe's ingredients, except those in `have` (already set aside)."""
        if portions <= 0:
            return
        recipe = recipes.get(identifier or "")
        if not recipe or not recipe["ingredients"]:
            warnings.append(f"{name}: add recipe ingredients.")
            return
        for ingredient in recipe["ingredients"]:
            if pantry_staple(ingredient) or normalized(ingredient["name"]) in have:
                continue
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
            # A dish cooked from fridge foods sets those foods aside; only the
            # rest of its recipe (flour, oil…) is bought.
            have: set[str] = set()
            for use in component.get("uses") or []:
                food = stock.get(use["inventoryId"])
                if food:
                    balances[food["id"]] = max(0, balances[food["id"]] - use["portions"])
                    have.update(normalized(n) for n in (food["name"], food.get("nameEn")) if n)
            if have and not component.get("recipeId"):
                continue
            add_recipe(
                component.get("recipeId")
                or (task or {}).get("recipeId")
                or stock.get(inventory_id, {}).get("recipeId"),
                need,
                component["name"],
                frozenset(have),
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
