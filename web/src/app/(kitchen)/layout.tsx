import { Suspense, type ReactNode } from "react";
import { KitchenRoutes } from "@/features/kitchen/routes";

export default function KitchenLayout({ children }: { children: ReactNode }) {
  return <><Suspense fallback={<div>Loading your kitchen…</div>}><KitchenRoutes/></Suspense>{children}</>;
}
