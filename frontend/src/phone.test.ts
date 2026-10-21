import { describe, expect, it } from "vitest";
import { formatPhoneNumber } from "./phone";

describe("formatPhoneNumber", () => {
  it("formats 10 digits", () => {
    expect(formatPhoneNumber("5552234567")).toBe("(555) 223-4567");
  });

  it("leaves anything else as it is", () => {
    expect(formatPhoneNumber("555223")).toBe("555223");
  });
});
