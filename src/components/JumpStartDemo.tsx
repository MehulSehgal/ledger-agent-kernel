import React, { useState } from "react";
import {
  DEFAULT_TOKEN_BUDGET,
  DEMO_SCENARIOS,
  DemoScenario,
} from "../config/demoScenarios";
import {
  createInitialReceipt,
  ExecutionOutput,
  LiveReceipt,
  runScenarioWithLiveReceipt,
} from "../kernel/executor";
import "./JumpStartDemo.css";

export function JumpStartDemo() {
  const [selectedId, setSelectedId] = useState<DemoScenario["id"]>("board-prep");
  const [tokenBudget, setTokenBudget] = useState<number>(DEFAULT_TOKEN_BUDGET);
  const [isRunning, setIsRunning] = useState<boolean>(false);
  const [receipt, setReceipt] = useState<LiveReceipt>(() =>
    createInitialReceipt(DEFAULT_TOKEN_BUDGET, "auto")
  );
  const [output, setOutput] = useState<ExecutionOutput | null>(null);

  const activeScenario =
    DEMO_SCENARIOS.find((item) => item.id === selectedId) ?? DEMO_SCENARIOS[0];

  async function handleSelectScenario(scenario: DemoScenario) {
    setSelectedId(scenario.id);
    setIsRunning(true);
    setReceipt(createInitialReceipt(tokenBudget, scenario.routingMode));

    try {
      const result = await runScenarioWithLiveReceipt(
        scenario,
        tokenBudget,
        (liveTick) => setReceipt({ ...liveTick })
      );
      setReceipt({ ...result.receipt });
      setOutput(result);
    } finally {
      setIsRunning(false);
    }
  }

  function handleBudgetChange(rawValue: string) {
    const parsed = Number(rawValue);
    const nextBudget =
      Number.isFinite(parsed) && parsed > 0 ? Math.floor(parsed) : DEFAULT_TOKEN_BUDGET;
    setTokenBudget(nextBudget);
    setReceipt((prev) => ({
      ...prev,
      tokenBudget: nextBudget,
    }));
  }

  return (
    <section className="jumpstart-demo" aria-label="Jump-start a demo">
      <header className="jumpstart-header">
        <div>
          <p className="jumpstart-eyebrow">JUMP-START A DEMO</p>
          <h2>Choose a scenario and see the receipt update in real time.</h2>
        </div>

        <div className="budget-control">
          <label htmlFor="token-budget-input">Token Budget</label>
          <div className="budget-input-row">
            <input
              id="token-budget-input"
              type="number"
              min={10}
              max={8192}
              value={tokenBudget}
              onChange={(e) => handleBudgetChange(e.target.value)}
            />
            <button
              type="button"
              className="budget-reset-btn"
              onClick={() => handleBudgetChange(String(DEFAULT_TOKEN_BUDGET))}
            >
              Default (100)
            </button>
          </div>
        </div>
      </header>

      <div className="scenario-grid" role="group" aria-label="Demo scenarios">
        {DEMO_SCENARIOS.map((sc) => {
          const isSelected = sc.id === selectedId;
          const icon =
            sc.id === "board-prep" ? "↗" : sc.id === "market-scan" ? "◎" : "⌁";

          return (
            <button
              key={sc.id}
              type="button"
              className={`scenario-card ${isSelected ? "is-selected" : ""}`}
              aria-pressed={isSelected}
              disabled={isRunning}
              onClick={() => handleSelectScenario(sc)}
            >
              <span className="scenario-title">
                <span aria-hidden="true">{icon}</span> {sc.label}
              </span>
              <span className="scenario-subtitle">{sc.subtitle}</span>
              {sc.routingMode === "local-only" && (
                <span className="scenario-badge">Local-only enforced</span>
              )}
            </button>
          );
        })}
      </div>

      <div className="demo-workspace">
        <aside className="live-receipt-panel" aria-label="Live receipt">
          <div className="panel-heading">
            <h3>Live Receipt</h3>
            <span className={`status-pill status-${receipt.status}`}>
              {receipt.status.toUpperCase()}
            </span>
          </div>

          <dl className="receipt-metrics">
            <div>
              <dt>Receipt Code</dt>
              <dd data-testid="receipt-code">{receipt.receiptCode}</dd>
            </div>
            <div>
              <dt>Live Code</dt>
              <dd data-testid="live-code-count">{receipt.liveCodeCount}</dd>
            </div>
            <div>
              <dt>Tokens Used</dt>
              <dd data-testid="tokens-used">
                {receipt.tokensUsed} / {receipt.tokenBudget}
              </dd>
            </div>
            <div>
              <dt>Routing Mode</dt>
              <dd data-testid="route-target">
                {receipt.routeTarget} ({receipt.enforcedLocalOnly ? "local-only" : "auto"})
              </dd>
            </div>
            <div>
              <dt>Runtime Provider</dt>
              <dd className="mono">{receipt.provider}</dd>
            </div>
          </dl>
        </aside>

        <div className="output-panel" aria-label="Execution output">
          <div className="panel-heading">
            <h3>
              Output • {activeScenario.label}
              {activeScenario.repositoryName ? ` (${activeScenario.repositoryName})` : ""}
            </h3>
          </div>

          {!output ? (
            <p className="output-placeholder">
              Select a scenario above to execute the kernel and stream live receipt telemetry.
            </p>
          ) : (
            <>
              <p className="output-summary">{output.summary}</p>

              {output.diff && (
                <div className="diff-container" data-testid="confidential-diff">
                  <div className="diff-header">
                    <span>Confidential Repository Diff</span>
                    <span>{output.diff.split("\n").length} lines</span>
                  </div>
                  <pre className="diff-viewer">
                    <code>
                      {output.diff.split("\n").map((line, idx) => {
                        const lineClass = line.startsWith("+") && !line.startsWith("+++")
                          ? "diff-add"
                          : line.startsWith("-") && !line.startsWith("---")
                          ? "diff-del"
                          : line.startsWith("@@") || line.startsWith("diff --git")
                          ? "diff-hunk"
                          : "";
                        return (
                          <span key={idx} className={`diff-line ${lineClass}`}>
                            {line}
                            {"\n"}
                          </span>
                        );
                      })}
                    </code>
                  </pre>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </section>
  );
}
