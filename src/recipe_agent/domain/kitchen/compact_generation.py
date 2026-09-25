"""Compile compact AI menus into ordinary plans without guessing cooking work."""

from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal
from typing import Annotated, Any, Literal, Self

from pydantic import Field, model_validator

from recipe_agent.domain.kitchen.contracts import Contract, Identifier, Number, Recipe
from recipe_agent.domain.kitchen.scheduling import portion_batches


class CompactComponent(Contract):
    source: Literal["fresh", "prep", "inventory"]
    recipeId: Identifier | None = None
    inventoryId: Identifier | None = None
    portions: Annotated[float, Field(gt=0, allow_inf_nan=False, strict=True)]

    @model_validator(mode="after")
    def require_source(self) -> Self:
        if self.source == "inventory":
            if not self.inventoryId:
                raise ValueError("Inventory components require inventoryId")
        elif not self.recipeId or self.inventoryId:
            raise ValueError("Fresh/prep components require recipeId and no inventoryId")
        return self


class MealTemplate(Contract):
    id: Identifier
    components: list[CompactComponent] = Field(min_length=1, max_length=8)
    activeMinutes: Number
    elapsedMinutes: Number
    steps: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def valid_work(self) -> Self:
        if self.elapsedMinutes <= 0 or self.elapsedMinutes < self.activeMinutes:
            raise ValueError("Meal finishing elapsed time must be positive and cover active time")
        if any(not step.strip() for step in self.steps):
            raise ValueError("Meal finishing steps cannot be empty")
        return self


class DayAssignment(Contract):
    breakfast: Identifier
    lunch: Identifier
    dinner: Identifier


class CompactPrepInput(Contract):
    recipeId: Identifier
    inventoryId: Identifier
    portions: Annotated[float, Field(gt=0, allow_inf_nan=False, strict=True)]


class GeneratedRecipe(Recipe):
    # A new AI recipe has no user feedback yet. Missing UI bookkeeping must not
    # trigger another expensive full-week request.
    liked: Literal[False] = False


class CompactGeneration(Contract):
    recipes: list[GeneratedRecipe] = Field(max_length=21)
    # One template per slot at most; a cap below 21 only threw good weeks away.
    mealTemplates: list[MealTemplate] = Field(min_length=1, max_length=21)
    days: list[DayAssignment] = Field(min_length=7, max_length=7)
    prepInputs: list[CompactPrepInput] = Field(default_factory=list, max_length=100)


def batch_steps(recipe: dict[str, Any], batches: int, planned: float) -> list[str]:
    per_batch = "; ".join(
        f"{item['quantity']:g} {item['unit']} {item['name']}" for item in recipe["ingredients"]
    )
    total = "; ".join(
        f"{float(Decimal(str(item['quantity'])) * batches):g} {item['unit']} {item['name']}"
        for item in recipe["ingredients"]
    )
    yield_total = float(Decimal(str(recipe["servings"])) * batches)
    return [
        f"Make {batches} {'batch' if batches == 1 else 'batches'}: "
        f"{recipe['servings']:g} portions per batch, {yield_total:g} portions total "
        f"({planned:g} planned for these meals). Record the actual portions produced "
        "when marking prep complete, including extras.",
        f"Ingredients for EACH recipe batch: {per_batch}.",
        f"Total ingredients for all batches: {total}.",
        "Repeat the following recipe steps for each batch:",
        *deepcopy(recipe["steps"]),
    ]


def compile_generation(
    state: dict[str, Any], raw: dict[str, Any], week_start: str
) -> dict[str, Any]:
    """Expand references and sum demand; preserve recipe yield, steps and time verbatim.

    A repeated prep recipe creates one batch task. Its conservative batch count
    uses the same recipe serving/time math as the existing plan validator.
    """
    output = CompactGeneration.model_validate(raw).model_dump(mode="json", exclude_none=True)
    identifiers = [template["id"] for template in output["mealTemplates"]]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("Duplicate meal template IDs")
    recipes = {recipe["id"]: recipe for recipe in [*state["recipes"], *output["recipes"]]}
    inventory = {item["id"]: item for item in state["inventory"]}
    templates = {template["id"]: template for template in output["mealTemplates"]}
    prep_demand: dict[str, Decimal] = {}
    prep_ids: dict[str, str] = {}
    meals = []
    monday = date.fromisoformat(week_start)
    for offset, assignment in enumerate(output["days"]):
        for slot in ("breakfast", "lunch", "dinner"):
            template_id = assignment[slot]
            if template_id not in templates:
                raise ValueError(f"Unknown meal template: {template_id}")
            template = templates[template_id]
            meal_id = f"meal-{offset}-{slot}"
            components = []
            for index, source in enumerate(template["components"]):
                recipe_id = source.get("recipeId")
                record = recipes.get(recipe_id)
                component: dict[str, Any] = {
                    "id": f"{meal_id}-component-{index}",
                    "portions": source["portions"],
                }
                if source["source"] == "inventory":
                    stock = inventory.get(source["inventoryId"])
                    if stock is None:
                        raise ValueError(f"Unknown inventory: {source['inventoryId']}")
                    record = stock
                    component["inventoryId"] = stock["id"]
                    recipe_id = recipe_id or stock.get("recipeId")
                    if recipe_id and recipe_id not in recipes:
                        raise ValueError(f"Unknown recipe: {recipe_id}")
                elif record is None:
                    raise ValueError(f"Unknown recipe: {recipe_id}")
                elif source["source"] == "prep":
                    prep_id = prep_ids.setdefault(recipe_id, f"batch-{len(prep_ids)}")
                    component["prepId"] = prep_id
                    prep_demand[recipe_id] = prep_demand.get(recipe_id, Decimal(0)) + Decimal(
                        str(source["portions"])
                    )
                component.update(name=record["name"], type=record["type"])
                if recipe_id:
                    component["recipeId"] = recipe_id
                components.append(component)
            meals.append(
                {
                    "id": meal_id,
                    "day": (monday + timedelta(days=offset)).isoformat(),
                    "slot": slot,
                    "components": components,
                    "activeMinutes": template["activeMinutes"],
                    "elapsedMinutes": template["elapsedMinutes"],
                    "steps": deepcopy(template["steps"]),
                    "status": "planned",
                    "liked": False,
                    "locked": False,
                }
            )
    prep_inputs: dict[str, list[dict[str, Any]]] = {}
    for allocation in output["prepInputs"]:
        if allocation["recipeId"] not in prep_demand:
            raise ValueError(f"Unknown prep recipe: {allocation['recipeId']}")
        if allocation["inventoryId"] not in inventory:
            raise ValueError(f"Unknown inventory: {allocation['inventoryId']}")
        prep_inputs.setdefault(allocation["recipeId"], []).append(
            {"inventoryId": allocation["inventoryId"], "portions": allocation["portions"]}
        )
    prep = []
    for recipe_id, demand in prep_demand.items():
        amount = float(demand)
        recipe = recipes[recipe_id]
        batches = portion_batches(amount, recipe["servings"])
        baking = recipe["type"] == "Carbs" and any(
            tag.casefold() in {"baking", "烘焙"} for tag in recipe["tags"]
        )
        prep.append(
            {
                "id": prep_ids[recipe_id],
                "name": recipe["name"],
                "type": "Baking" if baking else recipe["type"],
                "recipeId": recipe_id,
                "plannedPortions": amount,
                "actualPortions": 0,
                "activeMinutes": recipe["activeMinutes"] * batches,
                "elapsedMinutes": recipe["elapsedMinutes"] * batches,
                "steps": batch_steps(recipe, batches, amount),
                "status": "planned",
                "liked": False,
                "inputs": prep_inputs.get(recipe_id, []),
                "equipment": deepcopy(recipe.get("equipment", [])),
                "dependencies": [],
            }
        )
    return {
        "recipes": output["recipes"],
        "plan": {
            "id": "generated",
            "weekStart": week_start,
            "status": "draft",
            "version": 1,
            "prompt": "",
            "meals": meals,
            "prep": prep,
            "chat": [],
        },
    }


def drop_unused_recipes(raw: dict[str, Any]) -> dict[str, Any]:
    """New recipes nothing uses are left out (models add placeholders).

    An unused, incomplete "placeholder" recipe would otherwise fail a week
    whose meals are all fine.
    """
    if not isinstance(raw.get("recipes"), list) or not isinstance(raw.get("mealTemplates"), list):
        return raw
    used = {
        component.get("recipeId")
        for template in raw["mealTemplates"]
        if isinstance(template, dict)
        for component in template.get("components", [])
        if isinstance(component, dict)
    } | {item.get("recipeId") for item in raw.get("prepInputs", []) if isinstance(item, dict)}
    return {
        **raw,
        "recipes": [r for r in raw["recipes"] if isinstance(r, dict) and r.get("id") in used],
    }


SLOTS = ("breakfast", "lunch", "dinner")


def arrange_days(
    state: dict[str, Any],
    raw: dict[str, Any],
    week_start: str,
    fixed: list[dict[str, Any]] | None = None,
    *,
    budget: int = 60000,
) -> dict[str, Any]:
    """Reorder which template each day gets so no dish lands too close to itself.

    A model picks a good set of meals but often puts one on consecutive days,
    or piles fresh cooking onto one day. Keeping every slot's templates (all
    breakfasts stay breakfasts), this searches for an order that respects the
    repeat gap — against the week itself, the neighbouring weeks and `fixed`
    meals that stay ({day, keys}) — with every day inside the daily cooking
    limit. When no order fits the limit, the heaviest fresh dishes move to the
    weekend prep batch (as the planning rules prefer) and the search runs
    again; failing that, the repeats alone are fixed so validation reports the
    real problem. The model's own order is tried first.
    """
    from collections import Counter

    from recipe_agent.domain.kitchen.repetition import adjacent_history, meal_dishes
    from recipe_agent.domain.kitchen.scheduling import schedule_tasks

    try:
        output = CompactGeneration.model_validate(raw).model_dump(mode="json", exclude_none=True)
    except ValueError:
        return raw
    templates = {template["id"]: template for template in output["mealTemplates"]}
    if any(day[slot] not in templates for day in output["days"] for slot in SLOTS):
        return raw
    recipes = {recipe["id"]: recipe for recipe in [*state["recipes"], *output["recipes"]]}
    inventory = {item["id"]: item for item in state["inventory"]}
    gap = state["settings"].get("recipeRepeatGapDays", 1)
    limit = state["settings"]["maxDailyActiveMinutes"]
    lookup = {**state, "recipes": list(recipes.values())}

    def fresh_recipe(source: dict[str, Any]) -> dict[str, Any] | None:
        stock = inventory.get(source.get("inventoryId") or "")
        cooks = source["source"] == "fresh" or (
            source["source"] == "inventory" and stock is not None and not stock.get("prepared")
        )
        recipe_id = source.get("recipeId") or (stock or {}).get("recipeId")
        return recipes.get(recipe_id or "") if cooks else None

    def template_cost(template: dict[str, Any]) -> float:
        tasks = []
        for index, source in enumerate(template["components"]):
            recipe = fresh_recipe(source)
            if recipe:
                batches = portion_batches(source["portions"], recipe["servings"])
                tasks.append(
                    {
                        **recipe,
                        "id": f"{template['id']}-{index}",
                        "dependencies": [],
                        "activeMinutes": recipe["activeMinutes"] * batches,
                        "elapsedMinutes": recipe["elapsedMinutes"] * batches,
                    }
                )
        work = schedule_tasks(tasks)["activeMinutes"] if tasks else 0
        return float(max(template["activeMinutes"], work))

    keys: dict[str, set[str]] = {}
    for template_id, template in templates.items():
        components = []
        for index, source in enumerate(template["components"]):
            stock = inventory.get(source.get("inventoryId") or "")
            recipe_id = source.get("recipeId") or (stock or {}).get("recipeId")
            record = recipes.get(recipe_id or "") or stock or {}
            components.append(
                {
                    "id": f"{template_id}-{index}",
                    "name": record.get("name", template_id),
                    "type": record.get("type", "Other"),
                    "portions": source["portions"],
                    **({"recipeId": recipe_id} if recipe_id else {}),
                    **({"inventoryId": stock["id"]} if stock else {}),
                }
            )
        keys[template_id] = {
            key
            for dish in meal_dishes(lookup, {"prep": []}, {"components": components})
            for key in dish["keys"]
        }
    monday = date.fromisoformat(week_start)
    outside = [
        {"offset": (date.fromisoformat(record["day"]) - monday).days, "keys": record["keys"]}
        for record in [*adjacent_history(state, {"weekStart": week_start}), *(fixed or [])]
    ]
    original = [tuple(day[slot] for slot in SLOTS) for day in output["days"]]

    def arrange(cost: dict[str, float] | None, free: bool) -> list[tuple[str, ...]] | None:
        """With `free`, a day may take any of the slot's templates, not just the
        ones left over; templates still owed days are preferred."""
        remaining = [Counter(day[slot] for day in output["days"]) for slot in SLOTS]
        menu = [sorted(column) for column in remaining]
        chosen: list[tuple[str, ...]] = []
        nodes = 0

        def fits(offset: int, combo: tuple[str, ...]) -> bool:
            if cost is not None and sum(cost[template] for template in combo) > limit:
                return False
            dishes = set().union(*(keys[template] for template in combo))
            for back in range(1, gap + 1):
                if offset - back >= 0 and dishes & set().union(
                    *(keys[t] for t in chosen[offset - back])
                ):
                    return False
            return not any(
                0 < abs(offset - record["offset"]) <= gap and dishes & record["keys"]
                for record in outside
            )

        def search(offset: int) -> bool:
            nonlocal nodes
            if offset == 7:
                return True
            options = [
                (breakfast, lunch, dinner)
                for breakfast in menu[0]
                if free or remaining[0][breakfast] > 0
                for lunch in menu[1]
                if free or remaining[1][lunch] > 0
                for dinner in menu[2]
                if free or remaining[2][dinner] > 0
            ]
            options.sort(
                key=lambda combo: (
                    combo != original[offset],
                    -sum(
                        min(column[template], 1)
                        for column, template in zip(remaining, combo, strict=True)
                    ),
                    combo,
                )
            )
            for combo in options:
                nodes += 1
                if nodes > budget:
                    return False
                if not fits(offset, combo):
                    continue
                for column, template in zip(remaining, combo, strict=True):
                    column[template] -= 1
                chosen.append(combo)
                if search(offset + 1):
                    return True
                chosen.pop()
                for column, template in zip(remaining, combo, strict=True):
                    column[template] += 1
            return False

        return chosen if search(0) else None

    def result(order: list[tuple[str, ...]]) -> dict[str, Any]:
        arranged = deepcopy(raw)
        arranged["mealTemplates"] = list(templates.values())
        arranged["days"] = [dict(zip(SLOTS, combo, strict=True)) for combo in order]
        return arranged

    def attempt(with_cost: bool) -> list[tuple[str, ...]] | None:
        cost = {t: template_cost(templates[t]) for t in templates} if with_cost else None
        return arrange(cost, free=False) or arrange(cost, free=True)

    used = {template for combo in original for template in combo}
    as_given = deepcopy(templates)
    while True:
        order = attempt(True)
        if order is not None:
            return result(order)
        # Move the heaviest fresh dish still cooked on the day to the weekend batch.
        heaviest = max(
            (
                (recipe["activeMinutes"], template_id, index)
                for template_id in used
                for index, source in enumerate(templates[template_id]["components"])
                if source["source"] == "fresh" and (recipe := fresh_recipe(source))
            ),
            default=None,
        )
        if heaviest is None:
            break
        _, template_id, index = heaviest
        templates[template_id] = deepcopy(templates[template_id])
        templates[template_id]["components"][index]["source"] = "prep"
    # No order meets the time limit: undo the prep moves and fix the repeats
    # alone, so validation reports the time problem (or keeps the closest week).
    templates.clear()
    templates.update(as_given)
    order = attempt(False)
    return result(order) if order is not None else raw
