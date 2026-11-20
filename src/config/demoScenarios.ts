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

export const CONFIDENTIAL_REPO_DIFF = `diff --git a/src/auth/tokenSigner.ts b/src/auth/tokenSigner.ts
index 4a91c02..8f31d9e 100644
--- a/src/auth/tokenSigner.ts
+++ b/src/auth/tokenSigner.ts
@@ -14,9 +14,12 @@ export function signSessionToken(userId: string, scope: string[]) {
-  const secret = process.env.JWT_FALLBACK_SECRET || "dev-static-secret-991";
-  return jwt.sign({ sub: userId, scope }, secret, { expiresIn: "7d" });
+  const secret = process.env.JWT_SIGNING_KEY;
+  if (!secret) {
+    throw new Error("Missing JWT_SIGNING_KEY in confidential runtime");
+  }
+  return jwt.sign({ sub: userId, scope }, secret, { expiresIn: "15m" });
 }
diff --git a/src/kernel/egressGuard.ts b/src/kernel/egressGuard.ts
index 19bc441..77d20a8 100644
--- a/src/kernel/egressGuard.ts
+++ b/src/kernel/egressGuard.ts
@@ -8,5 +8,8 @@ export function assertEgressAllowed(classification: string, endpoint: string) {
-  return true;
+  if (classification === "confidential" && !endpoint.startsWith("local://")) {
+    throw new Error(\`Blocked external egress to \${endpoint} for confidential repository\`);
+  }
+  return true;
 }`;

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
