"use client";
import { usePathname } from "next/navigation";
import { KitchenWorkspace } from "./workspace";
import type { Page } from "./types";

const routes: Record<string, Page> = {
  "/plan": "plan", "/calendar": "calendar", "/fridge": "fridge", "/recipes": "recipes",
  "/guidance": "guidance", "/knowledge": "knowledge", "/prep": "prep",
};

/** Mounted once by the shared layout; only the visible page changes. */
export function KitchenRoutes() {
  const pathname = usePathname();
  // A recipe's own page lives under the library: /recipes/<id> (or /recipes/new).
  const recipe = pathname?.match(/^\/recipes\/([^/]+)$/);
  if (recipe) return <KitchenWorkspace initialPage="recipes" recipeId={decodeURIComponent(recipe[1])}/>;
  return <KitchenWorkspace initialPage={routes[pathname ?? ""] ?? "calendar"}/>;
}
