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
  const isLocalOnlyMode = req.routingMode === "local-only";
  const isConfidential = req.classification === "confidential";

  if (isLocalOnlyMode || isConfidential) {
    return {
      target: "local",
      provider: req.localEndpoint || "local://ledger-ollama-runtime",
      enforcedLocalOnly: true,
      blockedCloudFallback: true,
      reason: isConfidential
        ? "Confidential classification locked execution to local runtime"
        : "Explicit local-only routing mode enforced",
    };
  }

  return {
    target: "cloud",
    provider: req.cloudEndpoint || "cloud://frontier-router",
    enforcedLocalOnly: false,
    blockedCloudFallback: false,
    reason: "Standard auto/cloud routing permitted for non-confidential payload",
  };
}

export function assertRouteSafety(decision: RouteDecision): void {
  if (decision.enforcedLocalOnly && !decision.provider.startsWith("local://")) {
    throw new Error(
      `Security violation: local-only route resolved to non-local provider "${decision.provider}"`
    );
  }
}
