import { useEffect, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { Radar } from "lucide-react";
import { api } from "./types";

type AuthStatus = { required: boolean; authenticated: boolean };

// Pide el PIN de APP_PIN antes de mostrar la app; el backend deja una cookie de sesión.
export default function PinGate({ children }: { children: ReactNode }) {
  const [ok, setOk] = useState<boolean | null>(null);
  const [pin, setPin] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api<AuthStatus>("/auth/status")
      .then((s) => setOk(!s.required || s.authenticated))
      .catch(() => setOk(true)); // Sin API la propia app ya muestra el error de conexión.
  }, []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api("/auth/login", { method: "POST", body: JSON.stringify({ pin }) });
      setOk(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "PIN incorrecto");
      setPin("");
    } finally {
      setBusy(false);
    }
  }

  if (ok === null) return null;
  if (ok) return <>{children}</>;
  return (
    <div className="pin-gate">
      <form className="pin-card" onSubmit={submit}>
        <Radar size={28} />
        <h1>Radar de contenido</h1>
        <p>Introduce el PIN de acceso</p>
        <input
          autoFocus
          inputMode="numeric"
          autoComplete="one-time-code"
          maxLength={6}
          value={pin}
          onChange={(e) => setPin(e.target.value.replace(/\D/g, ""))}
          placeholder="••••••"
          aria-label="PIN"
        />
        {error && <small className="pin-error">{error}</small>}
        <button type="submit" disabled={busy || pin.length < 4}>
          Entrar
        </button>
      </form>
    </div>
  );
}
