import type { ReactNode } from "react";
import { useAuth } from "./AuthContext";
import LoginPage from "./LoginPage";

export default function RequireAuth({ children }: { children: ReactNode }) {
  const { isAuthenticated, loading } = useAuth();

  if (loading) return null;
  if (!isAuthenticated) return <LoginPage />;

  return <>{children}</>;
}
