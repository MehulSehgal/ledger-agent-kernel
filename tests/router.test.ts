import { describe, expect, it } from "vitest";
import { assertRouteSafety, resolveRoute } from "../src/kernel/router";

describe("resolveRoute", () => {
  it("enforces local-only routing when routingMode is local-only", () => {
    const decision = resolveRoute({
      routingMode: "local-only",
      classification: "internal",
    });

    expect(decision.target).toBe("local");
    expect(decision.enforcedLocalOnly).toBe(true);
    expect(decision.blockedCloudFallback).toBe(true);
    expect(decision.provider.startsWith("local://")).toBe(true);
  });

  it("blocks cloud fallback for confidential classification even in auto mode", () => {
    const decision = resolveRoute({
      routingMode: "auto",
      classification: "confidential",
    });

    expect(decision.target).toBe("local");
    expect(decision.enforcedLocalOnly).toBe(true);
  });

  it("throws when a local-only decision points to a cloud endpoint", () => {
    expect(() =>
      assertRouteSafety({
        target: "local",
        provider: "https://api.openai.com/v1",
        enforcedLocalOnly: true,
        blockedCloudFallback: true,
        reason: "test",
      })
    ).toThrow(/Security violation/);
  });
});
