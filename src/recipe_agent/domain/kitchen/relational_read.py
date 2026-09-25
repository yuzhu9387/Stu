"""Rebuild the transport `Workspace` from the normalised tables.

The contract in `contracts.py` does not change: the frontend, the engine, the
MCP endpoint and AI generation keep seeing the same camelCase document. Only its
source moves. That makes the cutover verifiable — the same household must render
identically from the aggregate and from the tables.

Design: docs/superpowers/specs/2026-09-20-relational-schema.md
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from recipe_agent.domain.kitchen import schema as s
from recipe_agent.domain.kitchen.contracts import ANALYSIS_METRICS

FOOD_TYPE = {
    s.FoodCategory.PROTEIN: "Protein",
    s.FoodCategory.CARBS: "Carbs",
    s.FoodCategory.VEGETABLES: "Vegetables",
    s.FoodCategory.DAIRY: "Dairy",
    s.FoodCategory.OTHER: "Other",
}
PREP_TYPE = {
    s.PrepCategory.PROTEIN: "Protein",
    s.PrepCategory.CARBS: "Carbs",
    s.PrepCategory.VEGETABLES: "Vegetables",
    s.PrepCategory.BAKING: "Baking",
    s.PrepCategory.OTHER: "Other",
}


def _text(value: Any) -> str:
    """Enum columns are plain `String`, so the driver returns str, not a member."""
    return value.value if hasattr(value, "value") else str(value)


def _num(value: Decimal | float | int | None) -> float:
    """Transport numbers are JSON floats; trailing zeros must not survive."""
    return float(value or 0)


def _group(rows: Any, key: str) -> dict[UUID, list[Any]]:
    out: dict[UUID, list[Any]] = defaultdict(list)
    for row in rows:
        out[getattr(row, key)].append(row)
    return out


class RelationalWorkspaceReader:
    """Loads one household's workspace with a bounded number of queries."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _all(self, statement: Any) -> list[Any]:
        return list((await self.session.scalars(statement)).all())

    async def load(self, household_id: UUID, revision: int) -> dict[str, Any]:
        food = {
            item.id: item
            for item in await self._all(
                select(s.FoodItem).where(s.FoodItem.household_id == household_id)
            )
        }
        equipment = {
            item.id: item.name
            for item in await self._all(
                select(s.Equipment).where(s.Equipment.household_id == household_id)
            )
        }
        # The catalog renders as an ordered chip row, so insertion order is
        # user-visible and must not be re-sorted.
        tag_rows = await self._all(
            select(s.Tag)
            .where(s.Tag.household_id == household_id)
            .order_by(s.Tag.position, s.Tag.id)
        )
        tags = {item.id: item.name for item in tag_rows}
        listed = [item.name for item in tag_rows if item.listed]
        recipes, recipe_by_id = await self._recipes(household_id, equipment, tags, food)
        inventory, batch_by_id = await self._inventory(household_id, food, recipe_by_id)
        plans = await self._plans(household_id, equipment, recipe_by_id, batch_by_id, food)
        return {
            "revision": revision,
            "recipes": recipes,
            "knowledgeDocuments": await self._knowledge(household_id),
            "inventory": inventory,
            "plans": plans,
            "tags": listed,
            "mealStylePresets": await self._presets(household_id),
            "recipeRatings": await self._ratings(recipe_by_id),
            "weeklyPrompts": await self._prompts(household_id),
            "settings": await self._settings(household_id),
            "audit": await self._audit(household_id),
        }

    # -- recipes ---------------------------------------------------------

    async def _recipes(
        self,
        household_id: UUID,
        equipment: dict[UUID, str],
        tags: dict[UUID, str],
        food: dict[UUID, s.FoodItem],
    ) -> tuple[list[dict[str, Any]], dict[UUID, s.KitchenRecipe]]:
        rows = await self._all(
            select(s.KitchenRecipe)
            .where(s.KitchenRecipe.household_id == household_id)
            .order_by(s.KitchenRecipe.position, s.KitchenRecipe.created_at, s.KitchenRecipe.id)
        )
        by_id = {row.id: row for row in rows}
        if not by_id:
            return [], by_id
        ids = list(by_id)
        ingredients = _group(
            await self._all(
                select(s.RecipeIngredient)
                .where(s.RecipeIngredient.recipe_id.in_(ids))
                .order_by(s.RecipeIngredient.position)
            ),
            "recipe_id",
        )
        steps = _group(
            await self._all(
                select(s.RecipeStep)
                .where(s.RecipeStep.recipe_id.in_(ids))
                .order_by(s.RecipeStep.position)
            ),
            "recipe_id",
        )
        slots = _group(
            await self._all(
                select(s.RecipeMealSlotLink).where(s.RecipeMealSlotLink.recipe_id.in_(ids))
            ),
            "recipe_id",
        )
        tag_links = _group(
            await self._all(select(s.RecipeTagLink).where(s.RecipeTagLink.recipe_id.in_(ids))),
            "recipe_id",
        )
        equipment_links = _group(
            await self._all(
                select(s.RecipeEquipmentLink).where(s.RecipeEquipmentLink.recipe_id.in_(ids))
            ),
            "recipe_id",
        )
        allergens = _group(
            await self._all(select(s.RecipeAllergen).where(s.RecipeAllergen.recipe_id.in_(ids))),
            "recipe_id",
        )
        reheat = _group(
            await self._all(
                select(s.RecipeReheatInstruction)
                .where(s.RecipeReheatInstruction.recipe_id.in_(ids))
                .order_by(s.RecipeReheatInstruction.position)
            ),
            "recipe_id",
        )
        nutrition = {
            row.recipe_id: row
            for row in await self._all(
                select(s.RecipeNutrition).where(s.RecipeNutrition.recipe_id.in_(ids))
            )
        }
        out = []
        for row in rows:
            out.append(
                {
                    "id": row.legacy_id or str(row.id),
                    "name": row.name,
                    "type": FOOD_TYPE[row.category],
                    "mealTypes": [_text(link.slot) for link in slots.get(row.id, [])],
                    "tags": [tags[link.tag_id] for link in tag_links.get(row.id, [])],
                    "servings": _num(row.servings),
                    "activeMinutes": _num(row.active_minutes),
                    "elapsedMinutes": _num(row.elapsed_minutes),
                    "ingredients": [
                        {
                            "name": food[item.food_item_id].name,
                            "quantity": _num(item.quantity),
                            "unit": item.unit or "",
                            **({"group": item.group_label} if item.group_label else {}),
                        }
                        for item in ingredients.get(row.id, [])
                    ],
                    "steps": [step.body for step in steps.get(row.id, [])],
                    "liked": row.is_favorite,
                    "source": row.source_url or row.source_text or "",
                    "incomplete": row.incomplete,
                    "allergens": [item.label for item in allergens.get(row.id, [])],
                    "equipment": [
                        equipment[link.equipment_id] for link in equipment_links.get(row.id, [])
                    ],
                }
            )
            entry = out[-1]
            for key, value in (
                ("nameEn", row.name_en),
                ("cuisine", row.cuisine),
                ("difficulty", _text(row.difficulty) if row.difficulty else None),
                ("heroImageUrl", row.hero_image_url),
            ):
                if value:
                    entry[key] = value
            details = []
            for step in steps.get(row.id, []):
                annotation = {
                    key: value
                    for key, value in (
                        ("title", step.title),
                        ("titleEn", step.title_en),
                        (
                            "activeMinutes",
                            _num(step.active_minutes) if step.active_minutes is not None else None,
                        ),
                        (
                            "waitMinutes",
                            _num(step.wait_minutes) if step.wait_minutes is not None else None,
                        ),
                    )
                    if value is not None
                }
                if annotation:
                    details.append({"index": step.position, **annotation})
            if details:
                entry["stepDetails"] = details
            if row.id in reheat:
                entry["reheat"] = [
                    {"method": _text(item.method), "instruction": item.instruction}
                    for item in reheat[row.id]
                ]
            facts = nutrition.get(row.id)
            if facts is not None:
                entry["nutrition"] = {
                    **{
                        key: _num(value)
                        for key, value in (
                            ("calories", facts.calories),
                            ("proteinG", facts.protein_g),
                            ("carbsG", facts.carbs_g),
                            ("fatG", facts.fat_g),
                            ("fiberG", facts.fiber_g),
                        )
                        if value is not None
                    },
                    "source": _text(facts.source),
                }
        return out, by_id

    # -- fridge ----------------------------------------------------------

    async def _inventory(
        self,
        household_id: UUID,
        food: dict[UUID, s.FoodItem],
        recipes: dict[UUID, s.KitchenRecipe],
    ) -> tuple[list[dict[str, Any]], dict[UUID, s.InventoryBatch]]:
        rows = await self._all(
            select(s.InventoryBatch)
            .where(s.InventoryBatch.household_id == household_id)
            .order_by(s.InventoryBatch.position, s.InventoryBatch.created_at, s.InventoryBatch.id)
        )
        by_id = {row.id: row for row in rows}
        balances: dict[UUID, Decimal] = defaultdict(lambda: Decimal("0"))
        if rows:
            totals = await self.session.execute(
                select(
                    s.InventoryLedgerEntry.batch_id,
                    func.coalesce(func.sum(s.InventoryLedgerEntry.delta), 0),
                )
                .where(s.InventoryLedgerEntry.batch_id.in_(list(by_id)))
                .group_by(s.InventoryLedgerEntry.batch_id)
            )
            balances.update({batch: Decimal(str(total)) for batch, total in totals})
        out = []
        for row in rows:
            item = {
                "id": row.legacy_id or str(row.id),
                "name": food[row.food_item_id].name,
                "type": FOOD_TYPE[food[row.food_item_id].category],
                # Portions are derived, never stored: the ledger is the truth.
                "portions": _num(balances[row.id]),
                "location": _text(row.location),
                "prepared": row.prepared,
                "addedOn": row.stored_on.isoformat(),
                "priority": row.priority,
            }
            if row.recipe_id and row.recipe_id in recipes:
                recipe = recipes[row.recipe_id]
                item["recipeId"] = recipe.legacy_id or str(recipe.id)
            if row.expires_on:
                item["expiresOn"] = row.expires_on.isoformat()
            if row.notes:
                item["notes"] = row.notes
            grams = row.portion_grams or food[row.food_item_id].default_portion_grams
            if grams is not None:
                item["portionGrams"] = _num(grams)
            if food[row.food_item_id].emoji:
                item["emoji"] = food[row.food_item_id].emoji
            if food[row.food_item_id].name_en:
                item["nameEn"] = food[row.food_item_id].name_en
            out.append(item)
        return out, by_id

    # -- plans -----------------------------------------------------------

    async def _plans(
        self,
        household_id: UUID,
        equipment: dict[UUID, str],
        recipes: dict[UUID, s.KitchenRecipe],
        batches: dict[UUID, s.InventoryBatch],
        food: dict[UUID, s.FoodItem],
    ) -> list[dict[str, Any]]:
        plans = await self._all(
            select(s.WeeklyPlan)
            .where(s.WeeklyPlan.household_id == household_id)
            .order_by(s.WeeklyPlan.position, s.WeeklyPlan.created_at, s.WeeklyPlan.id)
        )
        if not plans:
            return []
        plan_ids = [plan.id for plan in plans]
        plan_by_id = {plan.id: plan for plan in plans}

        prep_rows = await self._all(
            select(s.PrepTask)
            .where(s.PrepTask.plan_id.in_(plan_ids))
            .order_by(s.PrepTask.position, s.PrepTask.id)
        )
        prep_by_id = {row.id: row for row in prep_rows}
        prep_by_plan = _group(prep_rows, "plan_id")
        prep_ids = list(prep_by_id)
        prep_steps = _group(
            await self._all(
                select(s.PrepTaskStep)
                .where(s.PrepTaskStep.prep_task_id.in_(prep_ids or [None]))
                .order_by(s.PrepTaskStep.position)
            ),
            "prep_task_id",
        )
        prep_inputs = _group(
            await self._all(
                select(s.PrepTaskInput).where(s.PrepTaskInput.prep_task_id.in_(prep_ids or [None]))
            ),
            "prep_task_id",
        )
        prep_equipment = _group(
            await self._all(
                select(s.PrepTaskEquipmentLink).where(
                    s.PrepTaskEquipmentLink.prep_task_id.in_(prep_ids or [None])
                )
            ),
            "prep_task_id",
        )
        prep_deps = _group(
            await self._all(
                select(s.PrepTaskDependency).where(
                    s.PrepTaskDependency.prep_task_id.in_(prep_ids or [None])
                )
            ),
            "prep_task_id",
        )

        meal_rows = await self._all(
            select(s.Meal)
            .where(s.Meal.plan_id.in_(plan_ids))
            .order_by(s.Meal.day, s.Meal.slot, s.Meal.id)
        )
        meal_by_id = {row.id: row for row in meal_rows}
        meals_by_plan = _group(meal_rows, "plan_id")
        meal_ids = list(meal_by_id) or [None]
        components = _group(
            await self._all(
                select(s.MealComponent)
                .where(s.MealComponent.meal_id.in_(meal_ids))
                .order_by(s.MealComponent.position)
            ),
            "meal_id",
        )
        meal_steps = _group(
            await self._all(
                select(s.MealStep)
                .where(s.MealStep.meal_id.in_(meal_ids))
                .order_by(s.MealStep.position)
            ),
            "meal_id",
        )
        chat_rows = await self._all(
            select(s.PlanChatMessage)
            .where(s.PlanChatMessage.plan_id.in_(plan_ids))
            .order_by(s.PlanChatMessage.created_at, s.PlanChatMessage.id)
        )
        chat_by_plan = _group(chat_rows, "plan_id")
        chat_refs = _group(
            await self._all(
                select(s.PlanChatReference).where(
                    s.PlanChatReference.message_id.in_([row.id for row in chat_rows] or [None])
                )
            ),
            "message_id",
        )
        preset_rows = await self._all(
            select(s.MealStylePreset)
            .where(s.MealStylePreset.household_id == household_id)
            .order_by(s.MealStylePreset.position, s.MealStylePreset.key)
        )
        preset_keys = {row.id: row.key for row in preset_rows}
        plan_presets = _group(
            await self._all(select(s.PlanPreset).where(s.PlanPreset.plan_id.in_(plan_ids))),
            "plan_id",
        )
        guidance_snapshots = await self._guidance_snapshots(plan_ids)
        knowledge_snapshots = await self._knowledge_snapshots(plan_ids)

        def transport(entity: Any) -> str:
            return entity.legacy_id or str(entity.id)

        out = []
        for plan in plans:
            prep = []
            for task in prep_by_plan.get(plan.id, []):
                record: dict[str, Any] = {
                    "id": transport(task),
                    "name": task.name,
                    "type": PREP_TYPE[task.category],
                    "plannedPortions": _num(task.planned_portions),
                    "actualPortions": _num(task.actual_portions),
                    "activeMinutes": _num(task.active_minutes),
                    "elapsedMinutes": _num(task.elapsed_minutes),
                    "steps": [step.text for step in prep_steps.get(task.id, [])],
                    "status": _text(task.status),
                    "liked": task.liked,
                    "inputs": [
                        {
                            "inventoryId": transport(batches[link.inventory_batch_id]),
                            "portions": _num(link.portions),
                        }
                        for link in prep_inputs.get(task.id, [])
                        if link.inventory_batch_id in batches
                    ],
                    "equipment": [
                        equipment[link.equipment_id] for link in prep_equipment.get(task.id, [])
                    ],
                    "dependencies": [
                        transport(prep_by_id[link.depends_on_prep_task_id])
                        for link in prep_deps.get(task.id, [])
                        if link.depends_on_prep_task_id in prep_by_id
                    ],
                }
                if task.recipe_id and task.recipe_id in recipes:
                    record["recipeId"] = transport(recipes[task.recipe_id])
                if task.output_batch_id and task.output_batch_id in batches:
                    record["outputInventoryId"] = transport(batches[task.output_batch_id])
                elif task.output_batch_key:
                    # Still planned: the batch it will produce does not exist yet.
                    record["outputInventoryId"] = task.output_batch_key
                prep.append(record)

            meals = []
            for meal in meals_by_plan.get(plan.id, []):
                parts = []
                for component in components.get(meal.id, []):
                    part: dict[str, Any] = {
                        "id": component.legacy_id or str(component.id),
                        "name": component.name,
                        "type": FOOD_TYPE[
                            food[component.food_item_id].category
                            if component.food_item_id in food
                            else s.FoodCategory.OTHER
                        ],
                        "portions": _num(component.portions),
                    }
                    if component.recipe_id and component.recipe_id in recipes:
                        part["recipeId"] = transport(recipes[component.recipe_id])
                    if component.inventory_batch_id in batches:
                        part["inventoryId"] = transport(batches[component.inventory_batch_id])
                    if component.prep_task_id in prep_by_id:
                        part["prepId"] = transport(prep_by_id[component.prep_task_id])
                    parts.append(part)
                meals.append(
                    {
                        "id": transport(meal),
                        "day": meal.day.isoformat(),
                        "slot": _text(meal.slot),
                        "included": meal.included,
                        "components": parts,
                        "activeMinutes": _num(meal.active_minutes),
                        "elapsedMinutes": _num(meal.elapsed_minutes),
                        "steps": [step.text for step in meal_steps.get(meal.id, [])],
                        "status": _text(meal.status),
                        "liked": meal.liked,
                        "locked": meal.locked,
                    }
                )

            selected = [
                preset_keys[link.preset_id]
                for link in plan_presets.get(plan.id, [])
                if link.preset_id in preset_keys
            ]
            record_plan: dict[str, Any] = {
                "id": transport(plan),
                "weekStart": plan.week_start.isoformat(),
                "status": _text(plan.status),
                "version": plan.version,
                "prompt": plan.prompt,
                **({"fulfillment": plan.fulfillment} if plan.fulfillment else {}),
                "shoppingChecked": plan.shopping_checked or [],
                "meals": meals,
                "prep": prep,
                "presets": selected,
                "chat": [
                    {
                        "id": message.legacy_id or str(message.id),
                        "role": _text(message.role),
                        "text": message.text,
                        "mealIds": [
                            transport(meal_by_id[link.meal_id])
                            for link in chat_refs.get(message.id, [])
                            if link.meal_id in meal_by_id
                        ],
                    }
                    for message in chat_by_plan.get(plan.id, [])
                ],
                "guidanceSnapshot": guidance_snapshots.get(plan.id, []),
                "knowledgeSnapshot": knowledge_snapshots.get(plan.id, []),
            }
            if plan.base_plan_id and plan.base_plan_id in plan_by_id:
                record_plan["basePlanId"] = transport(plan_by_id[plan.base_plan_id])
            if plan.base_version is not None:
                record_plan["baseVersion"] = plan.base_version
            out.append(record_plan)
        return out

    async def _guidance_snapshots(self, plan_ids: list[UUID]) -> dict[UUID, list[dict[str, Any]]]:
        rows = await self.session.execute(
            select(s.PlanGuidanceSnapshot, s.GuidanceRuleVersion, s.GuidanceRule)
            .join(
                s.GuidanceRuleVersion,
                s.GuidanceRuleVersion.id == s.PlanGuidanceSnapshot.guidance_version_id,
            )
            .join(s.GuidanceRule, s.GuidanceRule.id == s.GuidanceRuleVersion.rule_id)
            .where(s.PlanGuidanceSnapshot.plan_id.in_(plan_ids))
            .order_by(s.GuidanceRuleVersion.created_at, s.GuidanceRuleVersion.id)
        )
        out: dict[UUID, list[dict[str, Any]]] = defaultdict(list)
        for link, version, rule in rows:
            out[link.plan_id].append(
                {
                    "id": rule.legacy_id or str(rule.id),
                    "title": version.title,
                    "content": version.content,
                    "enabled": rule.enabled,
                    "version": version.version,
                }
            )
        return out

    async def _knowledge_snapshots(self, plan_ids: list[UUID]) -> dict[UUID, list[dict[str, Any]]]:
        rows = await self.session.execute(
            select(s.PlanKnowledgeSnapshot, s.KnowledgeDocumentVersion, s.KnowledgeDocument)
            .join(
                s.KnowledgeDocumentVersion,
                s.KnowledgeDocumentVersion.id == s.PlanKnowledgeSnapshot.document_version_id,
            )
            .join(
                s.KnowledgeDocument,
                s.KnowledgeDocument.id == s.KnowledgeDocumentVersion.document_id,
            )
            .where(s.PlanKnowledgeSnapshot.plan_id.in_(plan_ids))
            .order_by(s.KnowledgeDocumentVersion.created_at, s.KnowledgeDocumentVersion.id)
        )
        out: dict[UUID, list[dict[str, Any]]] = defaultdict(list)
        for link, version, document in rows:
            entry = {
                "id": document.legacy_id or str(document.id),
                "title": version.title,
                "content": version.content,
                "category": document.category,
                "enabled": document.enabled,
                "version": version.version,
                "updatedAt": version.created_at.isoformat(),
            }
            if document.source_url:
                entry["sourceUrl"] = document.source_url
            out[link.plan_id].append(entry)
        return out

    # -- remaining sections ----------------------------------------------

    async def _knowledge(self, household_id: UUID) -> list[dict[str, Any]]:
        documents = await self._all(
            select(s.KnowledgeDocument)
            .where(s.KnowledgeDocument.household_id == household_id)
            .order_by(s.KnowledgeDocument.created_at, s.KnowledgeDocument.id)
        )
        if not documents:
            return []
        versions = {
            (row.document_id, row.version): row
            for row in await self._all(
                select(s.KnowledgeDocumentVersion).where(
                    s.KnowledgeDocumentVersion.document_id.in_([d.id for d in documents])
                )
            )
        }
        out = []
        for document in documents:
            version = versions.get((document.id, document.current_version))
            entry = {
                "id": document.legacy_id or str(document.id),
                "title": version.title if version else "",
                "content": version.content if version else "",
                "category": document.category,
                "enabled": document.enabled,
                "version": document.current_version,
                "updatedAt": (
                    version.created_at.isoformat() if version else document.created_at.isoformat()
                ),
            }
            if document.source_url:
                entry["sourceUrl"] = document.source_url
            out.append(entry)
        return out

    async def _ratings(self, recipes: dict[UUID, s.KitchenRecipe]) -> list[dict[str, Any]]:
        if not recipes:
            return []
        rows = await self._all(
            select(s.KitchenRecipeRating)
            .where(s.KitchenRecipeRating.recipe_id.in_(list(recipes)))
            .order_by(s.KitchenRecipeRating.created_at, s.KitchenRecipeRating.id)
        )
        return [
            {
                "recipeId": recipes[row.recipe_id].legacy_id or str(row.recipe_id),
                "accountId": str(row.account_id),
                "stars": row.stars,
            }
            for row in rows
        ]

    async def _presets(self, household_id: UUID) -> list[dict[str, Any]]:
        out = []
        for row in await self._all(
            select(s.MealStylePreset)
            .where(s.MealStylePreset.household_id == household_id)
            .order_by(s.MealStylePreset.position, s.MealStylePreset.key)
        ):
            entry: dict[str, Any] = {
                "key": row.key,
                "label": row.label,
                "enabled": row.enabled,
            }
            if row.emoji:
                entry["emoji"] = row.emoji
            if row.tint:
                entry["tint"] = row.tint
            out.append(entry)
        return out

    async def _prompts(self, household_id: UUID) -> list[dict[str, Any]]:
        return [
            {
                "weekStart": row.week_start.isoformat(),
                "prompt": row.prompt,
                **({"workflow": row.workflow} if row.workflow is not None else {}),
            }
            for row in await self._all(
                select(s.WeeklyPrompt)
                .where(s.WeeklyPrompt.household_id == household_id)
                .order_by(s.WeeklyPrompt.week_start)
            )
        ]

    async def _settings(self, household_id: UUID) -> dict[str, Any]:
        record = await self.session.get(s.HouseholdKitchenSettings, household_id)
        allergies = [
            row.label
            for row in await self._all(
                select(s.HouseholdAllergy)
                .where(s.HouseholdAllergy.household_id == household_id)
                .order_by(s.HouseholdAllergy.position, s.HouseholdAllergy.label)
            )
        ]
        switches = {
            row.metric: row.enabled
            for row in await self._all(
                select(s.HouseholdAnalysisMetric).where(
                    s.HouseholdAnalysisMetric.household_id == household_id
                )
            )
        }
        # No rows: never chosen, so every metric is on. A metric added to the
        # catalog after the household chose starts on as well.
        metrics = [m for m in ANALYSIS_METRICS if switches.get(m, True)]
        rules = await self._all(
            select(s.GuidanceRule)
            .where(s.GuidanceRule.household_id == household_id)
            .order_by(s.GuidanceRule.created_at, s.GuidanceRule.id)
        )
        versions = {
            (row.rule_id, row.version): row
            for row in await self._all(
                select(s.GuidanceRuleVersion).where(
                    s.GuidanceRuleVersion.rule_id.in_([r.id for r in rules] or [None])
                )
            )
        }
        guidance = []
        for rule in rules:
            version = versions.get((rule.id, rule.current_version))
            guidance.append(
                {
                    "id": rule.legacy_id or str(rule.id),
                    "title": version.title if version else rule.title,
                    "content": version.content if version else "",
                    "enabled": rule.enabled,
                    "version": rule.current_version,
                }
            )
        if record is None:
            return {"allergies": allergies, "guidance": guidance, "analysisMetrics": metrics}
        return {
            "people": record.people,
            "childAge": _num(record.child_age_months),
            "allergies": allergies,
            "timezone": record.timezone,
            "generateTime": record.generate_time,
            "prepDay": record.prep_day,
            "maxPrepMinutes": _num(record.max_prep_minutes),
            "maxDailyActiveMinutes": _num(record.max_daily_active_minutes),
            "newRecipesPerWeek": record.new_recipes_per_week,
            "recurringMeals": record.recurring_meals or [],
            "recipeRepeatGapDays": record.recipe_repeat_gap_days,
            "guidance": guidance,
            "analysisMetrics": metrics,
            **({"pinnedTags": record.pinned_tags} if record.pinned_tags is not None else {}),
        }

    async def _audit(self, household_id: UUID) -> list[dict[str, Any]]:
        rows = await self._all(
            select(s.KitchenAuditEntry)
            .where(s.KitchenAuditEntry.household_id == household_id)
            .order_by(s.KitchenAuditEntry.sequence, s.KitchenAuditEntry.at)
        )
        if not rows:
            return []
        deltas = _group(
            await self._all(
                select(s.InventoryLedgerEntry)
                .where(s.InventoryLedgerEntry.audit_id.in_([row.id for row in rows]))
                .order_by(s.InventoryLedgerEntry.sequence, s.InventoryLedgerEntry.id)
            ),
            "audit_id",
        )
        batches = {
            row.id: row.legacy_id or str(row.id)
            for row in await self._all(
                select(s.InventoryBatch).where(s.InventoryBatch.household_id == household_id)
            )
        }
        plans = {
            row.id: row.legacy_id or str(row.id)
            for row in await self._all(
                select(s.WeeklyPlan).where(s.WeeklyPlan.household_id == household_id)
            )
        }
        out = []
        for row in rows:
            entry: dict[str, Any] = {
                "id": row.legacy_id or str(row.id),
                "kind": row.kind,
                "message": row.message,
                "at": row.at.isoformat(),
                "deltas": [
                    {"inventoryId": batches[item.batch_id], "amount": _num(item.delta)}
                    for item in deltas.get(row.id, [])
                    if item.batch_id in batches
                ],
                "undone": row.undone,
            }
            if row.actor_id:
                entry["actorId"] = str(row.actor_id)
            if row.operation_id:
                entry["operationId"] = row.operation_id
            if row.undo is not None:
                entry["undo"] = row.undo
            if row.plan_id in plans:
                entry["planId"] = plans[row.plan_id]
            if row.entity_id:
                entry["entityId"] = row.entity_id
            if row.component_id:
                entry["componentId"] = row.component_id
            out.append(entry)
        return out
