import { BrowserRouter, Link, Navigate, Route, Routes } from "react-router";
import { AuthProvider, RequireAnonymous, RequireAuth } from "./auth";
import { AppLayout, PublicLayout } from "./Layout";
import ConnectionsPage from "./pages/ConnectionsPage";
import DiscoverPage from "./pages/DiscoverPage";
import InventoriesTab from "./pages/InventoriesTab";
import InventoryPage from "./pages/InventoryPage";
import LoansPage from "./pages/LoansPage";
import LoginPage from "./pages/LoginPage";
import ManagePage from "./pages/ManagePage";
import MyItemsTab from "./pages/MyItemsTab";
import RegisterPage from "./pages/RegisterPage";

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
        <Route element={<PublicLayout />}>
          <Route
            path="/login"
            element={
              <RequireAnonymous>
                <LoginPage />
              </RequireAnonymous>
            }
          />
          <Route
            path="/register"
            element={
              <RequireAnonymous>
                <RegisterPage />
              </RequireAnonymous>
            }
          />
          <Route path="*" element={<NotFound />} />
        </Route>
        <Route
          element={
            <RequireAuth>
              <AppLayout />
            </RequireAuth>
          }
        >
          <Route path="/" element={<DiscoverPage />} />
          <Route path="/manage" element={<ManagePage />}>
            <Route index element={<Navigate to="inventories" replace />} />
            <Route path="inventories" element={<InventoriesTab />} />
            <Route path="items" element={<MyItemsTab />} />
          </Route>
          <Route path="/inventories/:id" element={<InventoryPage />} />
          <Route path="/loans" element={<LoansPage />} />
          <Route path="/connections" element={<ConnectionsPage />} />
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
