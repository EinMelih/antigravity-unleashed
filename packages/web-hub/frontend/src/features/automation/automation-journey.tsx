const steps = [
  "Idee beschreiben",
  "Plan prüfen",
  "PRs in Reihenfolge umsetzen",
  "Mensch prüft & merged",
] as const;

export function AutomationJourney() {
  return (
    <section
      aria-label="Ablauf von der Idee zur Prüfung"
      className="automation-journey"
    >
      <ol>
        {steps.map((step, index) => (
          <li key={step}>
            <span aria-hidden="true" className="automation-journey-number">
              {index + 1}
            </span>
            <strong>{step}</strong>
            {index < steps.length - 1 ? (
              <span aria-hidden="true" className="automation-journey-arrow">
                →
              </span>
            ) : null}
          </li>
        ))}
      </ol>
    </section>
  );
}
