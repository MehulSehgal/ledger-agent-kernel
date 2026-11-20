import React, { useState } from "react";
import {
  DEFAULT_TOKEN_BUDGET,
  DEMO_SCENARIOS,
  DemoScenario,
} from "../config/demoScenarios";

export function JumpStartDemo() {
  const [selectedId, setSelectedId] = useState<DemoScenario["id"]>("board-prep");
  const [tokenBudget, setTokenBudget] = useState<number>(DEFAULT_TOKEN_BUDGET);

  return (
    <section className="jumpstart-demo">
      <label htmlFor="token-budget-input">Token Budget</label>
      <input
        id="token-budget-input"
        type="number"
        value={tokenBudget}
        onChange={(e) => setTokenBudget(Number(e.target.value) || DEFAULT_TOKEN_BUDGET)}
      />
      <div>
        {DEMO_SCENARIOS.map((sc) => (
          <button key={sc.id} type="button" onClick={() => setSelectedId(sc.id)}>
            {sc.label} ({selectedId === sc.id ? "active" : sc.subtitle})
          </button>
        ))}
      </div>
    </section>
  );
}
