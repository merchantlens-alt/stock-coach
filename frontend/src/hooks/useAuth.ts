import { useState } from "react";
import { authToken } from "../api/client";
import type { TokenResponse } from "../types";

const API_BASE = "/api";
const USERNAME_KEY = "sc_username";

interface AuthState {
  token: string | null;
  username: string | null;
}

function loadState(): AuthState {
  try {
    return {
      token: localStorage.getItem("sc_token"),
      username: localStorage.getItem(USERNAME_KEY),
    };
  } catch {
    return { token: null, username: null };
  }
}

async function callAuth(endpoint: string, username: string, password: string): Promise<TokenResponse> {
  const resp = await fetch(`${API_BASE}/auth/${endpoint}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  const data = await resp.json().catch(() => ({})) as Record<string, unknown>;
  if (!resp.ok) {
    // FastAPI returns detail as a string for HTTPException, array for validation errors (422)
    const detail = data["detail"];
    let msg: string;
    if (typeof detail === "string") {
      msg = detail;
    } else if (Array.isArray(detail) && detail.length > 0) {
      const first = detail[0] as Record<string, unknown>;
      msg = String(first["msg"] ?? `${endpoint} failed`);
    } else {
      msg = `${endpoint} failed`;
    }
    throw new Error(msg);
  }
  return data as unknown as TokenResponse;
}

function persistToken(data: TokenResponse) {
  authToken.set(data.access_token);
  try { localStorage.setItem(USERNAME_KEY, data.username); } catch { /**/ }
}

export function useAuth() {
  const [state, setState] = useState<AuthState>(loadState);

  async function login(username: string, password: string): Promise<void> {
    const data = await callAuth("login", username, password);
    persistToken(data);
    setState({ token: data.access_token, username: data.username });
  }

  async function register(username: string, password: string): Promise<void> {
    const data = await callAuth("register", username, password);
    persistToken(data);
    setState({ token: data.access_token, username: data.username });
  }

  function logout() {
    authToken.clear();
    try { localStorage.removeItem(USERNAME_KEY); } catch { /**/ }
    setState({ token: null, username: null });
  }

  return {
    token: state.token,
    username: state.username,
    isAuthenticated: !!state.token,
    login,
    register,
    logout,
  };
}
