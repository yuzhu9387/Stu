"""Adapt existing full-week test proposals to the compact bootstrap wire contract."""

import json
from copy import deepcopy


def compact_fixture(output):
    templates, by_content, days = [], {}, {}
    for meal in output["plan"]["meals"]:
        template = {
            "components": [
                {
                    "source": "prep"
                    if c.get("prepId")
                    else "inventory"
                    if c.get("inventoryId")
                    else "fresh",
                    **{
                        key: c[key]
                        for key in ("recipeId", "inventoryId", "portions")
                        if c.get(key) is not None
                    },
                }
                for c in meal["components"]
            ],
            "activeMinutes": meal["activeMinutes"],
            "elapsedMinutes": meal["elapsedMinutes"],
            "steps": meal["steps"],
        }
        key = json.dumps(template, sort_keys=True)
        if key not in by_content:
            identifier = f"t{len(templates)}"
            by_content[key] = identifier
            templates.append({"id": identifier, **template})
        days.setdefault(meal["day"], {})[meal["slot"]] = by_content[key]
    return {
        "recipes": deepcopy(output["recipes"]),
        "mealTemplates": templates,
        "days": [days[key] for key in sorted(days)],
    }
