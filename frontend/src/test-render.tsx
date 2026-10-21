import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { expect } from "vitest";
import { MemoryRouter, useLocation, useNavigationType } from "react-router";
import { AppRoutes } from "./App";

/**
 * Renders the app at `path`. The returned `location` gives the current path and query, and
 * how the router last got there (`PUSH`, `REPLACE` or `POP`).
 */
export function renderAt(path: string) {
  const seen = { path, navigation: "POP" };
  function LocationProbe() {
    const location = useLocation();
    seen.path = location.pathname + location.search;
    seen.navigation = useNavigationType();
    return null;
  }
  render(
    <MemoryRouter initialEntries={[path]}>
      <AppRoutes />
      <LocationProbe />
    </MemoryRouter>,
  );
  return { location: () => ({ ...seen }) };
}

export function fillIn(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

/** Each button's accessible name starts with its visible text (WCAG 2.5.3, label in name). */
export function expectLabelsInNames(container: HTMLElement) {
  const buttons = within(container).getAllByRole("button");
  const names = buttons.map((button) => button.getAttribute("aria-label") ?? button.textContent);
  const prefixes = buttons.map((button, index) =>
    names[index]?.slice(0, button.textContent?.length),
  );
  expect(prefixes).toEqual(buttons.map((button) => button.textContent));
}

/** Lets replies already answered finish, for a test that checks nothing changed. */
export function settle() {
  return act(() => new Promise<void>((resolve) => setTimeout(resolve, 30)));
}
