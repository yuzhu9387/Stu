"""Project the aggregate's recipe and tag sections onto the normalised tables.

Phase B group 1 of the cutover. Rather than translating each command, this
reconciles the tables with whatever state `apply_command` produced. Any command
that touches recipes or tags — including `plan.save` carrying new AI recipes —
keeps the tables correct without its own translation, and there is one place to
audit instead of five.

Food items and equipment are only ever created, never removed: they are shared
vocabulary that inventory batches and prep tasks still reference.

Design: docs/superpowers/specs/2026-09-20-relational-schema.md
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from recipe_agent.domain.identity.models import Account
from recipe_agent.domain.kitchen import schema as s
from recipe_agent.domain.kitchen.contracts import ANALYSIS_METRICS

FOOD_CATEGORY = {
    "Protein": s.FoodCategory.PROTEIN,
    "Carbs": s.FoodCategory.CARBS,
    "Vegetables": s.FoodCategory.VEGETABLES,
    "Dairy": s.FoodCategory.DAIRY,
    "Other": s.FoodCategory.OTHER,
}


def _dec(value: Any, default: str = "0") -> Decimal:
    return Decimal(str(value)) if value is not None else Decimal(default)


class VocabularyCache:
    """Create-only lookup for food and equipment, flushed as rows are added."""

    def __init__(self, session: AsyncSession, household_id: UUID) -> None:
        self.session = session
        self.household_id = household_id
        self.food: dict[str, s.FoodItem] = {}
        self.equipment: dict[str, s.Equipment] = {}

    async def prime(self) -> None:
        for food in (
            await self.session.scalars(
                select(s.FoodItem).where(s.FoodItem.household_id == self.household_id)
            )
        ).all():
            self.food[food.name] = food
        for tool in (
            await self.session.scalars(
                select(s.Equipment).where(s.Equipment.household_id == self.household_id)
            )
        ).all():
            self.equipment[tool.name] = tool

    async def food_item(self, name: str, category: str | None = None) -> s.FoodItem:
        key = name.strip()
        mapped = FOOD_CATEGORY.get(category or "", s.FoodCategory.OTHER)
        existing = self.food.get(key)
        if existing is not None:
            if existing.category == s.FoodCategory.OTHER and mapped != s.FoodCategory.OTHER:
                existing.category = mapped
            return existing
        item = s.FoodItem(
            id=uuid4(), household_id=self.household_id, name=key, category=mapped
        )
        self.session.add(item)
        await self.session.flush()
        self.food[key] = item
        return item

    async def equipment_item(self, name: str) -> s.Equipment:
        key = name.strip()
        existing = self.equipment.get(key)
        if existing is not None:
            return existing
        item = s.Equipment(id=uuid4(), household_id=self.household_id, name=key)
        self.session.add(item)
        await self.session.flush()
        self.equipment[key] = item
        return item


async def project_recipes_and_tags(
    session: AsyncSession, household_id: UUID, state: dict[str, Any]
) -> None:
    """Make the recipe and tag tables match `state`, additively for vocabulary."""
    vocabulary = VocabularyCache(session, household_id)
    await vocabulary.prime()
    tags = await _project_tags(session, household_id, state)
    await _project_recipes(session, household_id, state, tags, vocabulary)


async def _project_tags(
    session: AsyncSession, household_id: UUID, state: dict[str, Any]
) -> dict[str, s.Tag]:
    listed = [str(name).strip() for name in state.get("tags") or []]
    used = {
        str(name).strip()
        for recipe in state.get("recipes") or []
        for name in recipe.get("tags") or []
    }
    wanted = list(dict.fromkeys([*listed, *sorted(used - set(listed))]))
    rows = {
        row.name: row
        for row in (
            await session.scalars(select(s.Tag).where(s.Tag.household_id == household_id))
        ).all()
    }
    for name in set(rows) - set(wanted):
        # Link rows cascade, so a removed tag leaves recipes intact.
        await session.execute(delete(s.Tag).where(s.Tag.id == rows.pop(name).id))
    for position, name in enumerate(wanted):
        row = rows.get(name)
        if row is None:
            row = s.Tag(
                id=uuid4(),
                household_id=household_id,
                name=name,
                listed=name in listed,
                position=position,
            )
            session.add(row)
            rows[name] = row
        else:
            row.listed = name in listed
            row.position = position
    await session.flush()
    return rows


async def _project_recipes(
    session: AsyncSession,
    household_id: UUID,
    state: dict[str, Any],
    tags: dict[str, s.Tag],
    vocabulary: VocabularyCache,
) -> None:
    incoming = {str(recipe["id"]): recipe for recipe in state.get("recipes") or []}
    existing = {
        row.legacy_id or str(row.id): row
        for row in (
            await session.scalars(
                select(s.KitchenRecipe).where(s.KitchenRecipe.household_id == household_id)
            )
        ).all()
    }
    for legacy_id in set(existing) - set(incoming):
        # Children cascade; inventory, meals and prep keep their rows with a
        # null recipe reference, matching the aggregate's own behaviour.
        await session.execute(
            delete(s.KitchenRecipe).where(s.KitchenRecipe.id == existing[legacy_id].id)
        )
    await session.flush()

    for position, (legacy_id, raw) in enumerate(incoming.items()):
        source = str(raw.get("source") or "")
        is_url = source.startswith(("http://", "https://"))
        row = existing.get(legacy_id)
        if row is None:
            row = s.KitchenRecipe(id=uuid4(), household_id=household_id, legacy_id=legacy_id)
            session.add(row)
        row.name = raw["name"]
        row.category = FOOD_CATEGORY.get(raw.get("type", ""), s.FoodCategory.OTHER)
        row.servings = _dec(raw["servings"], "1")
        row.active_minutes = _dec(raw["activeMinutes"])
        row.elapsed_minutes = _dec(raw["elapsedMinutes"])
        row.is_favorite = bool(raw.get("liked"))
        row.incomplete = bool(raw.get("incomplete"))
        row.source_text = None if is_url else (source or None)
        row.source_url = source if is_url else None
        row.name_en = raw.get("nameEn")
        row.cuisine = raw.get("cuisine")
        row.difficulty = raw.get("difficulty")
        row.hero_image_url = raw.get("heroImageUrl")
        row.position = position
        await session.flush()
        await _replace_children(session, row, raw, tags, vocabulary)
    await session.flush()


async def _project_nutrition(
    session: AsyncSession, row: s.KitchenRecipe, raw: dict[str, Any] | None
) -> None:
    """Absent means unknown; the row is removed rather than zero-filled."""
    existing = await session.get(s.RecipeNutrition, row.id)
    if raw is None:
        if existing is not None:
            await session.execute(
                delete(s.RecipeNutrition).where(s.RecipeNutrition.recipe_id == row.id)
            )
        return
    if existing is None:
        existing = s.RecipeNutrition(recipe_id=row.id)
        session.add(existing)
    for field, column in (
        ("calories", "calories"),
        ("proteinG", "protein_g"),
        ("carbsG", "carbs_g"),
        ("fatG", "fat_g"),
        ("fiberG", "fiber_g"),
    ):
        value = raw.get(field)
        setattr(existing, column, _dec(value) if value is not None else None)
    existing.source = raw.get("source", "unknown")
    await session.flush()


async def project_recipe_ratings(
    session: AsyncSession, household_id: UUID, state: dict[str, Any]
) -> None:
    recipes = {
        row.legacy_id or str(row.id): row.id
        for row in (
            await session.scalars(
                select(s.KitchenRecipe).where(s.KitchenRecipe.household_id == household_id)
            )
        ).all()
    }
    await session.execute(
        delete(s.KitchenRecipeRating).where(
            s.KitchenRecipeRating.recipe_id.in_(list(recipes.values()) or [None])
        )
    )
    await session.flush()
    for raw in state.get("recipeRatings") or []:
        recipe_id = recipes.get(str(raw["recipeId"]))
        account = _actor(raw.get("accountId"))
        if recipe_id is None or account is None:
            continue
        session.add(
            s.KitchenRecipeRating(
                id=uuid4(),
                recipe_id=recipe_id,
                account_id=account,
                stars=int(raw["stars"]),
            )
        )
    await session.flush()


async def _replace_children(
    session: AsyncSession,
    row: s.KitchenRecipe,
    raw: dict[str, Any],
    tags: dict[str, s.Tag],
    vocabulary: VocabularyCache,
) -> None:
    """Delete-and-insert: a recipe's children are small and fully specified."""
    for model in (
        s.RecipeIngredient,
        s.RecipeStep,
        s.RecipeMealSlotLink,
        s.RecipeTagLink,
        s.RecipeEquipmentLink,
        s.RecipeAllergen,
        s.RecipeReheatInstruction,
    ):
        await session.execute(delete(model).where(model.recipe_id == row.id))
    await session.flush()

    for index, ingredient in enumerate(raw.get("ingredients") or []):
        food = await vocabulary.food_item(ingredient["name"])
        session.add(
            s.RecipeIngredient(
                id=uuid4(),
                recipe_id=row.id,
                food_item_id=food.id,
                quantity=_dec(ingredient.get("quantity")),
                unit=ingredient.get("unit"),
                group_label=ingredient.get("group"),
                position=index,
            )
        )
    details = {
        int(entry["index"]): entry for entry in raw.get("stepDetails") or []
    }
    for index, step in enumerate(raw.get("steps") or []):
        detail = details.get(index, {})
        session.add(
            s.RecipeStep(
                id=uuid4(),
                recipe_id=row.id,
                position=index,
                body=step,
                title=detail.get("title"),
                title_en=detail.get("titleEn"),
                active_minutes=(
                    _dec(detail["activeMinutes"])
                    if detail.get("activeMinutes") is not None
                    else None
                ),
                wait_minutes=(
                    _dec(detail["waitMinutes"])
                    if detail.get("waitMinutes") is not None
                    else None
                ),
            )
        )
    for index, entry in enumerate(raw.get("reheat") or []):
        session.add(
            s.RecipeReheatInstruction(
                id=uuid4(),
                recipe_id=row.id,
                method=entry["method"],
                instruction=entry["instruction"],
                position=index,
            )
        )
    await _project_nutrition(session, row, raw.get("nutrition"))
    for slot in dict.fromkeys(raw.get("mealTypes") or []):
        session.add(s.RecipeMealSlotLink(recipe_id=row.id, slot=s.MealSlot(slot)))
    for name in dict.fromkeys(str(n).strip() for n in raw.get("tags") or []):
        tag = tags.get(name)
        if tag is not None:
            session.add(s.RecipeTagLink(recipe_id=row.id, tag_id=tag.id))
    for name in dict.fromkeys(raw.get("equipment") or []):
        item = await vocabulary.equipment_item(name)
        session.add(s.RecipeEquipmentLink(recipe_id=row.id, equipment_id=item.id))
    for label in dict.fromkeys(raw.get("allergens") or []):
        session.add(s.RecipeAllergen(id=uuid4(), recipe_id=row.id, label=str(label)))
    await session.flush()


# Which ledger reason a command's audit entry represents.
LEDGER_REASON = {
    "prep.status": s.LedgerReason.PREP_OUTPUT,
    "meal.status": s.LedgerReason.MEAL_CONSUMPTION,
    "meal.leftovers": s.LedgerReason.LEFTOVER_RETURN,
    "change.undo": s.LedgerReason.UNDO_REVERSAL,
}
LOCATION = {
    "fridge": s.StorageLocation.FRIDGE,
    "freezer": s.StorageLocation.FREEZER,
    "pantry": s.StorageLocation.PANTRY,
}


def _actor(value: Any) -> UUID | None:
    try:
        return UUID(str(value)) if value else None
    except ValueError:
        return None


async def _project_batches(
    session: AsyncSession,
    household_id: UUID,
    state: dict[str, Any],
    vocabulary: VocabularyCache,
    recipes: dict[str, s.KitchenRecipe],
) -> dict[str, s.InventoryBatch]:
    incoming = {str(item["id"]): item for item in state.get("inventory") or []}
    existing = {
        row.legacy_id or str(row.id): row
        for row in (
            await session.scalars(
                select(s.InventoryBatch).where(s.InventoryBatch.household_id == household_id)
            )
        ).all()
    }
    for legacy_id in set(existing) - set(incoming):
        # Ledger rows cascade with the batch they belong to. Finished prep let
        # go of a removed box (its inputs are rewritten with the plans), so
        # the input rows that still name it go first.
        await session.execute(
            delete(s.PrepTaskInput).where(
                s.PrepTaskInput.inventory_batch_id == existing[legacy_id].id
            )
        )
        await session.execute(
            delete(s.InventoryBatch).where(s.InventoryBatch.id == existing[legacy_id].id)
        )
    await session.flush()

    for position, (legacy_id, raw) in enumerate(incoming.items()):
        food = await vocabulary.food_item(raw["name"], raw.get("type"))
        recipe = recipes.get(str(raw.get("recipeId") or ""))
        row = existing.get(legacy_id)
        if row is None:
            row = s.InventoryBatch(
                id=uuid4(), household_id=household_id, legacy_id=legacy_id
            )
            session.add(row)
            existing[legacy_id] = row
        row.food_item_id = food.id
        row.recipe_id = recipe.id if recipe else None
        row.location = LOCATION.get(
            str(raw.get("location", "fridge")).lower(), s.StorageLocation.FRIDGE
        )
        row.prepared = bool(raw.get("prepared"))
        row.stored_on = date.fromisoformat(raw["addedOn"])
        row.expires_on = (
            date.fromisoformat(raw["expiresOn"]) if raw.get("expiresOn") else None
        )
        row.priority = bool(raw.get("priority"))
        row.position = position
        row.notes = raw.get("notes")
        row.portion_grams = (
            _dec(raw["portionGrams"]) if raw.get("portionGrams") is not None else None
        )
    await session.flush()
    await _derive_food_attributes(session, incoming, existing, vocabulary)
    await session.flush()
    return existing


async def _derive_food_attributes(
    session: AsyncSession,
    incoming: dict[str, dict[str, Any]],
    batches: dict[str, s.InventoryBatch],
    vocabulary: VocabularyCache,
) -> None:
    """Icon and English name describe the food, so they are derived from its
    batches rather than accumulated on the food row.

    Accumulating could not round-trip: an attribute could be set but never
    cleared, so the food record would keep an icon the aggregate no longer has.
    Recomputing from the batches makes the aggregate authoritative — the food
    shows an icon exactly while some batch of it supplies one.
    """
    seen: dict[UUID, dict[str, Any]] = {}
    for legacy_id, raw in incoming.items():
        batch = batches.get(legacy_id)
        if batch is None:
            continue
        current = seen.setdefault(
            batch.food_item_id, {"emoji": None, "nameEn": None, "grams": None}
        )
        for key, source in (("emoji", "emoji"), ("nameEn", "nameEn")):
            if current[key] is None and raw.get(source) is not None:
                current[key] = raw[source]
        if current["grams"] is None and raw.get("portionGrams") is not None:
            current["grams"] = _dec(raw["portionGrams"])
    for food_id, values in seen.items():
        food = await session.get(s.FoodItem, food_id)
        if food is None:
            continue
        food.emoji = values["emoji"]
        food.name_en = values["nameEn"]
        food.default_portion_grams = values["grams"]
    vocabulary.food.clear()
    await vocabulary.prime()


async def _project_audit(
    session: AsyncSession, household_id: UUID, state: dict[str, Any]
) -> list[tuple[dict[str, Any], s.KitchenAuditEntry]]:
    """Append new entries and follow `undone` flips. Audit is otherwise immutable."""
    rows = {
        row.legacy_id or str(row.id): row
        for row in (
            await session.scalars(
                select(s.KitchenAuditEntry).where(
                    s.KitchenAuditEntry.household_id == household_id
                )
            )
        ).all()
    }
    plans = {
        row.legacy_id or str(row.id): row.id
        for row in (
            await session.scalars(
                select(s.WeeklyPlan).where(s.WeeklyPlan.household_id == household_id)
            )
        ).all()
    }
    accounts = set((await session.scalars(select(Account.id))).all())
    appended: list[tuple[dict[str, Any], s.KitchenAuditEntry]] = []
    for index, raw in enumerate(state.get("audit") or []):
        legacy_id = str(raw["id"])
        row = rows.get(legacy_id)
        if row is not None:
            # Undo flips this on an older entry; nothing else ever changes.
            row.undone = bool(raw.get("undone"))
            continue
        actor = _actor(raw.get("actorId"))
        row = s.KitchenAuditEntry(
            id=uuid4(),
            household_id=household_id,
            legacy_id=legacy_id,
            sequence=index,
            kind=raw["kind"],
            message=raw.get("message", ""),
            at=datetime.fromisoformat(raw["at"]),
            actor_id=actor if actor in accounts else None,
            operation_id=raw.get("operationId"),
            # Plans arrive in group 3; until then a brand new plan has no row.
            plan_id=plans.get(str(raw.get("planId") or "")),
            entity_id=raw.get("entityId"),
            component_id=raw.get("componentId"),
            undo=raw.get("undo"),
            undone=bool(raw.get("undone")),
        )
        session.add(row)
        rows[legacy_id] = row
        appended.append((raw, row))
    await session.flush()
    return appended


async def _append_ledger(
    session: AsyncSession,
    household_id: UUID,
    state: dict[str, Any],
    batches: dict[str, s.InventoryBatch],
    appended: list[tuple[dict[str, Any], s.KitchenAuditEntry]],
) -> None:
    for raw, entry in appended:
        reason = LEDGER_REASON.get(raw["kind"], s.LedgerReason.MANUAL_ADJUST)
        for position, delta in enumerate(raw.get("deltas") or []):
            batch = batches.get(str(delta["inventoryId"]))
            if batch is None:
                continue
            session.add(
                s.InventoryLedgerEntry(
                    id=uuid4(),
                    household_id=household_id,
                    batch_id=batch.id,
                    delta=_dec(delta["amount"]),
                    sequence=position,
                    reason=reason,
                    audit_id=entry.id,
                    created_at=entry.at,
                )
            )
    await session.flush()

    # Anything the aggregate changed without recording a delta — a manual
    # quantity edit, or a batch created with an opening balance — is squared up
    # here so the derived portions always equal what the aggregate reports.
    rows = (
        await session.execute(
            select(
                s.InventoryLedgerEntry.batch_id,
                func.coalesce(func.sum(s.InventoryLedgerEntry.delta), 0),
            )
            .where(s.InventoryLedgerEntry.household_id == household_id)
            .group_by(s.InventoryLedgerEntry.batch_id)
        )
    ).all()
    totals: dict[UUID, Decimal] = {
        batch_id: Decimal(str(total)) for batch_id, total in rows
    }
    for raw_item in state.get("inventory") or []:
        batch = batches.get(str(raw_item["id"]))
        if batch is None:
            continue
        target = _dec(raw_item["portions"])
        current = totals.get(batch.id, Decimal("0"))
        if target != current:
            session.add(
                s.InventoryLedgerEntry(
                    id=uuid4(),
                    household_id=household_id,
                    batch_id=batch.id,
                    delta=target - current,
                    sequence=0,
                    reason=s.LedgerReason.MANUAL_ADJUST,
                )
            )
    await session.flush()


async def project_workspace(
    session: AsyncSession,
    household_id: UUID,
    state: dict[str, Any],
    previous: dict[str, Any] | None = None,
) -> None:
    """Every section, in dependency order.

    Recipes and documents first because plans reference them; batches before
    plans because prep names its output batch; audit and the ledger last
    because an entry links the plan it belongs to and a ledger row links the
    batch it moved.

    With `previous` (the aggregate the tables already match), sections the
    command did not touch are not rewritten: re-projecting every plan's meals,
    chat and snapshots took over a second for a one-field change such as the
    planning step or a shopping tick.
    """
    if previous is None or any(
        previous.get(key) != state.get(key) for key in ("recipes", "tags")
    ):
        await project_recipes_and_tags(session, household_id, state)
    await project_recipe_ratings(session, household_id, state)
    await project_knowledge_and_settings(session, household_id, state)
    await project_meal_style_presets(session, household_id, state)
    vocabulary = VocabularyCache(session, household_id)
    await vocabulary.prime()
    recipes = {
        row.legacy_id or str(row.id): row
        for row in (
            await session.scalars(
                select(s.KitchenRecipe).where(s.KitchenRecipe.household_id == household_id)
            )
        ).all()
    }
    batches = await _project_batches(session, household_id, state, vocabulary, recipes)
    await project_plans(session, household_id, state, batches, previous)
    await project_prompts(session, household_id, state)
    appended = await _project_audit(session, household_id, state)
    await _append_ledger(session, household_id, state, batches, appended)


PREP_CATEGORY = {
    "Protein": s.PrepCategory.PROTEIN,
    "Carbs": s.PrepCategory.CARBS,
    "Vegetables": s.PrepCategory.VEGETABLES,
    "Baking": s.PrepCategory.BAKING,
    "Other": s.PrepCategory.OTHER,
}


async def project_knowledge_and_settings(
    session: AsyncSession, household_id: UUID, state: dict[str, Any]
) -> None:
    """Documents, guidance rules and the scheduler's settings row."""
    await _project_versioned(
        session,
        household_id,
        state.get("knowledgeDocuments") or [],
        s.KnowledgeDocument,
        s.KnowledgeDocumentVersion,
        "document_id",
        extra=lambda raw: {
            "category": raw.get("category", "Nutrition"),
            "source_url": raw.get("sourceUrl"),
        },
    )
    settings = state.get("settings") or {}
    await _project_versioned(
        session,
        household_id,
        settings.get("guidance") or [],
        s.GuidanceRule,
        s.GuidanceRuleVersion,
        "rule_id",
        extra=lambda raw: {},
    )
    await _project_settings_row(session, household_id, settings)


async def _project_versioned(
    session: AsyncSession,
    household_id: UUID,
    entries: list[dict[str, Any]],
    parent_model: Any,
    version_model: Any,
    parent_column: str,
    extra: Any,
) -> None:
    """One row per document plus an immutable row per content version."""
    incoming = {str(raw["id"]): raw for raw in entries}
    existing = {
        row.legacy_id or str(row.id): row
        for row in (
            await session.scalars(
                select(parent_model).where(parent_model.household_id == household_id)
            )
        ).all()
    }
    for legacy_id in set(existing) - set(incoming):
        await session.execute(
            delete(parent_model).where(parent_model.id == existing[legacy_id].id)
        )
    await session.flush()

    for legacy_id, raw in incoming.items():
        row = existing.get(legacy_id)
        if row is None:
            row = parent_model(id=uuid4(), household_id=household_id, legacy_id=legacy_id)
            session.add(row)
            existing[legacy_id] = row
        row.title = raw["title"]
        row.enabled = bool(raw.get("enabled", True))
        row.current_version = int(raw.get("version", 1))
        for key, value in extra(raw).items():
            setattr(row, key, value)
        await session.flush()
        await version_row(
            session, version_model, parent_column, row.id, raw, live=True
        )
    await session.flush()


def _stamp(entry: dict[str, Any]) -> dict[str, Any]:
    """The aggregate owns the document timestamp; the row must not invent one."""
    raw = entry.get("updatedAt")
    return {"created_at": datetime.fromisoformat(raw)} if raw else {}


async def version_row(
    session: AsyncSession,
    model: Any,
    parent_column: str,
    parent_id: UUID,
    entry: dict[str, Any],
    live: bool = False,
) -> Any:
    """Reuse an exact (version, content) match, else record a new row.

    A live document owns the row at its own version number. A snapshot whose
    content no longer matches gets a row in a free slot; the pinned number
    travels on the link, so the transport still reports the original.
    """
    wanted = int(entry.get("version", 1))
    content = entry.get("content", "")
    rows = (
        await session.scalars(
            select(model).where(getattr(model, parent_column) == parent_id)
        )
    ).all()
    for row in rows:
        if row.version == wanted and row.content == content:
            return row
    at_version = next((row for row in rows if row.version == wanted), None)
    if live and at_version is not None:
        # The aggregate is authoritative during the cutover, so the live row
        # takes the new content. Snapshots pinning it keep the old text by
        # moving to a preserved row first.
        await _preserve(session, model, parent_column, parent_id, at_version, rows)
        at_version.title = entry["title"]
        at_version.content = content
        for key, value in _stamp(entry).items():
            setattr(at_version, key, value)
        await session.flush()
        return at_version
    if at_version is None and live:
        row = model(
            id=uuid4(),
            version=wanted,
            title=entry["title"],
            content=content,
            **_stamp(entry),
            **{parent_column: parent_id},
        )
        session.add(row)
        await session.flush()
        return row
    free = max((row.version for row in rows), default=0) + 1
    row = model(
        id=uuid4(),
        version=wanted if at_version is None else free,
        title=entry["title"],
        content=content,
        **{parent_column: parent_id},
    )
    session.add(row)
    await session.flush()
    return row


async def _preserve(
    session: AsyncSession,
    model: Any,
    parent_column: str,
    parent_id: UUID,
    row: Any,
    rows: Any,
) -> None:
    """Move snapshots off a version row whose content is about to change."""
    statement = (
        select(s.PlanKnowledgeSnapshot).where(
            s.PlanKnowledgeSnapshot.document_version_id == row.id
        )
        if model is s.KnowledgeDocumentVersion
        else select(s.PlanGuidanceSnapshot).where(
            s.PlanGuidanceSnapshot.guidance_version_id == row.id
        )
    )
    pinned: list[Any] = list((await session.scalars(statement)).all())
    if not pinned:
        return
    free = max((other.version for other in rows), default=0) + 1
    copy = model(
        id=uuid4(),
        version=free,
        title=row.title,
        content=row.content,
        **{parent_column: parent_id},
    )
    session.add(copy)
    await session.flush()
    for snapshot in pinned:
        # The pinned number lives on the link, so moving rows is invisible
        # to the transport.
        if isinstance(snapshot, s.PlanKnowledgeSnapshot):
            snapshot.document_version_id = copy.id
        else:
            snapshot.guidance_version_id = copy.id
    await session.flush()


async def _project_settings_row(
    session: AsyncSession, household_id: UUID, settings: dict[str, Any]
) -> None:
    row = await session.get(s.HouseholdKitchenSettings, household_id)
    if row is None:
        row = s.HouseholdKitchenSettings(
            household_id=household_id, timezone=settings.get("timezone", "UTC")
        )
        session.add(row)
    row.people = int(settings.get("people", 3))
    row.child_age_months = _dec(settings.get("childAge"))
    row.timezone = settings.get("timezone", "America/Los_Angeles")
    row.generate_time = settings.get("generateTime", "17:00")
    row.prep_day = int(settings.get("prepDay", 6))
    row.max_prep_minutes = _dec(settings.get("maxPrepMinutes"), "240")
    row.max_daily_active_minutes = _dec(settings.get("maxDailyActiveMinutes"), "30")
    row.new_recipes_per_week = int(settings.get("newRecipesPerWeek", 2))
    row.recurring_meals = settings.get("recurringMeals", [])
    row.pinned_tags = settings.get("pinnedTags")
    row.recipe_repeat_gap_days = int(settings.get("recipeRepeatGapDays", 1))

    await _project_analysis_metrics(session, household_id, settings)

    wanted = list(
        dict.fromkeys(str(label).strip() for label in settings.get("allergies") or [])
    )
    rows = {
        row_.label: row_
        for row_ in (
            await session.scalars(
                select(s.HouseholdAllergy).where(
                    s.HouseholdAllergy.household_id == household_id
                )
            )
        ).all()
    }
    for label in set(rows) - set(wanted):
        await session.execute(
            delete(s.HouseholdAllergy).where(s.HouseholdAllergy.id == rows[label].id)
        )
    for position, label in enumerate(wanted):
        row_ = rows.get(label)
        if row_ is None:
            session.add(
                s.HouseholdAllergy(
                    id=uuid4(),
                    household_id=household_id,
                    label=label,
                    position=position,
                )
            )
        else:
            row_.position = position
    await session.flush()


async def project_prompts(
    session: AsyncSession, household_id: UUID, state: dict[str, Any]
) -> None:
    incoming = {str(raw["weekStart"]): raw for raw in state.get("weeklyPrompts") or []}
    rows = {
        row.week_start.isoformat(): row
        for row in (
            await session.scalars(
                select(s.WeeklyPrompt).where(s.WeeklyPrompt.household_id == household_id)
            )
        ).all()
    }
    for week in set(rows) - set(incoming):
        await session.execute(
            delete(s.WeeklyPrompt).where(s.WeeklyPrompt.id == rows[week].id)
        )
    for week, raw in incoming.items():
        row = rows.get(week)
        if row is None:
            session.add(
                s.WeeklyPrompt(
                    id=uuid4(),
                    household_id=household_id,
                    week_start=date.fromisoformat(week),
                    prompt=raw.get("prompt", ""),
                    workflow=raw.get("workflow"),
                )
            )
        else:
            row.prompt = raw.get("prompt", "")
            row.workflow = raw.get("workflow")
    await session.flush()


# What a plan's child rows are built from, besides the plan itself. Stock is
# compared by which batches exist (rows are reused by id), so reordering boxes
# or changing an amount does not rewrite every plan.
PLAN_CONTEXT = ("recipes", "knowledgeDocuments", "mealStylePresets")
PLAN_CHILDREN = ("prep", "meals", "chat", "presets", "guidanceSnapshot", "knowledgeSnapshot")


def _batch_ids(document: dict[str, Any]) -> list[str]:
    return sorted(str(item["id"]) for item in document.get("inventory") or [])


def _plan_children_unchanged(
    previous: dict[str, Any] | None, state: dict[str, Any], legacy_id: str
) -> bool:
    """A plan whose child rows already match: same prep, meals, chat, presets and
    snapshots, and nothing they point at (recipes, stock, documents, presets,
    guidance) changed either."""
    if previous is None:
        return False
    if any(previous.get(key) != state.get(key) for key in PLAN_CONTEXT):
        return False
    if _batch_ids(previous) != _batch_ids(state):
        return False
    if (previous.get("settings") or {}).get("guidance") != (state.get("settings") or {}).get(
        "guidance"
    ):
        return False
    before = next((p for p in previous.get("plans") or [] if str(p["id"]) == legacy_id), None)
    after = next((p for p in state.get("plans") or [] if str(p["id"]) == legacy_id), None)
    return (
        before is not None
        and after is not None
        and all(before.get(key) == after.get(key) for key in PLAN_CHILDREN)
    )


async def project_plans(
    session: AsyncSession,
    household_id: UUID,
    state: dict[str, Any],
    batches: dict[str, s.InventoryBatch],
    previous: dict[str, Any] | None = None,
) -> dict[str, s.WeeklyPlan]:
    """Plans with their prep, meals, chat and pinned snapshots.

    Prep is written before meals because a meal component references the prep
    task that produces it. With `previous`, a plan whose children did not
    change keeps its child rows; its own row (status, version, shopping
    checks) is always written.
    """
    recipes = {
        row.legacy_id or str(row.id): row
        for row in (
            await session.scalars(
                select(s.KitchenRecipe).where(s.KitchenRecipe.household_id == household_id)
            )
        ).all()
    }
    vocabulary = VocabularyCache(session, household_id)
    await vocabulary.prime()

    incoming = {str(raw["id"]): raw for raw in state.get("plans") or []}
    existing = {
        row.legacy_id or str(row.id): row
        for row in (
            await session.scalars(
                select(s.WeeklyPlan).where(s.WeeklyPlan.household_id == household_id)
            )
        ).all()
    }
    for legacy_id in set(existing) - set(incoming):
        await session.execute(
            delete(s.WeeklyPlan).where(s.WeeklyPlan.id == existing[legacy_id].id)
        )
    await session.flush()

    created: set[str] = set()
    for position, (legacy_id, raw) in enumerate(incoming.items()):
        row = existing.get(legacy_id)
        if row is None:
            created.add(legacy_id)
            row = s.WeeklyPlan(id=uuid4(), household_id=household_id, legacy_id=legacy_id)
            session.add(row)
            existing[legacy_id] = row
        row.position = position
        row.week_start = date.fromisoformat(raw["weekStart"])
        row.status = s.PlanStatus(raw["status"])
        row.version = int(raw.get("version", 1))
        row.base_version = raw.get("baseVersion")
        row.prompt = raw.get("prompt", "")
        row.fulfillment = raw.get("fulfillment")
        row.shopping_checked = raw.get("shoppingChecked", [])
    await session.flush()

    # basePlanId can name another plan in this same batch.
    for legacy_id, raw in incoming.items():
        base = existing.get(str(raw.get("basePlanId") or ""))
        existing[legacy_id].base_plan_id = base.id if base else None
    await session.flush()

    for legacy_id, raw in incoming.items():
        if legacy_id not in created and _plan_children_unchanged(previous, state, legacy_id):
            continue
        plan = existing[legacy_id]
        prep = await _project_prep(session, plan, raw.get("prep") or [], recipes, batches)
        await _project_meals(
            session, plan, raw.get("meals") or [], recipes, batches, prep, vocabulary
        )
        await _project_chat(session, plan, raw.get("chat") or [])
        await _project_plan_presets(session, household_id, plan, raw.get("presets") or [])
        await _project_snapshots(session, household_id, plan, raw)
    await session.flush()
    return existing


async def _project_prep(
    session: AsyncSession,
    plan: s.WeeklyPlan,
    tasks: list[dict[str, Any]],
    recipes: dict[str, s.KitchenRecipe],
    batches: dict[str, s.InventoryBatch],
) -> dict[str, s.PrepTask]:
    incoming = {str(raw["id"]): raw for raw in tasks}
    existing = {
        row.legacy_id or str(row.id): row
        for row in (
            await session.scalars(select(s.PrepTask).where(s.PrepTask.plan_id == plan.id))
        ).all()
    }
    for legacy_id in set(existing) - set(incoming):
        await session.execute(
            delete(s.PrepTask).where(s.PrepTask.id == existing[legacy_id].id)
        )
    await session.flush()

    for position, (legacy_id, raw) in enumerate(incoming.items()):
        row = existing.get(legacy_id)
        if row is None:
            row = s.PrepTask(id=uuid4(), plan_id=plan.id, legacy_id=legacy_id)
            session.add(row)
            existing[legacy_id] = row
        recipe = recipes.get(str(raw.get("recipeId") or ""))
        output = batches.get(str(raw.get("outputInventoryId") or ""))
        row.recipe_id = recipe.id if recipe else None
        row.name = raw["name"]
        row.category = PREP_CATEGORY.get(raw.get("type", ""), s.PrepCategory.OTHER)
        row.planned_portions = _dec(raw["plannedPortions"])
        row.actual_portions = (
            _dec(raw["actualPortions"]) if raw.get("status") == "completed" else None
        )
        row.active_minutes = _dec(raw["activeMinutes"])
        row.elapsed_minutes = _dec(raw["elapsedMinutes"])
        row.status = s.ExecutionStatus(raw["status"])
        row.liked = bool(raw.get("liked"))
        row.output_batch_id = output.id if output else None
        row.output_batch_key = raw.get("outputInventoryId")
        row.position = position
    await session.flush()

    for legacy_id in incoming:
        row = existing[legacy_id]
        for model in (s.PrepTaskStep, s.PrepTaskInput, s.PrepTaskEquipmentLink):
            await session.execute(delete(model).where(model.prep_task_id == row.id))
        await session.execute(
            delete(s.PrepTaskDependency).where(s.PrepTaskDependency.prep_task_id == row.id)
        )
    await session.flush()

    vocabulary = VocabularyCache(session, plan.household_id)
    await vocabulary.prime()
    for legacy_id, raw in incoming.items():
        row = existing[legacy_id]
        for index, step in enumerate(raw.get("steps") or []):
            session.add(
                s.PrepTaskStep(id=uuid4(), prep_task_id=row.id, position=index, text=step)
            )
        for source in raw.get("inputs") or []:
            batch = batches.get(str(source["inventoryId"]))
            if batch is None:
                continue
            session.add(
                s.PrepTaskInput(
                    id=uuid4(),
                    prep_task_id=row.id,
                    inventory_batch_id=batch.id,
                    portions=_dec(source["portions"]),
                )
            )
        for name in dict.fromkeys(raw.get("equipment") or []):
            tool = await vocabulary.equipment_item(name)
            session.add(
                s.PrepTaskEquipmentLink(prep_task_id=row.id, equipment_id=tool.id)
            )
    await session.flush()
    for legacy_id, raw in incoming.items():
        for dependency in raw.get("dependencies") or []:
            target = existing.get(str(dependency))
            if target is None:
                continue
            session.add(
                s.PrepTaskDependency(
                    prep_task_id=existing[legacy_id].id,
                    depends_on_prep_task_id=target.id,
                )
            )
    await session.flush()
    return existing


async def _project_meals(
    session: AsyncSession,
    plan: s.WeeklyPlan,
    meals: list[dict[str, Any]],
    recipes: dict[str, s.KitchenRecipe],
    batches: dict[str, s.InventoryBatch],
    prep: dict[str, s.PrepTask],
    vocabulary: VocabularyCache,
) -> None:
    incoming = {str(raw["id"]): raw for raw in meals}
    existing = {
        row.legacy_id or str(row.id): row
        for row in (
            await session.scalars(select(s.Meal).where(s.Meal.plan_id == plan.id))
        ).all()
    }
    for legacy_id in set(existing) - set(incoming):
        await session.execute(delete(s.Meal).where(s.Meal.id == existing[legacy_id].id))
    await session.flush()

    for legacy_id, raw in incoming.items():
        row = existing.get(legacy_id)
        previous_status = row.status if row is not None else None
        previous_liked = row.liked if row is not None else None
        if row is None:
            row = s.Meal(id=uuid4(), plan_id=plan.id, legacy_id=legacy_id)
            session.add(row)
            existing[legacy_id] = row
        row.day = date.fromisoformat(raw["day"])
        row.slot = s.MealSlot(raw["slot"])
        row.status = s.ExecutionStatus(raw["status"])
        row.included = bool(raw.get("included", True))
        row.liked = bool(raw.get("liked"))
        row.locked = bool(raw.get("locked"))
        row.active_minutes = _dec(raw["activeMinutes"])
        row.elapsed_minutes = _dec(raw["elapsedMinutes"])
        await session.flush()
        await _record_meal_events(session, row, previous_status, previous_liked)

    for legacy_id in incoming:
        row = existing[legacy_id]
        for model in (s.MealComponent, s.MealStep):
            await session.execute(delete(model).where(model.meal_id == row.id))
    await session.flush()

    for legacy_id, raw in incoming.items():
        row = existing[legacy_id]
        for index, component in enumerate(raw.get("components") or []):
            food = await vocabulary.food_item(component["name"], component.get("type"))
            recipe = recipes.get(str(component.get("recipeId") or ""))
            batch = batches.get(str(component.get("inventoryId") or ""))
            task = prep.get(str(component.get("prepId") or ""))
            session.add(
                s.MealComponent(
                    id=uuid4(),
                    meal_id=row.id,
                    legacy_id=component["id"],
                    position=index,
                    name=component["name"],
                    portions=_dec(component["portions"]),
                    food_item_id=food.id,
                    recipe_id=recipe.id if recipe else None,
                    inventory_batch_id=batch.id if batch else None,
                    prep_task_id=task.id if task else None,
                )
            )
        for index, step in enumerate(raw.get("steps") or []):
            session.add(
                s.MealStep(id=uuid4(), meal_id=row.id, position=index, text=step)
            )
    await session.flush()


async def _record_meal_events(
    session: AsyncSession,
    meal: s.Meal,
    previous_status: Any,
    previous_liked: bool | None,
) -> None:
    """Append-only history. `times cooked` is counted from these rows."""
    if previous_status is not None and str(previous_status) != str(meal.status):
        kind = {
            s.ExecutionStatus.COMPLETED: s.MealEventKind.COMPLETED,
            s.ExecutionStatus.SKIPPED: s.MealEventKind.SKIPPED,
            s.ExecutionStatus.PLANNED: s.MealEventKind.REOPENED,
        }[s.ExecutionStatus(str(meal.status))]
        session.add(s.MealEvent(id=uuid4(), meal_id=meal.id, kind=kind))
    elif previous_status is None and meal.status != s.ExecutionStatus.PLANNED:
        kind = (
            s.MealEventKind.COMPLETED
            if meal.status == s.ExecutionStatus.COMPLETED
            else s.MealEventKind.SKIPPED
        )
        session.add(s.MealEvent(id=uuid4(), meal_id=meal.id, kind=kind))
    if previous_liked is not None and previous_liked != meal.liked:
        session.add(
            s.MealEvent(
                id=uuid4(),
                meal_id=meal.id,
                kind=s.MealEventKind.LIKED if meal.liked else s.MealEventKind.UNLIKED,
            )
        )
    await session.flush()


async def project_meal_style_presets(
    session: AsyncSession, household_id: UUID, state: dict[str, Any]
) -> None:
    """The 47:9 catalog. Households seeded before this keep their defaults."""
    incoming = {str(raw["key"]): raw for raw in state.get("mealStylePresets") or []}
    if not incoming:
        return
    existing = {
        row.key: row
        for row in (
            await session.scalars(
                select(s.MealStylePreset).where(
                    s.MealStylePreset.household_id == household_id
                )
            )
        ).all()
    }
    for key in set(existing) - set(incoming):
        await session.execute(
            delete(s.MealStylePreset).where(s.MealStylePreset.id == existing[key].id)
        )
    for position, (key, raw) in enumerate(incoming.items()):
        row = existing.get(key)
        if row is None:
            row = s.MealStylePreset(id=uuid4(), household_id=household_id, key=key)
            session.add(row)
            existing[key] = row
        row.label = raw["label"]
        row.emoji = raw.get("emoji")
        row.tint = raw.get("tint")
        row.enabled = bool(raw.get("enabled", True))
        row.position = position
    await session.flush()


async def _project_plan_presets(
    session: AsyncSession, household_id: UUID, plan: s.WeeklyPlan, keys: list[str]
) -> None:
    await session.execute(
        delete(s.PlanPreset).where(s.PlanPreset.plan_id == plan.id)
    )
    await session.flush()
    catalog = {
        row.key: row.id
        for row in (
            await session.scalars(
                select(s.MealStylePreset).where(
                    s.MealStylePreset.household_id == household_id
                )
            )
        ).all()
    }
    for key in dict.fromkeys(keys):
        preset_id = catalog.get(str(key))
        if preset_id is not None:
            session.add(s.PlanPreset(plan_id=plan.id, preset_id=preset_id))
    await session.flush()


async def _project_chat(
    session: AsyncSession, plan: s.WeeklyPlan, messages: list[dict[str, Any]]
) -> None:
    incoming = {str(raw["id"]): raw for raw in messages}
    existing = {
        row.legacy_id or str(row.id): row
        for row in (
            await session.scalars(
                select(s.PlanChatMessage).where(s.PlanChatMessage.plan_id == plan.id)
            )
        ).all()
    }
    for legacy_id in set(existing) - set(incoming):
        await session.execute(
            delete(s.PlanChatMessage).where(s.PlanChatMessage.id == existing[legacy_id].id)
        )
    await session.flush()
    meals = {
        row.legacy_id or str(row.id): row.id
        for row in (
            await session.scalars(select(s.Meal).where(s.Meal.plan_id == plan.id))
        ).all()
    }
    for legacy_id, raw in incoming.items():
        row = existing.get(legacy_id)
        if row is None:
            row = s.PlanChatMessage(
                id=uuid4(),
                plan_id=plan.id,
                legacy_id=legacy_id,
                role=s.ChatRole(raw["role"]),
                text=raw.get("text", ""),
            )
            session.add(row)
            existing[legacy_id] = row
            await session.flush()
        else:
            row.text = raw.get("text", "")
            await session.execute(
                delete(s.PlanChatReference).where(
                    s.PlanChatReference.message_id == row.id
                )
            )
            await session.flush()
        for meal_id in raw.get("mealIds") or []:
            target = meals.get(str(meal_id))
            if target is not None:
                session.add(
                    s.PlanChatReference(message_id=existing[legacy_id].id, meal_id=target)
                )
    await session.flush()


async def _project_snapshots(
    session: AsyncSession, household_id: UUID, plan: s.WeeklyPlan, raw: dict[str, Any]
) -> None:
    await session.execute(
        delete(s.PlanGuidanceSnapshot).where(s.PlanGuidanceSnapshot.plan_id == plan.id)
    )
    await session.execute(
        delete(s.PlanKnowledgeSnapshot).where(s.PlanKnowledgeSnapshot.plan_id == plan.id)
    )
    await session.flush()
    rules = {
        row.legacy_id or str(row.id): row
        for row in (
            await session.scalars(
                select(s.GuidanceRule).where(s.GuidanceRule.household_id == household_id)
            )
        ).all()
    }
    documents = {
        row.legacy_id or str(row.id): row
        for row in (
            await session.scalars(
                select(s.KnowledgeDocument).where(
                    s.KnowledgeDocument.household_id == household_id
                )
            )
        ).all()
    }
    for entry in raw.get("guidanceSnapshot") or []:
        rule = rules.get(str(entry["id"]))
        if rule is None:
            continue
        version = await version_row(
            session, s.GuidanceRuleVersion, "rule_id", rule.id, entry
        )
        session.add(
            s.PlanGuidanceSnapshot(
                plan_id=plan.id,
                guidance_version_id=version.id,
                version=int(entry.get("version", 1)),
            )
        )
    for entry in raw.get("knowledgeSnapshot") or []:
        document = documents.get(str(entry["id"]))
        if document is None:
            continue
        version = await version_row(
            session, s.KnowledgeDocumentVersion, "document_id", document.id, entry
        )
        session.add(
            s.PlanKnowledgeSnapshot(
                plan_id=plan.id,
                document_version_id=version.id,
                version=int(entry.get("version", 1)),
            )
        )
    await session.flush()


async def _project_analysis_metrics(
    session: AsyncSession, household_id: UUID, settings: dict[str, Any]
) -> None:
    """One row per catalogued metric, each carrying its own on/off flag."""
    chosen = set(settings.get("analysisMetrics", ANALYSIS_METRICS))
    rows = {
        row.metric: row
        for row in (
            await session.scalars(
                select(s.HouseholdAnalysisMetric).where(
                    s.HouseholdAnalysisMetric.household_id == household_id
                )
            )
        ).all()
    }
    for metric in ANALYSIS_METRICS:
        row = rows.get(metric)
        if row is None:
            session.add(
                s.HouseholdAnalysisMetric(
                    id=uuid4(), household_id=household_id, metric=metric, enabled=metric in chosen
                )
            )
        else:
            row.enabled = metric in chosen
