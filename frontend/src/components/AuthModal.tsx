"use client";

import React, { useState } from "react";
import { useAuth } from "./AuthContext";
import { X, Mail, Lock, AlertCircle, Loader2 } from "lucide-react";

export function AuthModal() {
  const { isAuthModalOpen, closeAuthModal, modalMode, setModalMode, login, register } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  if (!isAuthModalOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    // Gmail regex check
    const gmailRegex = /^[a-zA-Z0-9._%+-]+@gmail\.com$/i;
    if (!gmailRegex.test(email.trim())) {
      setError("Please enter a valid Gmail address (e.g. yourname@gmail.com)");
      return;
    }

    if (password.length < 6) {
      setError("Password must be at least 6 characters long.");
      return;
    }

    setLoading(true);
    try {
      if (modalMode === "login") {
        await login(email.trim(), password);
      } else {
        await register(email.trim(), password);
      }
      setEmail("");
      setPassword("");
    } catch (err: any) {
      setError(err.message || "Authentication failed. Please verify credentials.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-ink/70 backdrop-blur-sm animate-fade-in">
      <div className="relative w-full max-w-md bg-paper border border-ink/20 rounded-2xl shadow-2xl p-6 sm:p-8 text-ink">
        <button
          onClick={closeAuthModal}
          className="absolute top-4 right-4 p-1.5 rounded-lg text-ink/50 hover:text-ink hover:bg-ink/5 transition-colors"
        >
          <X className="w-5 h-5" />
        </button>

        <div className="mb-6">
          <div className="inline-flex items-center gap-2 px-2.5 py-1 rounded-full text-xs font-mono font-medium bg-butter/30 text-ink mb-2">
            <span>Powered by Neon PostgreSQL</span>
          </div>
          <h2 className="text-2xl font-display font-bold">
            {modalMode === "login" ? "Welcome back" : "Create your account"}
          </h2>
          <p className="text-sm text-ink/70 mt-1">
            {modalMode === "login"
              ? "Sign in with your @gmail.com account"
              : "Register using your @gmail.com address"}
          </p>
        </div>

        {error && (
          <div className="mb-4 p-3 rounded-xl bg-danger/10 border border-danger/20 flex items-start gap-2.5 text-danger text-sm">
            <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
            <span>{error}</span>
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-xs font-mono font-medium text-ink/70 mb-1.5">
              Gmail Address
            </label>
            <div className="relative">
              <Mail className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-ink/40" />
              <input
                type="email"
                required
                placeholder="developer@gmail.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="w-full pl-10 pr-4 py-2.5 rounded-xl border border-ink/20 bg-white/70 focus:bg-white focus:outline-none focus:ring-2 focus:ring-indigo/40 focus:border-indigo text-sm font-sans placeholder:text-ink/30 transition-all"
              />
            </div>
            <p className="text-[11px] text-ink/50 mt-1 font-mono">Must match: *@gmail.com</p>
          </div>

          <div>
            <label className="block text-xs font-mono font-medium text-ink/70 mb-1.5">
              Password
            </label>
            <div className="relative">
              <Lock className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-ink/40" />
              <input
                type="password"
                required
                placeholder="••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full pl-10 pr-4 py-2.5 rounded-xl border border-ink/20 bg-white/70 focus:bg-white focus:outline-none focus:ring-2 focus:ring-indigo/40 focus:border-indigo text-sm font-sans placeholder:text-ink/30 transition-all"
              />
            </div>
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full py-2.5 px-4 rounded-xl font-medium text-sm text-white bg-ink hover:bg-ink/90 active:scale-[0.99] transition-all flex items-center justify-center gap-2 disabled:opacity-50 shadow-md"
          >
            {loading && <Loader2 className="w-4 h-4 animate-spin" />}
            {modalMode === "login" ? "Sign In" : "Register Account"}
          </button>
        </form>

        <div className="mt-6 pt-4 border-t border-ink/10 text-center text-xs text-ink/70">
          {modalMode === "login" ? (
            <p>
              Don't have an account yet?{" "}
              <button
                type="button"
                onClick={() => {
                  setError(null);
                  setModalMode("register");
                }}
                className="font-medium text-indigo underline hover:text-indigo/80 ml-1"
              >
                Sign up
              </button>
            </p>
          ) : (
            <p>
              Already have an account?{" "}
              <button
                type="button"
                onClick={() => {
                  setError(null);
                  setModalMode("login");
                }}
                className="font-medium text-indigo underline hover:text-indigo/80 ml-1"
              >
                Sign in
              </button>
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
