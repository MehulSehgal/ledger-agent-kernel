import { DataClassification } from "../config/demoScenarios";

export function sanitizeDiffForOutput(
  diff: string | undefined,
  classification: DataClassification
): string | null {
  if (!diff || !diff.trim()) {
    return null;
  }

  if (classification !== "confidential") {
    return diff;
  }

  return diff.replace(
    /(secret\s*=\s*[^\n]*?\|\|\s*)"([^"]+)"/gi,
    '$1"[REDACTED_SECRET]"'
  );
}
