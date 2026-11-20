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

export function boundTextToTokenBudget(text: string, tokenBudget: number): {
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
  budgetOverride?: number
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
  const { boundedText, tokensUsed } = boundTextToTokenBudget(
    scenario.prompt,
    effectiveBudget
  );

  const receipt: LiveReceipt = {
    receiptCode: 200,
    liveCodeCount: sanitizedDiff ? sanitizedDiff.split("\n").length : 6,
    tokensUsed,
    tokenBudget: effectiveBudget,
    routeTarget: route.target,
    provider: route.provider,
    enforcedLocalOnly: route.enforcedLocalOnly,
    status: "settled",
  };

  return {
    scenarioId: scenario.id,
    summary: boundedText,
    diff: sanitizedDiff,
    receipt,
  };
}
