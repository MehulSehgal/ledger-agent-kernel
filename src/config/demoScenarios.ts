export type RoutingMode = "auto" | "local-only" | "cloud";
export type DataClassification = "public" | "internal" | "confidential";

export const DEFAULT_TOKEN_BUDGET = 100;

export interface DemoScenario {
  id: "board-prep" | "market-scan" | "private-review";
  label: string;
  subtitle: string;
  routingMode: RoutingMode;
  classification: DataClassification;
  tokenBudget: number;
  prompt: string;
  repositoryName?: string;
  repositoryDiff?: string;
}

export const DEMO_SCENARIOS: DemoScenario[] = [
  {
    id: "board-prep",
    label: "Board prep",
    subtitle: "Company signal brief",
    routingMode: "auto",
    classification: "internal",
    tokenBudget: DEFAULT_TOKEN_BUDGET,
    prompt: "Generate a concise Q4 company signal brief for board prep.",
  },
  {
    id: "market-scan",
    label: "Market scan",
    subtitle: "Fresh evidence window",
    routingMode: "auto",
    classification: "public",
    tokenBudget: DEFAULT_TOKEN_BUDGET,
    prompt: "Summarize fresh market evidence across enterprise agent runtimes.",
  },
  {
    id: "private-review",
    label: "Private review",
    subtitle: "Confidential repository • Local-only",
    routingMode: "local-only",
    classification: "confidential",
    tokenBudget: DEFAULT_TOKEN_BUDGET,
    prompt: "Audit the confidential repository diff for auth and egress regressions.",
  },
];
