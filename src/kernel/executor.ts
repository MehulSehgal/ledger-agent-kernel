import { DEFAULT_TOKEN_BUDGET, DemoScenario } from "../config/demoScenarios";
import { sanitizeDiffForOutput } from "./redactor";
import { assertRouteSafety, resolveRoute } from "./router";

export interface LiveReceipt {
  receiptCode: number;
  liveCodeCount: number;
  tokensUsed: number;
  tokenBudget: number;
  routeTarget: "local" | "cloud";
  provider: string;
  enforcedLocalOnly: boolean;
  status: "idle" | "routing" | "running" | "settled";
}

export interface ExecutionOutput {
  scenarioId: DemoScenario["id"];
  summary: string;
  diff: string | null;
  receipt: LiveReceipt;
}

export function createInitialReceipt(
  budget: number = DEFAULT_TOKEN_BUDGET,
  routingMode: DemoScenario["routingMode"] = "auto"
): LiveReceipt {
  const isLocal = routingMode === "local-only";
  return {
    receiptCode: 0,
    liveCodeCount: 0,
    tokensUsed: 0,
    tokenBudget: budget,
    routeTarget: isLocal ? "local" : "cloud",
    provider: isLocal ? "local://ledger-ollama-runtime" : "cloud://frontier-router",
    enforcedLocalOnly: isLocal,
    status: "idle",
  };
}

function boundTextToTokenBudget(text: string, tokenBudget: number): {
  boundedText: string;
  tokensUsed: number;
} {
  const safeBudget = Math.max(1, Math.floor(tokenBudget));
  const maxChars = safeBudget * 4;
  const boundedText =
    text.length > maxChars ? `${text.slice(0, Math.max(0, maxChars - 3))}...` : text;
  const estimatedTokens = Math.min(
    safeBudget,
    Math.max(12, Math.ceil(boundedText.length / 4))
  );
  return { boundedText, tokensUsed: estimatedTokens };
}

export async function runScenarioWithLiveReceipt(
  scenario: DemoScenario,
  budgetOverride: number | undefined,
  onReceiptUpdate?: (next: LiveReceipt) => void,
  stepDelayMs: number = 120
): Promise<ExecutionOutput> {
  const effectiveBudget =
    budgetOverride !== undefined && budgetOverride > 0
      ? budgetOverride
      : scenario.tokenBudget || DEFAULT_TOKEN_BUDGET;

  const route = resolveRoute({
    routingMode: scenario.routingMode,
    classification: scenario.classification,
  });
  assertRouteSafety(route);

  const sanitizedDiff = sanitizeDiffForOutput(
    scenario.repositoryDiff,
    scenario.classification
  );
  const diffLines = sanitizedDiff ? sanitizedDiff.split("\n").length : 0;

  let receipt: LiveReceipt = {
    receiptCode: 102,
    liveCodeCount: diffLines > 0 ? diffLines : 4,
    tokensUsed: Math.min(14, effectiveBudget),
    tokenBudget: effectiveBudget,
    routeTarget: route.target,
    provider: route.provider,
    enforcedLocalOnly: route.enforcedLocalOnly,
    status: "routing",
  };
  onReceiptUpdate?.({ ...receipt });

  if (stepDelayMs > 0) {
    await new Promise((resolve) => setTimeout(resolve, stepDelayMs));
  }

  const rawSummaryByScenario: Record<DemoScenario["id"], string> = {
    "board-prep":
      "Board prep signal brief: Q4 enterprise retention reached 118% NRR; deterministic receipt verification reduced audit review overhead by 41%.",
    "market-scan":
      "Market scan evidence: Regulated teams increasingly require verifiable local-first execution receipts and strict per-run token budgets.",
    "private-review":
      "Confidential audit passed on local runtime: removed static JWT fallback secret, enforced 15m TTL, and blocked non-local egress.",
  };

  const { boundedText, tokensUsed } = boundTextToTokenBudget(
    rawSummaryByScenario[scenario.id],
    effectiveBudget
  );

  const finalLiveCodeCount =
    diffLines > 0 ? diffLines : Math.max(6, boundedText.split(/[.!?]+/).filter(Boolean).length * 3);

  receipt = {
    ...receipt,
    receiptCode: 104,
    liveCodeCount: finalLiveCodeCount,
    tokensUsed: Math.max(receipt.tokensUsed, Math.floor(tokensUsed * 0.7)),
    status: "running",
  };
  onReceiptUpdate?.({ ...receipt });

  if (stepDelayMs > 0) {
    await new Promise((resolve) => setTimeout(resolve, stepDelayMs));
  }

  receipt = {
    ...receipt,
    receiptCode: 200,
    liveCodeCount: finalLiveCodeCount,
    tokensUsed,
    tokenBudget: effectiveBudget,
    status: "settled",
  };
  onReceiptUpdate?.({ ...receipt });

  return {
    scenarioId: scenario.id,
    summary: boundedText,
    diff: sanitizedDiff,
    receipt: { ...receipt },
  };
}
