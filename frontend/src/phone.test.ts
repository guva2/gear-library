import { describe, expect, it } from "vitest";
import { formatPhoneNumber } from "./phone";

describe("formatPhoneNumber", () => {
  it("formats 10 digits", () => {
    expect(formatPhoneNumber("5551234567")).toBe("(555) 123-4567");
  });

  it("leaves anything else as it is", () => {
    expect(formatPhoneNumber("555123")).toBe("555123");
  });
});
