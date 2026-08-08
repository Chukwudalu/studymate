import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { checkAuth, logout as apiLogout } from "./api";

interface AuthContextValue {
  isAuthenticated: boolean;
  loading: boolean;
  signIn: () => void;
  signOut: () => void;
}

const AuthContext = createContext<AuthContextValue>({
  isAuthenticated: false,
  loading: true,
  signIn: () => {},
  signOut: () => {},
});

export function AuthProvider({ children }: { children: ReactNode }) {
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    checkAuth()
      .then(setIsAuthenticated)
      .finally(() => setLoading(false));
  }, []);

  function signIn() {
    setIsAuthenticated(true);
  }

  function signOut() {
    apiLogout().finally(() => setIsAuthenticated(false));
  }

  return (
    <AuthContext.Provider value={{ isAuthenticated, loading, signIn, signOut }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
