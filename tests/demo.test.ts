import { describe, expect, it } from "vitest";
import {
  DEFAULT_TOKEN_BUDGET,
  DEMO_SCENARIOS,
} from "../src/config/demoScenarios";
import {
  createInitialReceipt,
  LiveReceipt,
  runScenarioWithLiveReceipt,
} from "../src/kernel/executor";

describe("Jump-Start Demo Execution", () => {
  it("defaults token budget to 100 across initial receipt and all scenarios", () => {
    expect(DEFAULT_TOKEN_BUDGET).toBe(100);
    expect(createInitialReceipt().tokenBudget).toBe(100);
    for (const sc of DEMO_SCENARIOS) {
      expect(sc.tokenBudget).toBe(100);
    }
  });

  it("emits non-zero live receipt and live code counts that persist after settling", async () => {
    const ticks: LiveReceipt[] = [];
    const boardPrep = DEMO_SCENARIOS.find((s) => s.id === "board-prep")!;

    const result = await runScenarioWithLiveReceipt(
      boardPrep,
      undefined,
      (tick) => ticks.push(tick),
      0
    );

    expect(ticks.length).toBeGreaterThanOrEqual(3);
    expect(result.receipt.receiptCode).toBe(200);
    expect(result.receipt.liveCodeCount).toBeGreaterThan(0);
    expect(result.receipt.tokensUsed).toBeGreaterThan(0);
    expect(result.receipt.tokensUsed).toBeLessThanOrEqual(100);
  });

  it("routes Private review strictly local-only and outputs sanitized repository diff", async () => {
    const privateReview = DEMO_SCENARIOS.find((s) => s.id === "private-review")!;
    const result = await runScenarioWithLiveReceipt(
      privateReview,
      undefined,
      undefined,
      0
    );

    expect(result.receipt.routeTarget).toBe("local");
    expect(result.receipt.enforcedLocalOnly).toBe(true);
    expect(result.diff).toBeTruthy();
    expect(result.diff).toContain("diff --git a/src/auth/tokenSigner.ts");
    expect(result.diff).toContain("[REDACTED_SECRET]");
  });
});
