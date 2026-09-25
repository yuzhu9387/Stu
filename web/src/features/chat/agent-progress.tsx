import { getCatalog, type Locale } from "@/i18n/catalog";

type AgentStage = "understanding" | "planning" | "acting" | "checking" | "continuing";
type CompletedAction = "checkedHouseholdRecipes" | "savedRecipe" | "createdPlan";

interface AgentProgress {
  stage: AgentStage;
  completedActions: CompletedAction[];
  result?: string;
}

interface AgentProgressViewProps {
  locale: Locale;
  progress: AgentProgress;
}

const stages: AgentStage[] = ["understanding", "planning", "acting", "checking", "continuing"];

export function AgentProgressView({ locale, progress }: AgentProgressViewProps) {
  const catalog = getCatalog(locale);
  const activeIndex = stages.indexOf(progress.stage);

  return (
    <section className="agent-progress" aria-label="Agent progress">
      <ol>
        {stages.map((stage, index) => (
          <li className={index <= activeIndex ? "complete" : "pending"} key={stage}>
            <span aria-hidden="true">{index < activeIndex ? "✓" : index + 1}</span>
            {catalog.progress[stage]}
          </li>
        ))}
      </ol>
      {progress.completedActions.map((action) => (
        <p className="action-receipt" key={action}>
          <span aria-hidden="true">✓ </span>
          {catalog.progress[action]}
        </p>
      ))}
      {progress.result ? <p className="agent-result">{progress.result}</p> : null}
    </section>
  );
}
