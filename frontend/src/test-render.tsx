import { fireEvent, render, screen } from "@testing-library/react";
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
