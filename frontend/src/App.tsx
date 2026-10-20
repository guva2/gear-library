import { BrowserRouter, Link, Outlet, Route, Routes } from "react-router";
import { AuthProvider, RequireAuth } from "./auth";
import ConnectionsPage from "./pages/ConnectionsPage";
import HomePage from "./pages/HomePage";
import InventoryPage from "./pages/InventoryPage";
import LoginPage from "./pages/LoginPage";
import RegisterPage from "./pages/RegisterPage";

function Layout() {
  return (
    <main>
      <h1>Gear Library</h1>
      <Outlet />
    </main>
  );
}

function NotFound() {
  return (
    <p>
      Page not found. <Link to="/">Go home</Link>
    </p>
  );
}

export function AppRoutes() {
  return (
    <AuthProvider>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/register" element={<RegisterPage />} />
          <Route
            path="/"
            element={
              <RequireAuth>
                <HomePage />
              </RequireAuth>
            }
          />
          <Route
            path="/inventories/:id"
            element={
              <RequireAuth>
                <InventoryPage />
              </RequireAuth>
            }
          />
          <Route
            path="/connections"
            element={
              <RequireAuth>
                <ConnectionsPage />
              </RequireAuth>
            }
          />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
    </AuthProvider>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AppRoutes />
    </BrowserRouter>
  );
}
