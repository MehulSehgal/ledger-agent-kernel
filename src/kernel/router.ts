import { DataClassification, RoutingMode } from "../config/demoScenarios";

export interface RouteRequest {
  routingMode: RoutingMode;
  classification: DataClassification;
  localEndpoint?: string;
  cloudEndpoint?: string;
}

export interface RouteDecision {
  target: "local" | "cloud";
  provider: string;
  enforcedLocalOnly: boolean;
  blockedCloudFallback: boolean;
  reason: string;
}

export function resolveRoute(req: RouteRequest): RouteDecision {
  if (req.routingMode === "local-only") {
    return {
      target: "local",
      provider: req.localEndpoint || "local://ledger-ollama-runtime",
      enforcedLocalOnly: true,
      blockedCloudFallback: true,
      reason: "Explicit local-only routing mode enforced",
    };
  }

  return {
    target: "cloud",
    provider: req.cloudEndpoint || "cloud://frontier-router",
    enforcedLocalOnly: false,
    blockedCloudFallback: false,
    reason: "Standard auto/cloud routing permitted",
  };
}
