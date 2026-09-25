"""Copy the JSON workspace aggregate into the normalised tables.

Idempotent: every row is keyed by its legacy transport id, so re-running
replaces a household's rows rather than duplicating them. Nothing is deleted
from `kitchen_workspaces`; the aggregate stays authoritative until the
relational read path is verified.

Design: docs/superpowers/specs/2026-09-20-relational-schema.md
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from recipe_agent.domain.identity.models import Account
from recipe_agent.domain.kitchen import schema as s
from recipe_agent.domain.kitchen.contracts import ANALYSIS_METRICS, Workspace
from recipe_agent.domain.kitchen.models import KitchenWorkspace

# The JSON aggregate uses these four food types; `dairy` only exists in the new
# designs, so nothing backfills into it.
FOOD_CATEGORY = {
    "Protein": s.FoodCategory.PROTEIN,
    "Carbs": s.FoodCategory.CARBS,
    "Vegetables": s.FoodCategory.VEGETABLES,
    "Dairy": s.FoodCategory.DAIRY,
    "Other": s.FoodCategory.OTHER,
}
PREP_CATEGORY = {
    "Protein": s.PrepCategory.PROTEIN,
    "Carbs": s.PrepCategory.CARBS,
    "Vegetables": s.PrepCategory.VEGETABLES,
    "Baking": s.PrepCategory.BAKING,
    "Other": s.PrepCategory.OTHER,
}
LOCATION = {
    "fridge": s.StorageLocation.FRIDGE,
    "freezer": s.StorageLocation.FREEZER,
    "pantry": s.StorageLocation.PANTRY,
}
# Which ledger reason a historical audit entry represents.
LEDGER_REASON = {
    "prep.status": s.LedgerReason.PREP_OUTPUT,
    "meal.status": s.LedgerReason.MEAL_CONSUMPTION,
    "meal.leftovers": s.LedgerReason.LEFTOVER_RETURN,
    "change.undo": s.LedgerReason.UNDO_REVERSAL,
}


def _dec(value: Any, default: str = "0") -> Decimal:
    if value is None:
        return Decimal(default)
    return Decimal(str(value))


def _date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def _moment(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _now_utc() -> datetime:
    from datetime import UTC

    return datetime.now(UTC)


def _known(value: UUID | None, accounts: set[UUID]) -> UUID | None:
    return value if value in accounts else None


def _opt(value: Any) -> Decimal | None:
    return _dec(value) if value is not None else None


def _actor(value: str | None) -> UUID | None:
    """Historic entries may carry a non-UUID actor; those are dropped, not faked."""
    if not value:
        return None
    try:
        return UUID(str(value))
    except ValueError:
        return None


class BackfillReport:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}

    def add(self, table: str, n: int = 1) -> None:
        self.counts[table] = self.counts.get(table, 0) + n

    def __str__(self) -> str:
        width = max((len(k) for k in self.counts), default=0)
        return "\n".join(f"  {k.ljust(width)}  {v}" for k, v in sorted(self.counts.items()))


class WorkspaceBackfill:
    """One household's aggregate -> relational rows, inside one transaction."""

    def __init__(self, session: AsyncSession, household_id: UUID, state: dict[str, Any]) -> None:
        self.session = session
        self.household_id = household_id
        self.state = state
        self.report = BackfillReport()
        self.food: dict[str, s.FoodItem] = {}
        self.equipment: dict[str, s.Equipment] = {}
        self.tags: dict[str, s.Tag] = {}
        self.recipes: dict[str, s.KitchenRecipe] = {}
        self.batches: dict[str, s.InventoryBatch] = {}
        self.plans: dict[str, s.WeeklyPlan] = {}
        self.meals: dict[str, s.Meal] = {}
        self.prep: dict[str, s.PrepTask] = {}
        self.audit: dict[str, s.KitchenAuditEntry] = {}

    # -- vocabulary ------------------------------------------------------

    async def food_item(self, name: str, category: str | None = None) -> s.FoodItem:
        """Upsert by name. A real category always wins over a placeholder."""
        key = name.strip()
        mapped = FOOD_CATEGORY.get(category or "", s.FoodCategory.OTHER)
        existing = self.food.get(key)
        if existing is not None:
            if existing.category == s.FoodCategory.OTHER and mapped != s.FoodCategory.OTHER:
                existing.category = mapped
            return existing
        item = s.FoodItem(id=uuid4(), household_id=self.household_id, name=key, category=mapped)
        self.session.add(item)
        await self.session.flush()
        self.food[key] = item
        self.report.add("food_items")
        return item

    async def equipment_item(self, name: str) -> s.Equipment:
        key = name.strip()
        if key in self.equipment:
            return self.equipment[key]
        item = s.Equipment(id=uuid4(), household_id=self.household_id, name=key)
        self.session.add(item)
        await self.session.flush()
        self.equipment[key] = item
        self.report.add("equipment")
        return item

    async def tag(self, name: str, listed: bool = False) -> s.Tag:
        key = name.strip()
        if key in self.tags:
            if listed:
                self.tags[key].listed = True
            return self.tags[key]
        item = s.Tag(
            id=uuid4(),
            household_id=self.household_id,
            name=key,
            listed=listed,
            position=len(self.tags),
        )
        self.session.add(item)
        await self.session.flush()
        self.tags[key] = item
        self.report.add("kitchen_tags")
        return item

    # -- sections --------------------------------------------------------

    async def settings(self) -> None:
        raw = self.state.get("settings") or {}
        self.session.add(
            s.HouseholdKitchenSettings(
                household_id=self.household_id,
                people=int(raw.get("people", 3)),
                child_age_months=_dec(raw.get("childAge")),
                timezone=raw.get("timezone", "America/Los_Angeles"),
                generate_time=raw.get("generateTime", "17:00"),
                prep_day=int(raw.get("prepDay", 6)),
                max_prep_minutes=_dec(raw.get("maxPrepMinutes"), "240"),
                max_daily_active_minutes=_dec(raw.get("maxDailyActiveMinutes"), "30"),
                new_recipes_per_week=int(raw.get("newRecipesPerWeek", 2)),
                recurring_meals=raw.get("recurringMeals", []),
                pinned_tags=raw.get("pinnedTags"),
                recipe_repeat_gap_days=int(raw.get("recipeRepeatGapDays", 1)),
            )
        )
        self.report.add("household_kitchen_settings")
        for position, label in enumerate(dict.fromkeys(raw.get("allergies") or [])):
            self.session.add(
                s.HouseholdAllergy(
                    id=uuid4(),
                    household_id=self.household_id,
                    label=str(label).strip(),
                    position=position,
                )
            )
            self.report.add("household_allergies")
        chosen = set(raw.get("analysisMetrics", ANALYSIS_METRICS))
        for metric in ANALYSIS_METRICS:
            self.session.add(
                s.HouseholdAnalysisMetric(
                    id=uuid4(),
                    household_id=self.household_id,
                    metric=metric,
                    enabled=metric in chosen,
                )
            )
            self.report.add("household_analysis_metrics")
        for rule in raw.get("guidance") or []:
            record = s.GuidanceRule(
                id=uuid4(),
                household_id=self.household_id,
                legacy_id=rule["id"],
                title=rule["title"],
                enabled=bool(rule["enabled"]),
                current_version=int(rule.get("version", 1)),
            )
            self.session.add(record)
            self.session.add(
                s.GuidanceRuleVersion(
                    id=uuid4(),
                    rule_id=record.id,
                    version=int(rule.get("version", 1)),
                    title=rule["title"],
                    content=rule.get("content", ""),
                )
            )
            self.report.add("guidance_rules")
            self.report.add("guidance_rule_versions")
            await self.session.flush()

    async def vocabulary(self) -> None:
        for name in self.state.get("tags") or []:
            await self.tag(name, listed=True)

    async def knowledge(self) -> None:
        for doc in self.state.get("knowledgeDocuments") or []:
            record = s.KnowledgeDocument(
                id=uuid4(),
                household_id=self.household_id,
                legacy_id=doc["id"],
                title=doc["title"],
                category=doc.get("category", "Nutrition"),
                source_url=doc.get("sourceUrl"),
                enabled=bool(doc.get("enabled", True)),
                current_version=int(doc.get("version", 1)),
            )
            self.session.add(record)
            self.session.add(
                s.KnowledgeDocumentVersion(
                    id=uuid4(),
                    document_id=record.id,
                    version=int(doc.get("version", 1)),
                    title=doc["title"],
                    content=doc.get("content", ""),
                    created_at=_moment(doc.get("updatedAt")) or _now_utc(),
                )
            )
            self.report.add("knowledge_documents")
            self.report.add("knowledge_document_versions")
            await self.session.flush()

    async def recipes_section(self) -> None:
        for position, raw in enumerate(self.state.get("recipes") or []):
            source = raw.get("source") or ""
            is_url = source.startswith(("http://", "https://"))
            record = s.KitchenRecipe(
                id=uuid4(),
                household_id=self.household_id,
                legacy_id=raw["id"],
                position=position,
                name=raw["name"],
                category=FOOD_CATEGORY.get(raw.get("type", ""), s.FoodCategory.OTHER),
                servings=_dec(raw["servings"], "1"),
                active_minutes=_dec(raw["activeMinutes"]),
                elapsed_minutes=_dec(raw["elapsedMinutes"]),
                is_favorite=bool(raw.get("liked")),
                incomplete=bool(raw.get("incomplete")),
                source_text=None if is_url else (source or None),
                source_url=source if is_url else None,
                name_en=raw.get("nameEn"),
                cuisine=raw.get("cuisine"),
                difficulty=raw.get("difficulty"),
                hero_image_url=raw.get("heroImageUrl"),
            )
            self.session.add(record)
            self.recipes[raw["id"]] = record
            self.report.add("kitchen_recipes")
            await self.session.flush()

            for index, ingredient in enumerate(raw.get("ingredients") or []):
                # The aggregate has no per-ingredient category, so these land as
                # `other` until a fridge batch or the user classifies them.
                food = await self.food_item(ingredient["name"])
                self.session.add(
                    s.RecipeIngredient(
                        id=uuid4(),
                        recipe_id=record.id,
                        food_item_id=food.id,
                        quantity=_dec(ingredient.get("quantity")),
                        unit=ingredient.get("unit"),
                        group_label=ingredient.get("group"),
                        position=index,
                    )
                )
                self.report.add("recipe_ingredient_items")
            details = {int(entry["index"]): entry for entry in raw.get("stepDetails") or []}
            for index, step in enumerate(raw.get("steps") or []):
                detail = details.get(index, {})
                self.session.add(
                    s.RecipeStep(
                        id=uuid4(),
                        recipe_id=record.id,
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
                self.report.add("kitchen_recipe_steps")
            for index, entry in enumerate(raw.get("reheat") or []):
                self.session.add(
                    s.RecipeReheatInstruction(
                        id=uuid4(),
                        recipe_id=record.id,
                        method=entry["method"],
                        instruction=entry["instruction"],
                        position=index,
                    )
                )
                self.report.add("recipe_reheat_instructions")
            facts = raw.get("nutrition")
            if facts is not None:
                self.session.add(
                    s.RecipeNutrition(
                        recipe_id=record.id,
                        calories=_opt(facts.get("calories")),
                        protein_g=_opt(facts.get("proteinG")),
                        carbs_g=_opt(facts.get("carbsG")),
                        fat_g=_opt(facts.get("fatG")),
                        fiber_g=_opt(facts.get("fiberG")),
                        source=facts.get("source", "unknown"),
                    )
                )
                self.report.add("recipe_nutrition")
            for slot in dict.fromkeys(raw.get("mealTypes") or []):
                self.session.add(s.RecipeMealSlotLink(recipe_id=record.id, slot=s.MealSlot(slot)))
                self.report.add("recipe_meal_slots")
            for name in dict.fromkeys(raw.get("tags") or []):
                tag = await self.tag(name)
                self.session.add(s.RecipeTagLink(recipe_id=record.id, tag_id=tag.id))
                self.report.add("kitchen_recipe_tags")
            for name in dict.fromkeys(raw.get("equipment") or []):
                item = await self.equipment_item(name)
                self.session.add(s.RecipeEquipmentLink(recipe_id=record.id, equipment_id=item.id))
                self.report.add("recipe_equipment")
            for label in dict.fromkeys(raw.get("allergens") or []):
                self.session.add(
                    s.RecipeAllergen(id=uuid4(), recipe_id=record.id, label=str(label))
                )
                self.report.add("recipe_allergens")

    async def inventory(self) -> None:
        for position, raw in enumerate(self.state.get("inventory") or []):
            food = await self.food_item(raw["name"], raw.get("type"))
            recipe = self.recipes.get(raw.get("recipeId") or "")
            location = LOCATION.get(
                str(raw.get("location", "fridge")).lower(), s.StorageLocation.FRIDGE
            )
            batch = s.InventoryBatch(
                id=uuid4(),
                household_id=self.household_id,
                legacy_id=raw["id"],
                position=position,
                food_item_id=food.id,
                recipe_id=recipe.id if recipe else None,
                location=location,
                prepared=bool(raw.get("prepared")),
                stored_on=_date(raw["addedOn"]) or date.today(),
                priority=bool(raw.get("priority")),
            )
            self.session.add(batch)
            self.batches[raw["id"]] = batch
            self.report.add("inventory_batches")

    async def plans_section(self) -> None:
        for position, raw in enumerate(self.state.get("plans") or []):
            plan = s.WeeklyPlan(
                id=uuid4(),
                household_id=self.household_id,
                legacy_id=raw["id"],
                position=position,
                week_start=_date(raw["weekStart"]) or date.today(),
                status=s.PlanStatus(raw["status"]),
                version=int(raw.get("version", 1)),
                fulfillment=raw.get("fulfillment"),
                shopping_checked=raw.get("shoppingChecked", []),
                base_version=raw.get("baseVersion"),
                prompt=raw.get("prompt", ""),
            )
            self.session.add(plan)
            self.plans[raw["id"]] = plan
            self.report.add("weekly_plans")

        # Second pass: base_plan_id can point at another plan in the same batch.
        for raw in self.state.get("plans") or []:
            base = self.plans.get(raw.get("basePlanId") or "")
            if base is not None:
                self.plans[raw["id"]].base_plan_id = base.id

        await self.session.flush()
        for raw in self.state.get("plans") or []:
            plan = self.plans[raw["id"]]
            await self._prep_tasks(plan, raw.get("prep") or [])
            await self.session.flush()
            await self._meals(plan, raw.get("meals") or [])
            await self.session.flush()
            await self._chat(plan, raw.get("chat") or [])
            await self._snapshots(plan, raw)

    async def _prep_tasks(self, plan: s.WeeklyPlan, tasks: Sequence[dict[str, Any]]) -> None:
        for index, raw in enumerate(tasks):
            output = self.batches.get(raw.get("outputInventoryId") or "")
            task = s.PrepTask(
                id=uuid4(),
                plan_id=plan.id,
                legacy_id=raw["id"],
                recipe_id=(self.recipes[raw["recipeId"]].id if raw.get("recipeId") else None),
                name=raw["name"],
                category=PREP_CATEGORY.get(raw.get("type", ""), s.PrepCategory.OTHER),
                planned_portions=_dec(raw["plannedPortions"]),
                actual_portions=(
                    _dec(raw["actualPortions"]) if raw.get("status") == "completed" else None
                ),
                active_minutes=_dec(raw["activeMinutes"]),
                elapsed_minutes=_dec(raw["elapsedMinutes"]),
                status=s.ExecutionStatus(raw["status"]),
                liked=bool(raw.get("liked")),
                output_batch_id=output.id if output else None,
                output_batch_key=raw.get("outputInventoryId"),
                position=index,
            )
            self.session.add(task)
            self.prep[raw["id"]] = task
            self.report.add("prep_tasks")
            for pos, step in enumerate(raw.get("steps") or []):
                self.session.add(
                    s.PrepTaskStep(id=uuid4(), prep_task_id=task.id, position=pos, text=step)
                )
                self.report.add("prep_task_steps")
            for source in raw.get("inputs") or []:
                batch = self.batches.get(source["inventoryId"])
                if batch is None:
                    continue
                self.session.add(
                    s.PrepTaskInput(
                        id=uuid4(),
                        prep_task_id=task.id,
                        inventory_batch_id=batch.id,
                        portions=_dec(source["portions"]),
                    )
                )
                self.report.add("prep_task_inputs")
            for name in dict.fromkeys(raw.get("equipment") or []):
                item = await self.equipment_item(name)
                self.session.add(
                    s.PrepTaskEquipmentLink(prep_task_id=task.id, equipment_id=item.id)
                )
                self.report.add("prep_task_equipment")

        for raw in tasks:
            for dependency in raw.get("dependencies") or []:
                target = self.prep.get(dependency)
                if target is None:
                    continue
                self.session.add(
                    s.PrepTaskDependency(
                        prep_task_id=self.prep[raw["id"]].id,
                        depends_on_prep_task_id=target.id,
                    )
                )
                self.report.add("prep_task_dependencies")

    async def _meals(self, plan: s.WeeklyPlan, meals: Sequence[dict[str, Any]]) -> None:
        for raw in meals:
            meal = s.Meal(
                id=uuid4(),
                plan_id=plan.id,
                legacy_id=raw["id"],
                day=_date(raw["day"]) or date.today(),
                slot=s.MealSlot(raw["slot"]),
                included=True,
                status=s.ExecutionStatus(raw["status"]),
                liked=bool(raw.get("liked")),
                locked=bool(raw.get("locked")),
                active_minutes=_dec(raw["activeMinutes"]),
                elapsed_minutes=_dec(raw["elapsedMinutes"]),
            )
            self.session.add(meal)
            self.meals[raw["id"]] = meal
            self.report.add("meals")
            for index, component in enumerate(raw.get("components") or []):
                batch = self.batches.get(component.get("inventoryId") or "")
                task = self.prep.get(component.get("prepId") or "")
                recipe = self.recipes.get(component.get("recipeId") or "")
                food = await self.food_item(component["name"], component.get("type"))
                self.session.add(
                    s.MealComponent(
                        id=uuid4(),
                        meal_id=meal.id,
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
                self.report.add("meal_components")
            for index, step in enumerate(raw.get("steps") or []):
                self.session.add(s.MealStep(id=uuid4(), meal_id=meal.id, position=index, text=step))
                self.report.add("meal_steps")

    async def _chat(self, plan: s.WeeklyPlan, messages: Sequence[dict[str, Any]]) -> None:
        for raw in messages:
            message = s.PlanChatMessage(
                id=uuid4(),
                plan_id=plan.id,
                legacy_id=raw.get("id"),
                role=s.ChatRole(raw["role"]),
                text=raw.get("text", ""),
            )
            self.session.add(message)
            self.report.add("plan_chat_messages")
            for meal_id in raw.get("mealIds") or []:
                meal = self.meals.get(meal_id)
                if meal is None:
                    continue
                self.session.add(s.PlanChatReference(message_id=message.id, meal_id=meal.id))
                self.report.add("plan_chat_references")

    async def _snapshots(self, plan: s.WeeklyPlan, raw: dict[str, Any]) -> None:
        """Snapshots pin a version row; historical text is kept verbatim."""
        for entry in raw.get("guidanceSnapshot") or []:
            rule = await self.session.scalar(
                select(s.GuidanceRule).where(
                    s.GuidanceRule.household_id == self.household_id,
                    s.GuidanceRule.legacy_id == entry["id"],
                )
            )
            if rule is None:
                continue
            version = await self._guidance_version(rule.id, entry)
            self.session.add(
                s.PlanGuidanceSnapshot(plan_id=plan.id, guidance_version_id=version.id)
            )
            self.report.add("plan_guidance_snapshots")
        for entry in raw.get("knowledgeSnapshot") or []:
            doc = await self.session.scalar(
                select(s.KnowledgeDocument).where(
                    s.KnowledgeDocument.household_id == self.household_id,
                    s.KnowledgeDocument.legacy_id == entry["id"],
                )
            )
            if doc is None:
                continue
            doc_version = await self._knowledge_version(doc.id, entry)
            self.session.add(
                s.PlanKnowledgeSnapshot(plan_id=plan.id, document_version_id=doc_version.id)
            )
            self.report.add("plan_knowledge_snapshots")

    async def _guidance_version(
        self, rule_id: UUID, entry: dict[str, Any]
    ) -> s.GuidanceRuleVersion:
        await self.session.flush()
        wanted = int(entry.get("version", 1))
        found = await self.session.scalar(
            select(s.GuidanceRuleVersion).where(
                s.GuidanceRuleVersion.rule_id == rule_id,
                s.GuidanceRuleVersion.version == wanted,
            )
        )
        if found is not None and found.content == entry.get("content", ""):
            return found
        # The rule moved on since this plan was generated, so the snapshot keeps
        # its own immutable row rather than silently pointing at newer text.
        highest = await self.session.scalar(
            select(s.GuidanceRuleVersion.version)
            .where(s.GuidanceRuleVersion.rule_id == rule_id)
            .order_by(s.GuidanceRuleVersion.version.desc())
            .limit(1)
        )
        record = s.GuidanceRuleVersion(
            id=uuid4(),
            rule_id=rule_id,
            version=(highest or 0) + 1,
            title=entry["title"],
            content=entry.get("content", ""),
        )
        self.session.add(record)
        self.report.add("guidance_rule_versions (snapshot)")
        return record

    async def _knowledge_version(
        self, document_id: UUID, entry: dict[str, Any]
    ) -> s.KnowledgeDocumentVersion:
        await self.session.flush()
        wanted = int(entry.get("version", 1))
        found = await self.session.scalar(
            select(s.KnowledgeDocumentVersion).where(
                s.KnowledgeDocumentVersion.document_id == document_id,
                s.KnowledgeDocumentVersion.version == wanted,
            )
        )
        if found is not None and found.content == entry.get("content", ""):
            return found
        highest = await self.session.scalar(
            select(s.KnowledgeDocumentVersion.version)
            .where(s.KnowledgeDocumentVersion.document_id == document_id)
            .order_by(s.KnowledgeDocumentVersion.version.desc())
            .limit(1)
        )
        record = s.KnowledgeDocumentVersion(
            id=uuid4(),
            document_id=document_id,
            version=(highest or 0) + 1,
            title=entry["title"],
            content=entry.get("content", ""),
        )
        self.session.add(record)
        self.report.add("knowledge_document_versions (snapshot)")
        return record

    async def audit_and_ledger(self) -> None:
        """Replay audit deltas as ledger rows, then prepend opening balances.

        The aggregate only stores a current balance plus a delta history, so the
        opening entry is whatever makes the ledger sum to that balance. This
        keeps the invariant `portions == sum(ledger)` true from the first row.
        """
        movements: dict[str, list[tuple[Decimal, s.LedgerReason, s.KitchenAuditEntry, int]]] = {}
        # actorId is free text in the aggregate and may name an account that no
        # longer exists; a dangling reference must not fail the whole backfill.
        accounts = set((await self.session.scalars(select(Account.id))).all())
        for index, raw in enumerate(self.state.get("audit") or []):
            plan = self.plans.get(raw.get("planId") or "")
            entry = s.KitchenAuditEntry(
                id=uuid4(),
                household_id=self.household_id,
                legacy_id=raw["id"],
                sequence=index,
                kind=raw["kind"],
                message=raw.get("message", ""),
                at=_moment(raw.get("at")) or datetime.now(tz=None),
                actor_id=_known(_actor(raw.get("actorId")), accounts),
                operation_id=raw.get("operationId"),
                plan_id=plan.id if plan else None,
                entity_id=raw.get("entityId"),
                component_id=raw.get("componentId"),
                undo=raw.get("undo"),
                undone=bool(raw.get("undone")),
            )
            self.session.add(entry)
            self.audit[raw["id"]] = entry
            self.report.add("kitchen_audit_entries")
            reason = LEDGER_REASON.get(raw["kind"], s.LedgerReason.MANUAL_ADJUST)
            for position, delta in enumerate(raw.get("deltas") or []):
                movements.setdefault(delta["inventoryId"], []).append(
                    (_dec(delta["amount"]), reason, entry, position)
                )

        await self.session.flush()
        for legacy_id, batch in self.batches.items():
            entries = movements.get(legacy_id, [])
            moved = sum((amount for amount, _, _, _ in entries), Decimal("0"))
            current = _dec(
                next(
                    item["portions"] for item in self.state["inventory"] if item["id"] == legacy_id
                )
            )
            opening = current - moved
            if opening != 0:
                self.session.add(
                    s.InventoryLedgerEntry(
                        id=uuid4(),
                        household_id=self.household_id,
                        batch_id=batch.id,
                        delta=opening,
                        reason=s.LedgerReason.MANUAL_ADJUST,
                    )
                )
                self.report.add("inventory_ledger_entries")
            for amount, reason, entry, position in entries:
                self.session.add(
                    s.InventoryLedgerEntry(
                        id=uuid4(),
                        household_id=self.household_id,
                        batch_id=batch.id,
                        delta=amount,
                        sequence=position,
                        reason=reason,
                        audit_id=entry.id,
                        created_at=entry.at,
                    )
                )
                self.report.add("inventory_ledger_entries")

    async def ratings(self) -> None:
        for raw in self.state.get("recipeRatings") or []:
            recipe = self.recipes.get(str(raw["recipeId"]))
            account = _actor(raw.get("accountId"))
            if recipe is None or account is None:
                continue
            self.session.add(
                s.KitchenRecipeRating(
                    id=uuid4(),
                    recipe_id=recipe.id,
                    account_id=account,
                    stars=int(raw["stars"]),
                )
            )
            self.report.add("kitchen_recipe_ratings")
        await self.session.flush()

    async def presets(self) -> None:
        for position, raw in enumerate(self.state.get("mealStylePresets") or []):
            self.session.add(
                s.MealStylePreset(
                    id=uuid4(),
                    household_id=self.household_id,
                    key=raw["key"],
                    label=raw["label"],
                    emoji=raw.get("emoji"),
                    tint=raw.get("tint"),
                    enabled=bool(raw.get("enabled", True)),
                    position=position,
                )
            )
            self.report.add("meal_style_presets")
        await self.session.flush()

    async def prompts(self) -> None:
        for raw in self.state.get("weeklyPrompts") or []:
            self.session.add(
                s.WeeklyPrompt(
                    id=uuid4(),
                    household_id=self.household_id,
                    week_start=_date(raw["weekStart"]) or date.today(),
                    prompt=raw.get("prompt", ""),
                )
            )
            self.report.add("weekly_prompts")

    async def run(self) -> BackfillReport:
        for step in (
            self.settings,
            self.vocabulary,
            self.knowledge,
            self.recipes_section,
            self.inventory,
            self.plans_section,
            self.ratings,
            self.presets,
            self.prompts,
            self.audit_and_ledger,
        ):
            await step()
            await self.session.flush()
        return self.report


# Child rows cascade, so clearing the roots is enough.
_ROOTS: tuple[Any, ...] = (
    s.KitchenAuditEntry,
    s.WeeklyPlan,
    s.WeeklyPrompt,
    s.InventoryLedgerEntry,
    s.InventoryBatch,
    s.KitchenRecipe,
    s.KnowledgeDocument,
    s.GuidanceRule,
    s.HouseholdAllergy,
    s.HouseholdAnalysisMetric,
    s.HouseholdKitchenSettings,
    s.MealStylePreset,
    s.Tag,
    s.Equipment,
    s.FoodItem,
)


async def clear_household(session: AsyncSession, household_id: UUID) -> None:
    for model in _ROOTS:
        column = model.household_id if hasattr(model, "household_id") else None
        if column is None:
            continue
        await session.execute(delete(model).where(column == household_id))


async def backfill_household(
    session: AsyncSession, household_id: UUID, state: dict[str, Any]
) -> BackfillReport:
    await clear_household(session, household_id)
    await session.flush()
    # Normalise through the contract first so the backfill sees exactly what a
    # reader sees, defaults included. Reading the raw document would miss
    # anything the contract supplies but the stored state predates.
    normalised = Workspace.model_validate(state).model_dump(mode="json", exclude_none=True)
    return await WorkspaceBackfill(session, household_id, normalised).run()


async def backfill_all(session: AsyncSession) -> dict[UUID, BackfillReport]:
    rows: Iterable[KitchenWorkspace] = (await session.scalars(select(KitchenWorkspace))).all()
    return {
        row.household_id: await backfill_household(session, row.household_id, row.state)
        for row in rows
    }
