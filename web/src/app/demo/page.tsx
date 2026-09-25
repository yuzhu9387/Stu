import { Suspense } from "react";
import { KitchenWorkspace } from "@/features/kitchen/workspace";

export default function Page() {
  return <Suspense fallback={<div>Loading your kitchen…</div>}><KitchenWorkspace demo/></Suspense>;
}
