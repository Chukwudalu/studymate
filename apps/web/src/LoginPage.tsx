import { useState, type FormEvent } from "react";
import { login, signup, resetPassword } from "./api";
import { useAuth } from "./AuthContext";

type Mode = "signin" | "signup" | "reset";

export default function LoginPage() {
  const [mode, setMode] = useState<Mode>("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [resetDone, setResetDone] = useState(false);
  const { signIn } = useAuth();

  function switchMode(next: Mode) {
    setMode(next);
    setError(null);
    setPassword("");
    setConfirmPassword("");
    setResetDone(false);
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);

    try {
      if (mode === "signin") {
        await login(email, password);
        signIn();
      } else if (mode === "signup") {
        await signup(email, password);
        signIn();
      } else {
        await resetPassword(email, password, confirmPassword);
        switchMode("signin");
        setResetDone(true);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setSubmitting(false);
    }
  }

  const titles: Record<Mode, string> = {
    signin: "Welcome back",
    signup: "Create an account",
    reset: "Reset your password",
  };
  const ledes: Record<Mode, string> = {
    signin: "Sign in to see your lectures.",
    signup: "Sign up to start turning lectures into notes, flashcards, and quizzes.",
    reset: "Enter your email and a new password.",
  };

  return (
    <div className="wrap">
      <section className="card">
        <div>
          <h1 className="display">{titles[mode]}</h1>
          <p className="lede">{ledes[mode]}</p>
        </div>

        <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <label>
            Email
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoComplete="email"
            />
          </label>
          <label>
            {mode === "reset" ? "New password" : "Password"}
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={8}
              autoComplete={mode === "signin" ? "current-password" : "new-password"}
            />
          </label>
          {mode === "reset" && (
            <label>
              Confirm new password
              <input
                type="password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                required
                minLength={8}
                autoComplete="new-password"
              />
            </label>
          )}

          <button className="btn btn-primary" type="submit" disabled={submitting}>
            {submitting
              ? "Please wait…"
              : mode === "signin"
              ? "Sign in"
              : mode === "signup"
              ? "Sign up"
              : "Reset password"}
          </button>
        </form>

        {mode === "signin" && (
          <>
            <button className="btn btn-ghost" type="button" onClick={() => switchMode("signup")}>
              Need an account? Sign up
            </button>
            <button className="btn btn-ghost" type="button" onClick={() => switchMode("reset")}>
              Forgot password?
            </button>
          </>
        )}
        {mode === "signup" && (
          <button className="btn btn-ghost" type="button" onClick={() => switchMode("signin")}>
            Already have an account? Sign in
          </button>
        )}
        {mode === "reset" && (
          <button className="btn btn-ghost" type="button" onClick={() => switchMode("signin")}>
            Back to sign in
          </button>
        )}

        {resetDone && mode === "signin" && (
          <div className="lede">Password updated — sign in with your new password.</div>
        )}
        {error && <div className="error-box">{error}</div>}
      </section>
    </div>
  );
}
