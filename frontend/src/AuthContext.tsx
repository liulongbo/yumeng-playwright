import { createContext, useContext, useEffect, useMemo, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, setCsrfToken } from "./api";
import type { UserView } from "./types";

interface AuthValue {
  user: UserView | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<UserView>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const me = useQuery({
    queryKey: ["auth", "me"], queryFn: api.me, retry: false,
  });
  const loginMutation = useMutation({
    mutationFn: ({ username, password }: { username: string; password: string }) => api.login(username, password),
    onSuccess: (user) => { setCsrfToken(user.csrf_token); queryClient.setQueryData(["auth", "me"], user); },
  });
  const logoutMutation = useMutation({
    mutationFn: api.logout,
    onSettled: () => { setCsrfToken(""); queryClient.clear(); },
  });

  useEffect(() => { if (me.data) setCsrfToken(me.data.csrf_token); }, [me.data]);
  useEffect(() => {
    const expire = () => queryClient.setQueryData(["auth", "me"], null);
    window.addEventListener("xingtu:auth-expired", expire);
    return () => window.removeEventListener("xingtu:auth-expired", expire);
  }, [queryClient]);

  const value = useMemo<AuthValue>(() => ({
    user: me.data ?? null,
    loading: me.isLoading,
    login: (username, password) => loginMutation.mutateAsync({ username, password }),
    logout: () => logoutMutation.mutateAsync(),
  }), [me.data, me.isLoading, loginMutation, logoutMutation]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside AuthProvider");
  return value;
}
