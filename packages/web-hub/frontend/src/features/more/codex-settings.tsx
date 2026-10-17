import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, ExternalLink, LoaderCircle, LogIn, LogOut, RefreshCw, X } from "lucide-react";
import { useEffect, useState } from "react";

import {
  cancelCodexLogin,
  getCodexModels,
  getCodexStatus,
  logoutCodex,
  startCodexLogin,
} from "@/features/more/api";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

export function CodexSettings() {
  const queryClient = useQueryClient();
  const [login, setLogin] = useState<{ loginId: string; authUrl: string }>();
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const status = useQuery({
    queryKey: ["codex", "status"],
    queryFn: getCodexStatus,
    retry: false,
    refetchInterval: login ? 2_000 : 15_000,
  });
  const models = useQuery({
    queryKey: ["codex", "models"],
    queryFn: getCodexModels,
    enabled: Boolean(status.data?.authenticated),
    retry: false,
  });

  useEffect(() => {
    if (status.data?.authenticated && login) {
      const timeoutId = window.setTimeout(() => {
        setLogin(undefined);
        void queryClient.invalidateQueries({ queryKey: ["antigravity-models"] });
        void queryClient.invalidateQueries({ queryKey: ["codex", "models"] });
      }, 0);

      return () => window.clearTimeout(timeoutId);
    }
  }, [login, queryClient, status.data?.authenticated]);

  async function perform(label: string, operation: () => Promise<void>) {
    setBusy(label);
    setError("");
    try {
      await operation();
    } catch (operationError) {
      setError(operationError instanceof Error ? operationError.message : String(operationError));
    } finally {
      setBusy("");
    }
  }

  async function beginLogin() {
    await perform("login", async () => {
      const result = await startCodexLogin();
      setLogin({ loginId: result.login_id, authUrl: result.auth_url });
      window.open(result.auth_url, "_blank", "noopener,noreferrer");
    });
  }

  async function cancelLogin() {
    if (!login) return;
    await perform("cancel", async () => {
      await cancelCodexLogin(login.loginId);
      setLogin(undefined);
    });
  }

  const connected = Boolean(status.data?.authenticated);
  const available = status.data?.available !== false;
  return (
    <section className="settings-section">
      <div className="settings-section-heading">
        <div>
          <p className="eyebrow">OpenAI</p>
          <h2>Codex</h2>
          <p>Mit deinem Codex-/ChatGPT-Konto anmelden. Anti-Gravity erhält keine Tokens.</p>
        </div>
        <Badge variant={connected ? "healthy" : available ? "attention" : "neutral"}>
          {connected ? "Verbunden" : available ? "Nicht angemeldet" : "Nicht installiert"}
        </Badge>
      </div>

      <div className="custom-model-list">
        <article>
          <div className="custom-model-icon"><Bot className="size-4" /></div>
          <div className="min-w-0">
            <strong>{connected ? "Codex ist einsatzbereit" : "Codex lokal verbinden"}</strong>
            <p>
              {connected
                ? `${models.data?.models.length ?? 0} Modelle verfügbar${status.data?.plan_type ? ` · ${status.data.plan_type}` : ""}`
                : available ? "Die Anmeldung öffnet die offizielle Codex-Seite." : "Die lokale Codex-App wurde nicht gefunden."}
            </p>
          </div>
          <div className="custom-model-actions">
            {connected ? (
              <>
                <Button disabled={Boolean(busy)} onClick={() => void models.refetch()} size="sm" variant="secondary">
                  <RefreshCw className={`size-4 ${models.isFetching ? "motion-safe:animate-spin" : ""}`} /> Modelle laden
                </Button>
                <AlertDialog>
                  <AlertDialogTrigger asChild>
                    <Button aria-label="Codex abmelden" disabled={Boolean(busy)} size="icon" variant="ghost"><LogOut className="size-4" /></Button>
                  </AlertDialogTrigger>
                  <AlertDialogContent>
                    <AlertDialogHeader><AlertDialogTitle>Codex abmelden?</AlertDialogTitle><AlertDialogDescription>Die lokale Codex-Sitzung wird beendet. Gespeicherte Chatverläufe im Hub bleiben erhalten.</AlertDialogDescription></AlertDialogHeader>
                    <AlertDialogFooter><AlertDialogCancel>Abbrechen</AlertDialogCancel><AlertDialogAction onClick={() => void perform("logout", async () => { await logoutCodex(); await queryClient.invalidateQueries({ queryKey: ["codex"] }); await queryClient.invalidateQueries({ queryKey: ["antigravity-models"] }); })}>Abmelden</AlertDialogAction></AlertDialogFooter>
                  </AlertDialogContent>
                </AlertDialog>
              </>
            ) : login ? (
              <>
                <Button asChild size="sm"><a href={login.authUrl} rel="noreferrer" target="_blank"><ExternalLink className="size-4" /> Anmeldung öffnen</a></Button>
                <Button aria-label="Codex-Anmeldung abbrechen" disabled={Boolean(busy)} onClick={() => void cancelLogin()} size="icon" variant="ghost"><X className="size-4" /></Button>
              </>
            ) : (
              <Button disabled={!available || Boolean(busy)} onClick={() => void beginLogin()} size="sm">
                {busy === "login" ? <LoaderCircle className="size-4 motion-safe:animate-spin" /> : <LogIn className="size-4" />} Mit Codex anmelden
              </Button>
            )}
          </div>
        </article>
      </div>
      {login ? <p className="settings-message" role="status">Schließe die Anmeldung im geöffneten Fenster ab. Diese Seite erkennt den Erfolg automatisch.</p> : null}
      {status.isError ? <p className="composer-error" role="alert">Codex-Status konnte nicht geladen werden: {status.error.message}</p> : null}
      {models.isError ? <p className="composer-error" role="alert">Codex-Modelle konnten nicht geladen werden: {models.error.message}</p> : null}
      {error ? <p className="composer-error" role="alert">{error}</p> : null}
    </section>
  );
}
