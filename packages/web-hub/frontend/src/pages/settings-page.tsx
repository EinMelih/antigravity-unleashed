import { useQuery, useQueryClient } from "@tanstack/react-query";
import { FolderCog, GitBranch, ShieldCheck } from "lucide-react";

import { ErrorState, LoadingState } from "@/components/states";
import { Badge } from "@/components/ui/badge";
import { CustomModelSettings } from "@/features/more/custom-model-settings";
import { CodexSettings } from "@/features/more/codex-settings";
import { deleteCustomModel, getCustomModels, getGitHubStatus, saveCustomModel, testCustomModel } from "@/features/more/api";

export function SettingsPage() {
  const queryClient = useQueryClient();
  const github = useQuery({ queryKey: ["github", "status"], queryFn: getGitHubStatus, retry: false });
  const models = useQuery({ queryKey: ["custom-models"], queryFn: getCustomModels });
  async function refreshModels() { await queryClient.invalidateQueries({ queryKey: ["custom-models"] }); }

  if (github.isPending || models.isPending) return <LoadingState description="Integrationen und Modelle werden geladen." />;
  if (github.isError && models.isError) return <ErrorState description="Einstellungen konnten nicht geladen werden." onRetry={() => { void github.refetch(); void models.refetch(); }} />;
  return (
    <section className="more-detail-page">
      <header className="more-page-header"><div><p className="eyebrow">Einstellungen</p><h1>Integrationen & Laufzeit</h1><p>Seltene Konfigurationen bleiben zentral; projektbezogene Ports und Startbefehle stehen direkt im jeweiligen Projekt.</p></div></header>
      <div className="settings-status-grid"><article><GitBranch className="size-5" /><div><strong>GitHub</strong><p>{github.data?.valid ? `Verbunden als ${github.data.login || github.data.owner}` : github.data?.error || "Nicht verbunden oder Zugangsdaten ungültig"}</p></div><Badge variant={github.data?.valid ? "healthy" : "attention"}>{github.data?.valid ? "Verbunden" : "Prüfen"}</Badge></article><article><FolderCog className="size-5" /><div><strong>Projektbasis</strong><p>{github.data?.projects_base_dir || "Nicht konfiguriert"}</p></div></article><article><ShieldCheck className="size-5" /><div><strong>Hub-Konfiguration</strong><p>Außerhalb des Repositories unter <code>~/.gemini/config/antigravity-hub/</code></p></div><Badge variant="healthy">Extern</Badge></article></div>
      {github.isError ? <p className="composer-error" role="alert">GitHub-Status: {github.error.message}</p> : null}
      <CodexSettings />
      {models.isError ? <ErrorState description={models.error.message} onRetry={() => void models.refetch()} title="Custom API nicht verfügbar" /> : <CustomModelSettings models={models.data?.models ?? []} onDelete={async (id) => { await deleteCustomModel(id); await refreshModels(); }} onSave={async (input) => { await saveCustomModel(input); await refreshModels(); }} onTest={testCustomModel} />}
    </section>
  );
}
