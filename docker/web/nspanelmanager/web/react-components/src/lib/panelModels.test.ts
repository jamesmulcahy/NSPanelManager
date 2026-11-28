import { describe, expect, it } from "vitest";
import { hasFeature, isKnownModel, KNOWN_MODELS } from "./panelModels";

describe("panelModels", () => {
  it("knows the three models and not the server's placeholder", () => {
    expect(KNOWN_MODELS).toEqual(["sonoff", "custom", "waveshare_p4"]);
    for (const model of KNOWN_MODELS) {
      expect(isKnownModel(model)).toBe(true);
    }
    expect(isKnownModel("unknown")).toBe(false);
    expect(isKnownModel(undefined)).toBe(false);
  });

  it("reads features from the status, and treats a missing list as none", () => {
    expect(hasFeature({ features: ["no_tft"] }, "no_tft")).toBe(true);
    expect(hasFeature({ features: ["no_tft"] }, "no_relays")).toBe(false);
    expect(hasFeature({}, "no_tft")).toBe(false);
  });
});
