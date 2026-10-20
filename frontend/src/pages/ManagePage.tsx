import { NavLink, Outlet } from "react-router";

/**
 * The Manage tabs. Each tab is its own URL, so the tabs are links in a `nav`, and the
 * router marks the open one with `aria-current="page"`.
 */
export default function ManagePage() {
  return (
    <>
      <h2>Manage</h2>
      <nav aria-label="Manage" className="tabs">
        <ul>
          <li>
            <NavLink to="/manage/inventories">Inventories</NavLink>
          </li>
          <li>
            <NavLink to="/manage/items">My items</NavLink>
          </li>
        </ul>
      </nav>
      <Outlet />
    </>
  );
}
