"""Pure validated commands; inventory ledger changes are all-or-nothing."""

from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from recipe_agent.domain.kitchen.contracts import (
    DEFAULT_PINNED_TAGS,
    ChatMessage,
    InventoryItem,
    KitchenCommand,
    KitchenSettings,
    KnowledgeDocument,
    Meal,
    MealStylePreset,
    PlanningWorkflow,
    PrepTask,
    Recipe,
    RecipeRating,
    WeeklyPlan,
    WeeklyPrompt,
    Workspace,
)


class KitchenError(ValueError):
    def __init__(self, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.status_code = status_code


def initial_state() -> dict[str, Any]:
    return Workspace().model_dump(mode="json", exclude_none=True)


def parse(model: type[BaseModel], value: Any) -> dict[str, Any]:
    return model.model_validate(value).model_dump(mode="json", exclude_none=True)


MEAL_SLOTS = ("breakfast", "lunch", "dinner")


def repin(state: dict[str, Any], change: Callable[[list[str]], list[str]]) -> None:
    """Apply `change` to the pinned tags, saving them only when they change.
    Pins never chosen are the defaults, so the first change starts from those
    the household has (the meals always; a default tag only if it exists)."""
    current = state["settings"].get("pinnedTags")
    pins = (
        [pin for pin in DEFAULT_PINNED_TAGS if pin in MEAL_SLOTS or pin in state["tags"]]
        if current is None
        else current
    )
    changed = list(dict.fromkeys(change(pins)))
    if changed != pins:
        state["settings"]["pinnedTags"] = changed


def find(items: list[dict[str, Any]], identifier: str) -> dict[str, Any]:
    result = next((item for item in items if item["id"] == identifier), None)
    if result is None:
        raise KitchenError(f"Unknown record: {identifier}")
    return result


def upsert(items: list[dict[str, Any]], value: dict[str, Any]) -> None:
    old = next((item for item in items if item["id"] == value["id"]), None)
    if old is not None:
        items[items.index(old)] = value
    else:
        items.append(value)


def remember_workflow(state: dict[str, Any], week: str, workflow: dict[str, Any]) -> None:
    entry = next((p for p in state["weeklyPrompts"] if p["weekStart"] == week), None)
    if entry is None:
        entry = parse(WeeklyPrompt, {"weekStart": week, "prompt": ""})
        state["weeklyPrompts"].append(entry)
    entry["workflow"] = workflow


def structural(value: dict[str, Any]) -> dict[str, Any]:
    return {key: val for key, val in value.items() if key != "liked"}


def validate_references(state: dict[str, Any]) -> None:
    recipes = {item["id"] for item in state["recipes"]}
    inventory = {item["id"] for item in state["inventory"]}
    for item in state["inventory"]:
        if item.get("recipeId") and item["recipeId"] not in recipes:
            raise KitchenError("Inventory references an unknown recipe")
    for plan in state["plans"]:
        prep_ids = {item["id"] for item in plan["prep"]}
        for task in plan["prep"]:
            # A finished task may have no box: a quick task makes none, and a
            # box can be taken out of the fridge after the dish was made.
            if (
                task["status"] == "completed"
                and task.get("outputInventoryId")
                and task["outputInventoryId"] not in inventory
            ):
                raise KitchenError("Completed prep references missing output inventory")
            if task.get("recipeId") and task["recipeId"] not in recipes:
                raise KitchenError("Prep references an unknown recipe")
            if any(i["inventoryId"] not in inventory for i in task["inputs"]):
                raise KitchenError("Prep references missing inventory")
            if any(dep not in prep_ids or dep == task["id"] for dep in task["dependencies"]):
                raise KitchenError("Invalid prep dependency")
        pending = {task["id"]: set(task["dependencies"]) for task in plan["prep"]}
        finished: set[str] = set()
        while pending:
            ready = [identifier for identifier, deps in pending.items() if deps <= finished]
            if not ready:
                raise KitchenError("Prep dependencies are cyclic")
            for identifier in ready:
                finished.add(identifier)
                del pending[identifier]
        for meal in plan["meals"]:
            for component in meal["components"]:
                for key, available in [
                    ("recipeId", recipes),
                    ("inventoryId", inventory),
                    ("prepId", prep_ids),
                ]:
                    if component.get(key) and component[key] not in available:
                        raise KitchenError(f"{component['name']}: unknown {key}")
                selected = None
                if component.get("inventoryId"):
                    selected = find(state["inventory"], component["inventoryId"])
                    if (
                        component.get("recipeId")
                        and selected.get("recipeId") != component["recipeId"]
                    ):
                        raise KitchenError("Selected inventory belongs to a different recipe")
                if component.get("prepId"):
                    task = find(plan["prep"], component["prepId"])
                    output = task.get("outputInventoryId") or f"prep-{task['id']}"
                    if selected and selected["id"] != output:
                        raise KitchenError("Selected inventory belongs to a different prep output")
                    if component.get("recipeId") and task.get("recipeId") != component["recipeId"]:
                        raise KitchenError("Selected prep belongs to a different recipe")


def share_food_attributes(state: dict[str, Any], saved: dict[str, Any]) -> None:
    """Icon and English name describe the food, not one batch of it.

    Two tubs of 鸡蛋 are the same food, so naming or re-iconing one has to reach
    the other; otherwise the fridge shows the same item two different ways.
    Only values actually supplied propagate, so saving a batch that omits them
    never clears what another batch established.
    """
    name = saved["name"].casefold()
    shared = {key: saved[key] for key in ("emoji", "nameEn") if saved.get(key) is not None}
    if not shared:
        return
    for item in state["inventory"]:
        if item["id"] != saved["id"] and item["name"].casefold() == name:
            item.update(shared)


def consume(state: dict[str, Any], component: dict[str, Any], deltas: list[dict[str, Any]]) -> None:
    remaining = component["portions"]
    if component.get("inventoryId"):
        candidates = [find(state["inventory"], component["inventoryId"])]
    else:
        candidates = [
            item
            for item in state["inventory"]
            if (
                item.get("recipeId") == component.get("recipeId")
                if component.get("recipeId")
                else item["name"].casefold() == component["name"].casefold()
            )
        ]
        candidates.sort(key=lambda item: (item["addedOn"], item["id"]))
    for item in candidates:
        used = min(remaining, item["portions"])
        item["portions"] -= used
        remaining -= used
        if used:
            deltas.append({"inventoryId": item["id"], "amount": -used})
    if remaining > 1e-8:
        raise KitchenError(
            f"Insufficient stock for {component.get('name', component.get('inventoryId'))}: "
            f"missing {remaining:g} portions"
        )


def storage_location(value: str) -> str:
    """The fridge's own compartments are stored as the tables store them."""
    value = value.strip()
    return value.casefold() if value.casefold() in {"fridge", "freezer", "pantry"} else value


def add_output(
    state: dict[str, Any], task: dict[str, Any], amount: float, deltas: list[dict[str, Any]]
) -> None:
    # A quick task (no recipe, nothing to make, e.g. thawing meat) yields no food.
    if not task.get("recipeId") and amount == 0 and not task.get("outputInventoryId"):
        return
    identifier = task.get("outputInventoryId") or f"prep-{task['id']}"
    item = next((i for i in state["inventory"] if i["id"] == identifier), None)
    if item is None:
        item = {
            "id": identifier,
            "name": task["name"],
            "type": ("Carbs" if task["type"] == "Baking" else task["type"]),
            "portions": 0,
            # Batch-cooked dishes keep for the week in the freezer by default.
            "location": "freezer",
            "prepared": True,
            "addedOn": datetime.now(UTC).date().isoformat(),
            "priority": False,
        }
        if task.get("recipeId"):
            item["recipeId"] = task["recipeId"]
        state["inventory"].append(item)
    elif item["name"] != task["name"] or item.get("recipeId") != task.get("recipeId"):
        raise KitchenError("Prep output does not match the selected inventory batch")
    elif item["portions"] == 0:
        # An empty box refilled by batch cooking goes to the freezer, like a new one.
        item["location"] = "freezer"
    item["portions"] += amount
    task["outputInventoryId"] = identifier
    deltas.append({"inventoryId": identifier, "amount": amount})


def remove_inventory(state: dict[str, Any], item: dict[str, Any]) -> None:
    """Take a box out of the fridge.

    A box still needed (a meal still to eat, or prep still to cook, uses it)
    stays, with the reason. Finished meals and prep, and plans for days gone
    by, only remember where their food came from, so they let go of it and
    keep the rest of their record.
    """
    identifier = item["id"]
    today = datetime.now(ZoneInfo(state["settings"].get("timezone", "UTC"))).date()
    for plan in state["plans"]:
        tasks = {task["id"]: task for task in plan["prep"]}
        week_over = date.fromisoformat(plan["weekStart"]) + timedelta(days=7) <= today
        for meal in plan["meals"]:
            if meal["status"] != "planned" or date.fromisoformat(meal["day"]) < today:
                continue
            for component in meal["components"]:
                task = tasks.get(component.get("prepId") or "")
                made_here = (
                    task is not None
                    and task["status"] == "completed"
                    and task.get("outputInventoryId") == identifier
                )
                if component.get("inventoryId") == identifier or made_here:
                    weekday = date.fromisoformat(meal["day"]).strftime("%a")
                    raise KitchenError(
                        f"{item['name']} is planned for {weekday} {meal['slot']}. "
                        "Replace it in that meal first."
                    )
        for task in plan["prep"]:
            if (
                task["status"] == "planned"
                and not week_over
                and any(i["inventoryId"] == identifier for i in task["inputs"])
            ):
                raise KitchenError(
                    f"{item['name']} is needed to cook {task['name']}. Change that prep first."
                )
    for plan in state["plans"]:
        for meal in plan["meals"]:
            for component in meal["components"]:
                if component.get("inventoryId") == identifier:
                    component.pop("inventoryId")
        for task in plan["prep"]:
            task["inputs"] = [i for i in task["inputs"] if i["inventoryId"] != identifier]
            if task.get("outputInventoryId") == identifier:
                task.pop("outputInventoryId")
    state["inventory"].remove(item)


def inventory_references(state: dict[str, Any]) -> set[str]:
    """Inventory ids that meals, prep inputs or finished prep point at. A planned
    task's output id names a box still to be made, so it does not count."""
    return {
        *(
            component["inventoryId"]
            for plan in state["plans"]
            for meal in plan["meals"]
            for component in meal["components"]
            if component.get("inventoryId")
        ),
        *(
            ingredient["inventoryId"]
            for plan in state["plans"]
            for task in plan["prep"]
            for ingredient in task["inputs"]
        ),
        *(
            task["outputInventoryId"]
            for plan in state["plans"]
            for task in plan["prep"]
            if task.get("outputInventoryId") and task["status"] == "completed"
        ),
    }


def check_meal_allergies(meal: dict[str, Any], allergies: list[str]) -> None:
    """Check available dish text even before it has a saved recipe."""
    haystack = " ".join(
        [*(component["name"] for component in meal["components"]), *meal["steps"]]
    ).casefold()
    for allergy in allergies:
        if allergy.strip() and allergy.casefold() in haystack:
            raise KitchenError(f"Meal conflicts with allergy: {allergy}")


def check_confirmation(
    state: dict[str, Any], plan: dict[str, Any], *, check_stock: bool = True
) -> None:
    from recipe_agent.domain.kitchen.scheduling import recompute_plan_timing

    allergies = {value.casefold() for value in state["settings"]["allergies"]}
    for meal in plan["meals"]:
        check_meal_allergies(meal, state["settings"]["allergies"])
    referenced = {
        component.get("recipeId") for meal in plan["meals"] for component in meal["components"]
    }
    referenced.update(task.get("recipeId") for task in plan["prep"])
    for recipe in state["recipes"]:
        haystack = " ".join(
            [
                recipe["name"],
                *recipe.get("allergens", []),
                *(item["name"] for item in recipe["ingredients"]),
            ]
        ).casefold()
        if recipe["id"] in referenced and any(value and value in haystack for value in allergies):
            raise KitchenError(f"Allergy conflict: {recipe['name']}")
    inventory_ids = {
        component.get("inventoryId") for meal in plan["meals"] for component in meal["components"]
    }
    inventory_ids.update(
        ingredient["inventoryId"] for task in plan["prep"] for ingredient in task["inputs"]
    )
    for stock in state["inventory"]:
        if stock["id"] in inventory_ids and any(
            value and value in stock["name"].casefold() for value in allergies
        ):
            raise KitchenError(f"Allergy conflict: {stock['name']}")
    recomputed = recompute_plan_timing(state, plan)
    recomputed["meals"] = [
        meal
        if meal["status"] != "planned" or meal["locked"]
        else find(recomputed["meals"], meal["id"])
        for meal in plan["meals"]
    ]
    recomputed["prep"] = [
        task if task["status"] != "planned" else find(recomputed["prep"], task["id"])
        for task in plan["prep"]
    ]
    plan.update(recomputed)
    # With check_stock, fridge demand is projected across every confirmed week
    # and a plan that uses stock that will not be there is refused. Generation
    # keeps that on: an AI plan claiming fridge food the household does not have
    # is a planning error. A household confirming its own week turns it off —
    # whatever the week needs beyond the fridge is prepared on prep day, so a
    # shortage is a prep need, not a reason to refuse the plan. The structural
    # checks (prep that can never run, meals waiting on skipped prep) always run.
    projected = deepcopy(state)
    reserved = (
        [
            other
            for other in projected["plans"]
            if other["status"] == "confirmed"
            and other["id"] not in {plan["id"], plan.get("basePlanId")}
        ]
        if check_stock
        else []
    )
    reserved.append(deepcopy(plan))
    for reserved_plan in sorted(reserved, key=lambda value: value["weekStart"]):
        pending = {
            task["id"]: task for task in reserved_plan["prep"] if task["status"] == "planned"
        }
        done = {task["id"] for task in reserved_plan["prep"] if task["status"] == "completed"}
        while pending:
            ready = [task for task in pending.values() if set(task["dependencies"]) <= done]
            if not ready:
                raise KitchenError("Planned prep depends on skipped or cyclic tasks")
            for task in ready:
                if check_stock:
                    for ingredient in task["inputs"]:
                        consume(projected, ingredient, [])
                    add_output(projected, task, task["plannedPortions"], [])
                done.add(task["id"])
                del pending[task["id"]]
        for meal in sorted(reserved_plan["meals"], key=lambda value: value["day"]):
            if meal["status"] == "planned" and meal.get("included", True):
                for component in meal["components"]:
                    component = deepcopy(component)
                    if component.get("prepId"):
                        prep = find(reserved_plan["prep"], component["prepId"])
                        if prep["status"] == "skipped":
                            raise KitchenError(f"Meal depends on skipped prep: {prep['name']}")
                        component["inventoryId"] = (
                            prep.get("outputInventoryId") or f"prep-{prep['id']}"
                        )
                    # A recipe-only component is fresh cooking, not an allocation
                    # against a coincidentally matching leftover batch.
                    if check_stock and component.get("inventoryId"):
                        consume(projected, component, [])


def reconcile_prep(original: dict[str, Any], candidate: dict[str, Any]) -> list[dict[str, Any]]:
    """Adjust only previously allocated, unexecuted batches when meal demand changes.

    Preserve intentional standalone prep, completed/skipped records, and batches
    needed by dependent tasks. All quantities remain in the same portion basis.
    """

    def demand(plan: dict[str, Any]) -> dict[str, float]:
        amounts: dict[str, float] = {}
        for meal in plan["meals"]:
            if meal["status"] == "skipped":
                continue
            for component in meal["components"]:
                identifier = component.get("prepId")
                if identifier:
                    amounts[identifier] = amounts.get(identifier, 0) + component["portions"]
        return amounts

    before, after = demand(original), demand(candidate)
    prerequisites = {dep for task in candidate["prep"] for dep in task["dependencies"]}
    tasks = []
    for source in candidate["prep"]:
        task = deepcopy(source)
        identifier = task["id"]
        if (
            task["status"] == "planned"
            and before.get(identifier)
            and identifier not in prerequisites
        ):
            required = after.get(identifier, 0)
            if required == 0:
                continue
            if required != before[identifier]:
                scale = required / before[identifier]
                task["plannedPortions"] *= scale
                task["activeMinutes"] *= scale
                task["elapsedMinutes"] *= scale
                for ingredient in task["inputs"]:
                    ingredient["portions"] *= scale
        tasks.append(task)
    return tasks


def apply_command(state: dict[str, Any], command: dict[str, Any], actor_id: str) -> dict[str, Any]:
    command = parse(KitchenCommand, command)
    state = parse(Workspace, deepcopy(state))
    if command["expectedRevision"] != state["revision"]:
        raise KitchenError("Workspace changed; refresh before applying this change", 409)
    kind, payload = command["type"], command["payload"]
    deltas: list[dict[str, Any]] = []
    undo: dict[str, Any] | None = None
    message = "Changes saved"
    audit_context = {}
    prep_change: dict[str, Any] = {}
    stocked = {item["id"] for item in state["inventory"]}
    if kind in {"recipe.save", "inventory.save"}:
        key, model, collection = (
            ("recipe", Recipe, "recipes")
            if kind == "recipe.save"
            else ("item", InventoryItem, "inventory")
        )
        saved = parse(model, payload[key])
        upsert(state[collection], saved)
        if kind == "inventory.save":
            share_food_attributes(state, saved)
    elif kind == "inventory.receive":
        # What was bought comes home: each item is a new batch, once. A batch
        # already recorded (the same shopping line received twice) is left as is.
        items = payload.get("items")
        if not isinstance(items, list) or not items or len(items) > 200:
            raise KitchenError("Choose what you bought")
        known = {item["id"] for item in state["inventory"]}
        added = 0
        for raw in items:
            saved = parse(InventoryItem, raw)
            if saved["id"] in known:
                continue
            saved["location"] = storage_location(saved["location"])
            state["inventory"].append(saved)
            known.add(saved["id"])
            share_food_attributes(state, saved)
            added += 1
        message = f"Added {added} item{'' if added == 1 else 's'} to the fridge"
    elif kind == "inventory.arrange":
        # Boxes dragged around the fridge: the whole new order, plus any box
        # that changed compartment. Only where things sit changes, never how
        # much there is.
        order, moves = payload.get("order"), payload.get("moves") or []
        current = [item["id"] for item in state["inventory"]]
        if (
            not isinstance(order, list)
            or len(order) != len(current)
            or set(order) != set(current)
            or not isinstance(moves, list)
        ):
            raise KitchenError("Arrange every item in the fridge exactly once")
        by_id = {item["id"]: item for item in state["inventory"]}
        for move in moves:
            location = move.get("location") if isinstance(move, dict) else None
            if (
                not isinstance(location, str)
                or not location.strip()
                or len(location) > 60
                or move.get("id") not in by_id
            ):
                raise KitchenError("Choose an item and where it goes")
            by_id[move["id"]]["location"] = storage_location(location)
        state["inventory"] = [by_id[identifier] for identifier in order]
        message = "Fridge arranged"
    elif kind == "inventory.delete":
        remove_inventory(state, find(state["inventory"], payload["id"]))
        message = "Removed from the fridge"
    elif kind == "recipe.delete":
        state["recipes"].remove(find(state["recipes"], payload["id"]))
        state["recipeRatings"] = [
            entry for entry in state["recipeRatings"] if entry["recipeId"] != payload["id"]
        ]
    elif kind == "recipe.rate":
        find(state["recipes"], payload["recipeId"])
        stars = payload["stars"]
        if stars is None:
            state["recipeRatings"] = [
                entry
                for entry in state["recipeRatings"]
                if not (
                    entry["recipeId"] == payload["recipeId"] and entry["accountId"] == str(actor_id)
                )
            ]
            message = "Rating removed"
        else:
            rating = parse(
                RecipeRating,
                {
                    "recipeId": payload["recipeId"],
                    "accountId": str(actor_id),
                    "stars": stars,
                },
            )
            # One rating per person per recipe; the average is counted from
            # these rows and is never stored as a total.
            state["recipeRatings"] = [
                entry
                for entry in state["recipeRatings"]
                if not (
                    entry["recipeId"] == rating["recipeId"]
                    and entry["accountId"] == rating["accountId"]
                )
            ] + [rating]
            message = "Rating saved"
    elif kind == "knowledge.save":
        document = payload["document"]
        if not isinstance(document, dict):
            raise KitchenError("Document must be an object")
        old_document = next(
            (entry for entry in state["knowledgeDocuments"] if entry["id"] == document.get("id")),
            None,
        )
        if (
            old_document
            and "version" in document
            and document["version"] != old_document["version"]
        ):
            raise KitchenError("This document changed; reload it before saving edits", 409)
        saved = parse(
            KnowledgeDocument,
            {
                **document,
                "version": old_document["version"] + 1 if old_document else 1,
                "updatedAt": datetime.now(UTC).isoformat(),
            },
        )
        upsert(state["knowledgeDocuments"], saved)
        message = "Knowledge document saved; future planning uses enabled documents"
    elif kind == "knowledge.delete":
        state["knowledgeDocuments"].remove(find(state["knowledgeDocuments"], payload["id"]))
        message = "Knowledge document deleted; existing plan snapshots are preserved"
    elif kind == "tag.save":
        name = str(payload["name"]).strip()
        if not name or len(name) > 100:
            raise KitchenError("Tag must contain 1-100 characters")
        previous = payload.get("previous")
        if previous:
            state["tags"] = [tag for tag in state["tags"] if tag != previous]
            for recipe in state["recipes"]:
                recipe["tags"] = list(
                    dict.fromkeys(name if t == previous else t for t in recipe["tags"])
                )
            # A renamed (or merged) tag keeps its pin under the new name.
            repin(state, lambda pins: [name if pin == previous else pin for pin in pins])
        state["tags"] = list(dict.fromkeys([*state["tags"], name]))
    elif kind == "tag.apply":
        name = str(payload["name"]).strip()
        if not name or len(name) > 100:
            raise KitchenError("Tag must contain 1-100 characters")
        if not isinstance(payload.get("remove", False), bool):
            raise KitchenError("remove must be boolean")
        identifiers = payload["recipeIds"]
        if not isinstance(identifiers, list) or not identifiers:
            raise KitchenError("Select at least one recipe")
        recipes = [find(state["recipes"], identifier) for identifier in identifiers]
        for recipe in recipes:
            recipe["tags"] = [tag for tag in recipe["tags"] if tag != name]
            if not payload.get("remove", False):
                recipe["tags"].append(name)
        if not payload.get("remove", False):
            state["tags"] = list(dict.fromkeys([*state["tags"], name]))
    elif kind == "tag.delete":
        state["tags"] = [tag for tag in state["tags"] if tag != payload["name"]]
        for recipe in state["recipes"]:
            recipe["tags"] = [tag for tag in recipe["tags"] if tag != payload["name"]]
        repin(state, lambda pins: [pin for pin in pins if pin != payload["name"]])
    elif kind == "tag.pin":
        # A meal is pinned by its slot ("breakfast"); any other tag by its name.
        name = str(payload["name"]).strip()
        if not isinstance(payload.get("pinned"), bool):
            raise KitchenError("pinned must be boolean")
        if name not in MEAL_SLOTS and name not in state["tags"]:
            raise KitchenError(f"Unknown tag: {name}")
        pinned = payload["pinned"]
        repin(state, lambda pins: [*[p for p in pins if p != name], *([name] if pinned else [])])
        message = f"{name} pinned" if pinned else f"{name} unpinned"
    elif kind == "settings.save":
        state["settings"] = parse(KitchenSettings, payload["settings"])
    elif kind == "planning.prompt":
        entry = parse(WeeklyPrompt, payload)
        saved_prompt: dict[str, Any] = next(
            (p for p in state["weeklyPrompts"] if p["weekStart"] == entry["weekStart"]), {}
        )
        if saved_prompt.get("workflow"):
            entry["workflow"] = saved_prompt["workflow"]
        state["weeklyPrompts"] = [
            item for item in state["weeklyPrompts"] if item["weekStart"] != entry["weekStart"]
        ] + [entry]
        message = "Weekly preferences saved for scheduled planning"
    elif kind == "planning.workflow":
        workflow = parse(PlanningWorkflow, payload["workflow"])
        plan = find(state["plans"], workflow["planId"]) if workflow.get("planId") else None
        if plan and plan["weekStart"] != payload["weekStart"]:
            raise KitchenError("The workflow and plan must belong to the same week")
        step = workflow["step"]
        if (not plan and step != "preferences") or (
            plan
            and (
                (plan["status"] == "draft" and step not in {"preferences", "adjust"})
                or (plan["status"] == "confirmed" and step not in {"confirmed", "shopping"})
            )
        ):
            raise KitchenError("This step is not available for the current plan")
        remember_workflow(state, payload["weekStart"], workflow)
        message = "Planning progress saved"
    elif kind == "shopping.check":
        plan = find(state["plans"], payload["planId"])
        if plan["status"] != "confirmed":
            raise KitchenError("Confirm the plan before shopping")
        # One item ("key") or several at once ("keys", e.g. "Mark all picked up").
        chosen = payload["keys"] if "keys" in payload else [payload.get("key")]
        checked = payload.get("checked")
        if (
            not isinstance(chosen, list)
            or not chosen
            or len(chosen) > 500
            or any(not isinstance(k, str) or not k.strip() or len(k) > 1000 for k in chosen)
            or not isinstance(checked, bool)
        ):
            raise KitchenError("Choose a shopping item and a checked state")
        chosen = list(dict.fromkeys(chosen))
        keys = [k for k in plan["shoppingChecked"] if k not in chosen]
        plan["shoppingChecked"] = keys + (chosen if checked else [])
        message = "Shopping checklist saved"
    elif kind == "plan.save":
        plan = parse(WeeklyPlan, payload["plan"])
        if plan["status"] != "draft":
            raise KitchenError("Save a draft first, then confirm it")
        old = next((p for p in state["plans"] if p["id"] == plan["id"]), None)
        if old and old["status"] == "confirmed":
            raise KitchenError("Create a separate draft based on the confirmed plan")
        baseline = find(state["plans"], plan["basePlanId"]) if plan.get("basePlanId") else old
        if baseline and baseline["weekStart"] != plan["weekStart"]:
            raise KitchenError("A plan and its baseline must refer to the same week")
        if plan.get("basePlanId") and (
            baseline is None
            or baseline["status"] != "confirmed"
            or plan.get("baseVersion") != baseline["version"]
        ):
            raise KitchenError("Confirmed plan changed; reconcile the draft", 409)
        if baseline:
            for meal in baseline["meals"]:
                if (meal["locked"] or meal["status"] != "planned") and (
                    find(plan["meals"], meal["id"]) != meal
                ):
                    raise KitchenError("Locked or executed meals must be preserved")
            for task in baseline["prep"]:
                if task["status"] != "planned" and find(plan["prep"], task["id"]) != task:
                    raise KitchenError("Executed prep must be preserved")
        if any(
            m["status"] != "planned"
            and (not baseline or not any(old_m == m for old_m in baseline["meals"]))
            for m in plan["meals"]
        ) or any(
            p["status"] != "planned"
            and (not baseline or not any(old_p == p for old_p in baseline["prep"]))
            for p in plan["prep"]
        ):
            raise KitchenError("Execution must be recorded through status commands")
        if not baseline and (
            any(m["status"] != "planned" for m in plan["meals"])
            or any(p["status"] != "planned" for p in plan["prep"])
        ):
            raise KitchenError("New plans cannot contain executed meals or prep")
        for recipe in payload.get("recipes", []):
            parsed = parse(Recipe, recipe)
            if any(r["id"] == parsed["id"] and r != parsed for r in state["recipes"]):
                raise KitchenError("Save recipe edits separately before generating a plan")
            upsert(state["recipes"], parsed)
        if "knowledgeSnapshot" not in payload["plan"]:
            plan["knowledgeSnapshot"] = deepcopy(
                baseline.get("knowledgeSnapshot", [])
                if baseline
                else [entry for entry in state["knowledgeDocuments"] if entry["enabled"]]
            )
        if "guidanceSnapshot" not in payload["plan"]:
            plan["guidanceSnapshot"] = deepcopy(
                baseline.get("guidanceSnapshot", [])
                if baseline
                else [entry for entry in state["settings"]["guidance"] if entry["enabled"]]
            )
        from recipe_agent.domain.kitchen.recurring import apply_recurring

        apply_recurring(state, plan)
        plan.pop("fulfillment", None)
        if baseline and baseline.get("fulfillment"):
            plan["fulfillment"] = {**deepcopy(baseline["fulfillment"]), "stale": True}
        plan["version"] = old["version"] + 1 if old else 1
        upsert(state["plans"], plan)
        if not old:
            remember_workflow(
                state,
                plan["weekStart"],
                {"planId": plan["id"], "step": "adjust", "focus": "shopping"},
            )
    elif kind in {"plan.confirm", "plan.fulfill"}:
        plan = find(state["plans"], payload["id"])
        if plan["status"] == "confirmed":
            raise KitchenError("Plan is already confirmed")
        existing = [
            p
            for p in state["plans"]
            if p["status"] == "confirmed" and p["weekStart"] == plan["weekStart"]
        ]
        if existing:
            base = existing[0]
            if base["id"] != plan.get("basePlanId") or base["version"] != plan.get("baseVersion"):
                raise KitchenError("Confirmed plan changed; regenerate or reconcile the draft", 409)
        if kind == "plan.fulfill":
            from recipe_agent.domain.kitchen.fulfillment import attach_fulfillment, inputs_hash
            from recipe_agent.domain.kitchen.scheduling import recompute_plan_timing

            if inputs_hash(state, plan) != payload["inputHash"]:
                raise KitchenError("Menu, recipes or fridge changed; confirm again", 409)
            attach_fulfillment(state, plan, payload["output"])
            timed = recompute_plan_timing(state, plan)
            plan["meals"] = [
                meal
                if meal["status"] != "planned" or meal["locked"]
                else find(timed["meals"], meal["id"])
                for meal in plan["meals"]
            ]
            plan["prep"] = [
                task if task["status"] != "planned" else find(timed["prep"], task["id"])
                for task in plan["prep"]
            ]
        check_confirmation(state, plan, check_stock=False)
        for base in existing:
            base["status"] = "draft"
            base["version"] += 1
        plan["status"] = "confirmed"
        plan["version"] += 1
        remember_workflow(
            state,
            plan["weekStart"],
            {"planId": plan["id"], "step": "shopping", "focus": "shopping"},
        )
        message = "Plan confirmed; stock is unchanged"
    elif kind == "plan.presets":
        plan = find(state["plans"], payload["planId"])
        keys = payload["keys"]
        if not isinstance(keys, list) or any(not isinstance(key, str) for key in keys):
            raise KitchenError("Preset keys must be a list of strings")
        known = {preset["key"] for preset in state["mealStylePresets"]}
        unknown = [key for key in keys if key not in known]
        if unknown:
            raise KitchenError(f"Unknown meal style preset: {', '.join(sorted(unknown))}")
        plan["presets"] = list(dict.fromkeys(keys))
        plan["version"] += 1
        message = "Meal styles saved for this week"
    elif kind == "preset.save":
        preset = parse(MealStylePreset, payload["preset"])
        old = next(
            (item for item in state["mealStylePresets"] if item["key"] == preset["key"]),
            None,
        )
        if old is None:
            state["mealStylePresets"].append(preset)
        else:
            state["mealStylePresets"][state["mealStylePresets"].index(old)] = preset
    elif kind == "plan.chat":
        plan = find(state["plans"], payload["planId"])
        for value in payload["messages"]:
            entry = parse(ChatMessage, value)
            for meal_id in entry["mealIds"]:
                find(plan["meals"], meal_id)
            plan["chat"].append(entry)
    elif kind.startswith(("meal.", "prep.")):
        plan = find(state["plans"], payload["planId"])
        original_plan = deepcopy(plan)
        category, action = kind.split(".")
        collection = "meals" if category == "meal" else "prep"
        identifier = payload[category]["id"] if action == "save" else payload[f"{category}Id"]
        entity = next((item for item in plan[collection] if item["id"] == identifier), None)
        created = entity is None and action == "save"
        if entity is None and not created:
            raise KitchenError(f"Unknown record: {identifier}")
        before = deepcopy(entity)
        if entity is None:
            entity = {}
        if action == "include" and category == "meal":
            if entity["locked"]:
                raise KitchenError("Unlock this weekly meal before excluding it")
            if not isinstance(payload["included"], bool):
                raise KitchenError("Invalid flag")
            if entity["status"] != "planned":
                raise KitchenError("Undo the execution before excluding this meal")
            entity["included"] = payload["included"]
            from recipe_agent.domain.kitchen.scheduling import recompute_plan_timing

            plan.update(recompute_plan_timing(state, plan))
            message = (
                "Slot added back to the week"
                if payload["included"]
                else "Slot excluded; it no longer uses time or stock"
            )
        elif action in {"like", "lock"}:
            key = "liked" if action == "like" else "locked"
            if not isinstance(payload[key], bool) or (category == "prep" and action == "lock"):
                raise KitchenError("Invalid flag")
            entity[key] = payload[key]
            if action == "lock":
                from recipe_agent.domain.kitchen.recurring import toggle_recurring

                toggle_recurring(state, plan, entity, payload[key])
                message = "Meal locked every week" if payload[key] else "Weekly meal unlocked"
        elif action == "save":
            for recipe in payload.get("recipes", []):
                parsed = parse(Recipe, recipe)
                if any(r["id"] == parsed["id"] for r in state["recipes"]):
                    raise KitchenError("Save existing recipe edits separately")
                upsert(state["recipes"], parsed)
                state["tags"] = list(dict.fromkeys([*state["tags"], *parsed["tags"]]))
            candidate = parse(Meal if category == "meal" else PrepTask, payload[category])
            if not created and (entity.get("locked") or entity["status"] != "planned"):
                raise KitchenError("Unlock or undo execution before editing this record")
            if candidate["status"] != "planned" or candidate.get("locked", False):
                raise KitchenError("Use the status and lock commands")
            if category == "prep" and candidate["actualPortions"] != 0:
                raise KitchenError("Actual output must be recorded through completion")
            if created:
                entity = candidate
                plan[collection].append(entity)
            else:
                entity.clear()
                entity.update(candidate)
            from recipe_agent.domain.kitchen.scheduling import recompute_plan_timing

            if category == "meal":
                plan["prep"] = reconcile_prep(original_plan, plan)
            recomputed = recompute_plan_timing(state, plan)
            plan["prep"] = recomputed["prep"]
            if plan["prep"] != original_plan["prep"]:
                prep_change = {
                    "prepBefore": original_plan["prep"],
                    "prepAfter": deepcopy(plan["prep"]),
                }
            entity.update(find(recomputed[collection], entity["id"]))
        elif action == "delete":
            if entity.get("locked") or entity["status"] != "planned":
                raise KitchenError("Unlock or undo execution before deleting this record")
            plan[collection].remove(entity)
        elif action == "leftovers" and category == "meal":
            if plan["status"] != "confirmed" or entity["status"] != "completed":
                raise KitchenError("Record leftovers after completing this meal")
            component = find(entity["components"], payload["componentId"])
            amount = payload["portions"]
            if (
                isinstance(amount, bool)
                or not isinstance(amount, (int, float))
                or not 0 < amount < float("inf")
            ):
                raise KitchenError("Leftover portions must be positive and finite")
            returned = sum(
                sum(d["amount"] for d in audit["deltas"])
                for audit in state["audit"]
                if audit["kind"] == "meal.leftovers"
                and not audit["undone"]
                and audit.get("planId") == plan["id"]
                and audit.get("entityId") == identifier
                and audit.get("componentId") == component["id"]
            )
            if amount + returned > component["portions"] + 1e-8:
                raise KitchenError("Leftovers exceed this meal component's prepared portions")
            output = {"id": str(uuid4()), "name": component["name"], "type": component["type"]}
            recipe_id = component.get("recipeId")
            if not recipe_id and component.get("inventoryId"):
                recipe_id = find(state["inventory"], component["inventoryId"]).get("recipeId")
            if not recipe_id and component.get("prepId"):
                recipe_id = find(plan["prep"], component["prepId"]).get("recipeId")
            if recipe_id:
                output["recipeId"] = recipe_id
            add_output(state, output, amount, deltas)
            location = payload.get("location", "fridge")
            if not isinstance(location, str) or not location.strip():
                raise KitchenError("Location must be nonempty text")
            find(state["inventory"], output["outputInventoryId"])["location"] = location
            audit_context = {
                "planId": plan["id"],
                "entityId": identifier,
                "componentId": component["id"],
            }
            message = "Leftovers added to fridge"
        elif action == "status":
            if plan["status"] != "confirmed":
                raise KitchenError("Only a confirmed plan can be executed")
            status = payload["status"]
            if status not in {"planned", "completed", "skipped"}:
                raise KitchenError("Invalid execution status")
            if status != entity["status"]:
                if entity["status"] != "planned" or status == "planned":
                    raise KitchenError("Undo the previous execution first")
                if status == "completed":
                    if category == "meal":
                        for component in entity["components"]:
                            selected = deepcopy(component)
                            if component.get("prepId"):
                                task = find(plan["prep"], component["prepId"])
                                if task["status"] != "completed":
                                    raise KitchenError(f"Prep is not complete: {task['name']}")
                                if not task.get("outputInventoryId"):
                                    raise KitchenError(f"{task['name']} is no longer in the fridge")
                                selected["inventoryId"] = task["outputInventoryId"]
                            if selected.get("inventoryId"):
                                consume(state, selected, deltas)
                    else:
                        for dependency in entity["dependencies"]:
                            if find(plan["prep"], dependency)["status"] != "completed":
                                raise KitchenError("Complete prerequisite prep first")
                        amount = payload.get("actualPortions", entity["plannedPortions"])
                        if not isinstance(amount, (int, float)) or not 0 <= amount < float("inf"):
                            raise KitchenError("Actual portions must be finite and nonnegative")
                        for ingredient in entity["inputs"]:
                            consume(state, ingredient, deltas)
                        add_output(state, entity, amount, deltas)
                        entity["actualPortions"] = amount
                entity["status"] = status
        else:
            raise KitchenError("Unknown command")
        if (
            action in {"save", "status"} and before != entity and not created
        ) or action == "leftovers":
            undo = {
                "planId": plan["id"],
                "collection": collection,
                "entityId": identifier,
                "before": before,
                "after": deepcopy(entity),
                **prep_change,
                "balances": {
                    d["inventoryId"]: find(state["inventory"], d["inventoryId"])["portions"]
                    for d in deltas
                },
                "inventoryAfter": {
                    d["inventoryId"]: deepcopy(find(state["inventory"], d["inventoryId"]))
                    for d in deltas
                },
            }
            # Boxes this action brought into the fridge, which an undo takes away.
            if new_boxes := list(
                dict.fromkeys(d["inventoryId"] for d in deltas if d["inventoryId"] not in stocked)
            ):
                undo["created"] = new_boxes
        plan["version"] += 1
    elif kind == "change.undo":
        audit = find(state["audit"], payload["auditId"])
        target = audit.get("undo")
        if not target or audit["undone"]:
            raise KitchenError("This change cannot be undone")
        plan = find(state["plans"], target["planId"])
        if audit["kind"] in {"meal.status", "prep.status"} and plan["status"] != "confirmed":
            raise KitchenError("This plan was superseded; execution undo is no longer safe", 409)
        entity = find(plan[target["collection"]], target["entityId"])
        if structural(entity) != structural(target["after"]):
            raise KitchenError("This record changed after that action; undo is unsafe", 409)
        if "prepAfter" in target:
            if [structural(t) for t in plan["prep"]] != [
                structural(t) for t in target["prepAfter"]
            ]:
                raise KitchenError("Related prep changed after that action; undo is unsafe", 409)
            likes = {task["id"]: task["liked"] for task in plan["prep"]}
            plan["prep"] = deepcopy(target["prepBefore"])
            for task in plan["prep"]:
                task["liked"] = likes.get(task["id"], task["liked"])
        touched = set(target["balances"])
        for later in state["audit"][state["audit"].index(audit) + 1 :]:
            if (
                not later["undone"]
                and later["kind"] == "meal.leftovers"
                and later.get("planId") == target["planId"]
                and later.get("entityId") == target["entityId"]
            ):
                raise KitchenError("Undo recorded leftovers before undoing this meal", 409)
            if not later["undone"] and any(d["inventoryId"] in touched for d in later["deltas"]):
                raise KitchenError("Dependent stock activity prevents undo", 409)
        on_hand = {item["id"]: item for item in state["inventory"]}
        for identifier, snapshot in target.get("inventoryAfter", {}).items():
            if on_hand.get(identifier) != snapshot:
                raise KitchenError("Stock changed after that action; undo is unsafe", 409)
        for identifier, balance in target["balances"].items():
            if identifier not in on_hand or on_hand[identifier]["portions"] != balance:
                raise KitchenError("Stock changed after that action; undo is unsafe", 409)
        created = set(target.get("created", []))
        emptied: set[str] = set()
        for delta in audit["deltas"]:
            item = find(state["inventory"], delta["inventoryId"])
            item["portions"] -= delta["amount"]
            if item["portions"] < 0:
                raise KitchenError("Output has already been consumed")
            if item["id"] in created and item["portions"] == 0:
                emptied.add(item["id"])
                continue
            deltas.append({"inventoryId": item["id"], "amount": -delta["amount"]})
        liked = entity["liked"]
        entity.clear()
        entity.update(deepcopy(target["before"]))
        entity["liked"] = liked
        # A box that action brought into the fridge leaves with it (an undone
        # "done" leaves no empty box behind), unless something now points at it.
        emptied -= inventory_references(state)
        state["inventory"] = [item for item in state["inventory"] if item["id"] not in emptied]
        # Reinstating skipped meals can conflict with dishes added after the skip.
        # Validate before committing the restored entity, ledger or audit marker.
        if audit["kind"] == "meal.save":
            from recipe_agent.domain.kitchen.scheduling import recompute_plan_timing

            recomputed = recompute_plan_timing(state, plan)
            entity.update(find(recomputed["meals"], entity["id"]))
        plan["version"] += 1
        audit["undone"] = True
        message = "Change undone"
    else:
        raise KitchenError("Unknown command")
    validate_references(state)
    state["revision"] += 1
    state["audit"].append(
        {
            "id": str(uuid4()),
            "kind": kind,
            "message": message,
            "at": datetime.now(UTC).isoformat(),
            "actorId": str(actor_id),
            "operationId": command["operationId"],
            "deltas": deltas,
            "undo": undo,
            "undone": False,
            **audit_context,
        }
    )
    # A confirmed list is a snapshot. Material changes make the live ingredient
    # projection authoritative again until the next AI confirmation.
    if deltas or kind in {
        "recipe.save",
        "recipe.delete",
        "inventory.save",
        "inventory.delete",
        "settings.save",
        "change.undo",
    }:
        for changed_plan in state["plans"]:
            if changed_plan.get("fulfillment"):
                changed_plan["fulfillment"]["stale"] = True
    elif kind in {
        "meal.save",
        "meal.include",
        "meal.delete",
        "meal.lock",
        "meal.status",
        "meal.leftovers",
        "prep.save",
        "prep.delete",
        "prep.status",
    }:
        changed_plan = find(state["plans"], payload["planId"])
        if changed_plan.get("fulfillment"):
            changed_plan["fulfillment"]["stale"] = True
    return {"state": parse(Workspace, state), "message": message}
