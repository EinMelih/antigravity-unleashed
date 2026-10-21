import { useCallback, useEffect, useState } from "react";
import {
  Activity,
  BookOpen,
  CheckCircle2,
  Copy,
  Download,
  ExternalLink,
  Globe,
  Info,
  RefreshCw,
  RotateCcw,
  Settings2,
  ShieldAlert,
  ShieldCheck,
  Terminal,
  Trash2,
  Zap,
} from "lucide-react";

import { useHubLanguage } from "@/lib/i18n";

export interface ApiLogRecord {
  req_id: string;
  created_at: string;
  client_ip: string;
  user_agent: string;
  api_key_name: string;
  source_framework: string;
  endpoint: string;
  engine_mode: string;
  workspace_slot: string;
  conversation_id: string;
  model_requested: string;
  model_actual: string;
  reasoning_effort: string;
  stream: number;
  status_code: number;
  duration_ms: number;
  prompt_tokens: number;
  completion_tokens: number;
  cached_tokens: number;
  thinking_tokens: number;
  total_tokens: number;
  context_used_tokens: number;
  context_max_tokens: number;
  token_source: string;
  messages_json: string;
  system_prompt: string;
  user_prompt_preview: string;
  response_text: string;
  tool_calls_json: string;
  shield_metadata_json: string;
  error_text: string;
  reverted_at: string | null;
  reverted_to_step: number | null;
}

interface EngineSettings {
  mode: "rpc" | "ui";
  max_parallel_streams: number;
  slot_count: number;
  stagger_enabled: boolean;
  stagger_min_ms: number;
  stagger_max_ms: number;
  adaptive_pacing_enabled: boolean;
  heartbeat_blocker_enabled: boolean;
  keyword_firewall_enabled: boolean;
  quota_breaker_enabled: boolean;
  quota_min_fraction: number;
  max_turns_per_session: number;
  local_ip_is_user?: boolean;
  source_ip_map?: Record<string, string>;
}

interface LogsStats {
  totals: {
    total_requests?: number;
    success_requests?: number;
    error_requests?: number;
    reverted_requests?: number;
    prompt_tokens?: number;
    completion_tokens?: number;
    cached_tokens?: number;
    thinking_tokens?: number;
    total_tokens?: number;
    avg_duration_ms?: number;
  };
  by_model: Array<{
    model: string;
    requests: number;
    total_tokens: number;
    avg_duration_ms: number;
  }>;
  total_revert_events: number;
}

/** Official Original Brand Logos from the web */
const OFFICIAL_LOGOS = {
  hermes: "https://hermes-agent.nousresearch.com/docs/img/logo.png",
  openclaw: "https://cdn.jsdelivr.net/gh/selfhst/icons/svg/openclaw.svg",
  openwebui: "https://cdn.jsdelivr.net/gh/selfhst/icons/svg/open-webui.svg",
  openai: "https://cdn.jsdelivr.net/gh/selfhst/icons/svg/openai.svg",
} as const;

const SAFE_UNDETECTED_DEFAULTS: EngineSettings = {
  mode: "rpc",
  max_parallel_streams: 4,
  slot_count: 10,
  stagger_enabled: false,
  stagger_min_ms: 400,
  stagger_max_ms: 1200,
  adaptive_pacing_enabled: false,
  heartbeat_blocker_enabled: true,
  keyword_firewall_enabled: true,
  quota_breaker_enabled: true,
  quota_min_fraction: 0.05,
  max_turns_per_session: 20,
  local_ip_is_user: true,
  source_ip_map: {},
};

const REAL_V224_MODELS = [
  {
    name: "Gemini 4 Argon (Medium)",
    id: "gemini-4-argon-medium",
    enumId: "MODEL_PLACEHOLDER_M418",
    effort: "medium",
    roleDe: "Standard-Allrounder (Default)",
    roleEn: "Default All-Rounder",
  },
  {
    name: "Gemini 4 Argon (High)",
    id: "gemini-4-argon-high",
    effort: "high",
    enumId: "MODEL_PLACEHOLDER_M417",
    roleDe: "Deep Reasoning & Architektur",
    roleEn: "Deep Reasoning & Architecture",
  },
  {
    name: "Gemini 4 Argon (Low)",
    id: "gemini-4-argon-low",
    effort: "low",
    enumId: "MODEL_PLACEHOLDER_M419",
    roleDe: "Schnelle Argon-Antworten",
    roleEn: "Fast Argon Responses",
  },
  {
    name: "Gemini 3.8 Flash (High)",
    id: "gemini-3.8-flash-high",
    effort: "high",
    enumId: "MODEL_PLACEHOLDER_M318",
    roleDe: "Schnelles Flash-Modell mit High-Thinking",
    roleEn: "Fast Flash Model with High Thinking",
  },
  {
    name: "Gemini 3.8 Flash (Medium)",
    id: "gemini-3.8-flash-medium",
    effort: "medium",
    enumId: "MODEL_PLACEHOLDER_M319",
    roleDe: "Ausgewogenes High-Speed-Modell",
    roleEn: "Balanced High-Speed Model",
  },
  {
    name: "Gemini 3.8 Flash (Low)",
    id: "gemini-3.8-flash-low",
    effort: "low",
    enumId: "MODEL_PLACEHOLDER_M320",
    roleDe: "Maximale Geschwindigkeit / Sub-Tasks",
    roleEn: "Maximum Speed / Sub-Tasks",
  },
  {
    name: "Claude Sonnet 4.6 (Thinking)",
    id: "claude-sonnet-4-6",
    effort: "high",
    enumId: "MODEL_PLACEHOLDER_M35",
    roleDe: "Anthropic Coding & Agentic Workflows",
    roleEn: "Anthropic Coding & Agentic Workflows",
  },
  {
    name: "Claude Opus 4.6 (Thinking)",
    id: "claude-opus-4-6-thinking",
    effort: "high",
    enumId: "MODEL_PLACEHOLDER_M26",
    roleDe: "Anthropic Flagship für komplexe Aufgaben",
    roleEn: "Anthropic Flagship for Complex Tasks",
  },
  {
    name: "GPT-OSS 120B (Medium)",
    id: "gpt-oss-120b-medium",
    effort: "medium",
    enumId: "MODEL_OPENAI_GPT_OSS_120B_MEDIUM",
    roleDe: "Alternatives Reasoning-Modell",
    roleEn: "Alternative Reasoning Model",
  },
] as const;

const EIGHT_SHIELDS_INFO = [
  {
    numDe: "Schild 1",
    numEn: "Shield 1",
    titleDe: "Lokaler language_server.exe statt Cloud-OAuth-Spoofing",
    titleEn: "Local language_server.exe instead of Cloud OAuth Spoofing",
    threatDe:
      "Direkte Cloud-Aufrufe mit extrahierten OAuth-Tokens (wie bei früheren OpenClaw-Adaptern) fallen durch abweichende TLS-/Header-Signaturen auf.",
    threatEn:
      "Direct cloud calls using extracted OAuth tokens (like legacy OpenClaw adapters) are flagged due to mismatched TLS and header fingerprints.",
    measureDe:
      "Alle Requests laufen ausschließlich lokal (127.0.0.1) per ConnectRPC über den echten Go-Sidecar language_server.exe des isolierten API-Profils.",
    measureEn:
      "All requests run strictly over local loopback (127.0.0.1) via ConnectRPC through the genuine Go sidecar language_server.exe of the isolated API profile.",
    alwaysActive: true,
  },
  {
    numDe: "Schild 2",
    numEn: "Shield 2",
    titleDe: "Bidirektionale Persona-Firewall & 0 AGENTS.md-Overhead",
    titleEn: "Bidirectional Persona Firewall & Zero AGENTS.md Overhead",
    threatDe:
      "Bot-Signaturen (OpenClaw, Hermes, Nous Research, SOUL.md) im ausgehenden Prompt oder künstliche Override-Regeln in AGENTS.md fallen auf und kosten bei jedem Turn extra Tokens.",
    threatEn:
      "Bot signatures (OpenClaw, Hermes, Nous Research, SOUL.md) in outbound prompts or artificial override rules in AGENTS.md stand out and waste tokens on every turn.",
    measureDe:
      "Maskiert 'Hermes'/'OpenClaw' vor language_server lokal (schont CLI-Befehle & Pfade) und stellt sie in der API-Antwort automatisch wieder her. Keine AGENTS.md nötig (0 Extra-Tokens).",
    measureEn:
      "Masks 'Hermes'/'OpenClaw' locally before language_server (preserving CLI commands & paths) and transparently unmasks them in the API response. Zero AGENTS.md overhead (0 extra tokens).",
    settingKey: "keyword_firewall_enabled" as const,
  },
  {
    numDe: "Schild 3",
    numEn: "Shield 3",
    titleDe: "Heartbeat-Blocker (Aktiv) & Optionales Menschliches Pacing (Aus für Max-Speed)",
    titleEn: "Heartbeat Blocker (Active) & Optional Human Pacing (Off for Max Speed)",
    threatDe:
      "Periodische 30-Minuten-Cron-Pings ('HEARTBEAT_OK') erzeugen unnötige Backend-Aufrufe; künstliches Pacing kostet 1,5–4s Wartezeit.",
    threatEn:
      "Periodic 30-minute cron pings ('HEARTBEAT_OK') create unnecessary backend calls; artificial pacing adds 1.5–4s wait time.",
    measureDe:
      "Automatische Heartbeat-Pings werden lokal in 0 ms beantwortet. Künstliches menschliches Pacing (1,5–4s Pause) ist für maximale API-Geschwindigkeit standardmäßig AUS und jederzeit optional zuschaltbar.",
    measureEn:
      "Automated heartbeat pings are answered locally in 0 ms. Artificial human pacing (1.5–4s delay) is OFF by default for maximum API speed and can be toggled anytime.",
    settingKey: "heartbeat_blocker_enabled" as const,
  },
  {
    numDe: "Schild 4",
    numEn: "Shield 4",
    titleDe: "5-Schichten App-/Chat-Isolation, Session-Reuse & Nativer Revert",
    titleEn: "5-Layer App/Chat Isolation, Session Reuse & Native Revert",
    threatDe:
      "Verschiedene Apps (Hermes, OpenClaw, OpenWebUI, eigene Apps) oder zwei parallele Chats, die beide mit 'Hi' starten, könnten sonst dieselbe cascade_id treffen und Kontext vermischen.",
    threatEn:
      "Different apps (Hermes, OpenClaw, OpenWebUI, custom apps) or two parallel chats both starting with 'Hi' could otherwise hit the same cascade_id and mix context.",
    measureDe:
      "Trennt strikt nach App-Fingerprint (App/IP/Key/User-Agent/Session-ID), System-Hash, 2-Pass Newest-First Matching & Greeting-Guard ('Hi'-Kollisionsschutz). Kein Kontext-Mix zwischen Apps oder neuen Chats.",
    measureEn:
      "Strictly isolates by app_fingerprint (App/IP/Key/User-Agent/Session-ID), system_hash, 2-Pass Newest-First matching & Greeting Guard ('Hi' anti-collision). Zero context mixing across apps or chats.",
    alwaysActive: true,
  },
  {
    numDe: "Schild 5",
    numEn: "Shield 5",
    titleDe: "1:1 UI-Payload + Native IDE-Tool-Abschaltung (customAgent), Thinking & Vision",
    titleEn: "1:1 UI Payload + Native IDE Tool Deactivation (customAgent), Thinking & Vision",
    threatDe:
      "Aktive interne IDE-Tools (run_command, view_file) kollidieren mit Client-Tools (Hermes/OpenClaw), und fehlendes Thinking oder Bild-Pfade statt echtem Vision-Payload wirken unnatürlich.",
    threatEn:
      "Active internal IDE tools (run_command, view_file) collide with client tools (Hermes/OpenClaw), while missing thinking or local image paths instead of native vision payloads break API parity.",
    measureDe:
      "Schaltet interne IDE-Tools & Antigravity-Persona lokal im language_server nativ über customAgent (toolNames: []) ab, streamt Live-Thinking (reasoning_content) und übergibt Bilder nativ als Protobuf-Media (SendUserCascadeMessage.media).",
    measureEn:
      "Natively disables internal IDE tools & Antigravity persona locally inside language_server via customAgent (toolNames: []), streams live thinking (reasoning_content), and attaches images natively via Protobuf Media (SendUserCascadeMessage.media).",
    alwaysActive: true,
  },
  {
    numDe: "Schild 6",
    numEn: "Shield 6",
    titleDe: "Pre-Flight Quota-Breaker mit Hard-Latch bis resetTime (Kein Zwangs-Fallback)",
    titleEn: "Pre-Flight Quota Breaker with Hard Latch until resetTime (No Forced Fallback)",
    threatDe:
      "Endlose Retry-Schleifen bei leerem Kontingent erzeugen hunderte HTTP 429 RESOURCE_EXHAUSTED Fehler bei Google.",
    threatEn:
      "Infinite retry loops on exhausted quotas generate hundreds of HTTP 429 RESOURCE_EXHAUSTED errors on Google's servers.",
    measureDe:
      "Prüft vorab lokal die Modell-Quota und verriegelt erschöpfte Modelle sofort lokal (0 ms, HTTP 429 + Retry-After) exakt bis zur offiziellen Google-resetTime – ohne heimlichen Modell-Fallback, damit Hermes/OpenClaw selbst entscheiden.",
    measureEn:
      "Checks model quota locally before dispatch and latches exhausted models locally (0 ms, HTTP 429 + Retry-After) until Google's official resetTime — with zero silent model fallback so Hermes/OpenClaw stay in full control.",
    settingKey: "quota_breaker_enabled" as const,
  },
  {
    numDe: "Schild 7",
    numEn: "Shield 7",
    titleDe: "Null-Telemetrie-Leak & Hintergrund-Auto-Approval",
    titleEn: "Zero Telemetry Leak & Background Auto-Approval",
    threatDe:
      "Offene WAITING-Freigabedialoge bei Tool-Schritten würden hintergrundbasierte API-Requests endlos blockieren.",
    threatEn:
      "Pending WAITING approval dialogs on tool steps would block background API requests indefinitely.",
    measureDe:
      "Telemetrie im API-Profil deaktiviert; offene Tool-Schritte werden im RPC-Polling-Loop automatisch per HandleCascadeUserInteraction bestätigt.",
    measureEn:
      "Telemetry disabled in the API profile; pending tool steps are auto-approved in the RPC polling loop via HandleCascadeUserInteraction.",
    alwaysActive: true,
  },
  {
    numDe: "Schild 8",
    numEn: "Shield 8",
    titleDe: "10x Multi-Workspace-Pool (ws-00..ws-09) mit Staggered Parallelism",
    titleEn: "10x Multi-Workspace Pool (ws-00..ws-09) with Staggered Parallelism",
    threatDe:
      "Gleichzeitige Requests im selben Ordner führen zu AGENTS.md-Konflikten und unnatürlichen Millisekunden-Bursts.",
    threatEn:
      "Concurrent requests in the same folder cause AGENTS.md race conditions and unnatural millisecond bursts.",
    measureDe:
      "Verteilt bis zu 10 gleichzeitige Requests auf 10 isolierte Projekt-Workspaces (ws-00 bis ws-09) und staffelt Starts mit 400–1200 ms Versatz.",
    measureEn:
      "Distributes up to 10 concurrent requests across 10 isolated project workspaces (ws-00 to ws-09) and staggers starts by 400–1200 ms.",
    alwaysActive: true,
  },
];

function BrandLogo({
  src,
  alt,
  className = "size-5",
}: {
  src: string;
  alt: string;
  className?: string;
}) {
  return (
    <img
      alt={alt}
      className={`${className} shrink-0 rounded object-contain`}
      decoding="async"
      loading="lazy"
      src={src}
    />
  );
}

function FrameworkBadge({
  source,
  en = false,
}: {
  source: string;
  en?: boolean;
}) {
  const norm = (source || "openai").toLowerCase();
  if (norm === "user" || norm === "ich" || norm === "local") {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-md border border-emerald-500/40 bg-emerald-500/10 px-2 py-0.5 text-[11px] font-semibold text-emerald-300">
        <Terminal className="size-3.5 text-emerald-400" />
        {en ? "YOU / LOCAL" : "ICH / LOKAL"}
      </span>
    );
  }
  if (norm === "hermes") {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-md border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-[11px] font-semibold text-amber-300">
        <BrandLogo
          alt="Hermes Agent Logo"
          className="size-3.5"
          src={OFFICIAL_LOGOS.hermes}
        />
        HERMES
      </span>
    );
  }
  if (norm === "openclaw") {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-md border border-rose-500/40 bg-rose-500/10 px-2 py-0.5 text-[11px] font-semibold text-rose-300">
        <BrandLogo
          alt="OpenClaw Logo"
          className="size-3.5"
          src={OFFICIAL_LOGOS.openclaw}
        />
        OPENCLAW
      </span>
    );
  }
  if (norm === "openwebui") {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-md border border-sky-500/40 bg-sky-500/10 px-2 py-0.5 text-[11px] font-semibold text-sky-300">
        <BrandLogo
          alt="OpenWebUI Logo"
          className="size-3.5"
          src={OFFICIAL_LOGOS.openwebui}
        />
        OPENWEBUI
      </span>
    );
  }
  if (norm === "dokploy") {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-md border border-violet-500/40 bg-violet-500/10 px-2 py-0.5 text-[11px] font-semibold text-violet-300">
        <Activity className="size-3.5 text-violet-400" />
        DOKPLOY
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1.5 rounded-md border border-indigo-500/40 bg-indigo-500/10 px-2 py-0.5 text-[11px] font-semibold uppercase text-indigo-300">
      <BrandLogo
        alt="OpenAI Logo"
        className="size-3.5"
        src={OFFICIAL_LOGOS.openai}
      />
      {source || "OPENAI"}
    </span>
  );
}

function parseRowShieldMeta(rawJson: string): {
  detectionReason: string;
  firewallHits: number;
} {
  try {
    const parsed = JSON.parse(rawJson || "{}");
    const hits = Array.isArray(parsed.firewall_hits)
      ? parsed.firewall_hits.length
      : 0;
    const reason =
      typeof parsed.detection_reason === "string"
        ? parsed.detection_reason
        : "";
    return { detectionReason: reason, firewallHits: hits };
  } catch {
    return { detectionReason: "", firewallHits: 0 };
  }
}

function formatDetectionLabel(reason: string, en: boolean): string {
  if (!reason) return "";
  if (reason.startsWith("auto:tools")) {
    return en ? "Auto: Tool Signature" : "Auto: Tool-Signatur";
  }
  if (reason.startsWith("auto:system-prompt")) {
    return en ? "Auto: System Prompt" : "Auto: System-Prompt";
  }
  if (reason.startsWith("auto:user-agent")) {
    return "Auto: User-Agent";
  }
  if (reason.startsWith("ip-rule:")) {
    return en
      ? `IP Rule (${reason.slice(8)})`
      : `IP-Regel (${reason.slice(8)})`;
  }
  if (reason.startsWith("url:")) {
    return `URL (${reason.slice(4)})`;
  }
  if (reason.startsWith("local-pc:")) {
    return en ? "Local PC" : "Lokaler PC";
  }
  if (reason.startsWith("hub-ui:")) {
    return "Hub UI (/docs)";
  }
  return reason;
}

export function ApiLogsPage() {
  const [lang, setLang] = useHubLanguage();
  const en = lang === "en";

  const [logs, setLogs] = useState<ApiLogRecord[]>([]);
  const [stats, setStats] = useState<LogsStats | null>(null);
  const [engine, setEngine] = useState<EngineSettings>(SAFE_UNDETECTED_DEFAULTS);
  const [selectedLog, setSelectedLog] = useState<ApiLogRecord | null>(null);
  const [search, setSearch] = useState("");
  const [frameworkFilter, setFrameworkFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [modelFilter, setModelFilter] = useState("");
  const [loading, setLoading] = useState(false);
  const [statusBanner, setStatusBanner] = useState<string | null>(null);
  const [showCustomSettings, setShowCustomSettings] = useState(false);
  const [showEmbeddedApiDocs, setShowEmbeddedApiDocs] = useState(true);
  const [copiedSnippet, setCopiedSnippet] = useState<string | null>(null);
  const [newIpInput, setNewIpInput] = useState("");
  const [newIpSource, setNewIpSource] = useState("openclaw");

  const isSafeStandard =
    engine.mode === SAFE_UNDETECTED_DEFAULTS.mode &&
    engine.max_parallel_streams === SAFE_UNDETECTED_DEFAULTS.max_parallel_streams &&
    engine.slot_count === SAFE_UNDETECTED_DEFAULTS.slot_count &&
    engine.stagger_min_ms === SAFE_UNDETECTED_DEFAULTS.stagger_min_ms &&
    engine.stagger_max_ms === SAFE_UNDETECTED_DEFAULTS.stagger_max_ms &&
    engine.adaptive_pacing_enabled === SAFE_UNDETECTED_DEFAULTS.adaptive_pacing_enabled &&
    engine.heartbeat_blocker_enabled === SAFE_UNDETECTED_DEFAULTS.heartbeat_blocker_enabled &&
    engine.keyword_firewall_enabled === SAFE_UNDETECTED_DEFAULTS.keyword_firewall_enabled &&
    engine.quota_breaker_enabled === SAFE_UNDETECTED_DEFAULTS.quota_breaker_enabled &&
    Math.abs(engine.quota_min_fraction - SAFE_UNDETECTED_DEFAULTS.quota_min_fraction) < 0.001 &&
    engine.max_turns_per_session === SAFE_UNDETECTED_DEFAULTS.max_turns_per_session;

  const loadAll = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ limit: "150" });
      if (search.trim()) params.set("search", search.trim());
      if (frameworkFilter) params.set("framework", frameworkFilter);
      if (statusFilter) params.set("status", statusFilter);
      if (modelFilter.trim()) params.set("model", modelFilter.trim());

      const [logsRes, statsRes, modeRes] = await Promise.all([
        fetch(`/api/logs?${params.toString()}`),
        fetch("/api/logs/stats"),
        fetch("/api/engine-mode"),
      ]);

      if (logsRes.ok) {
        const data = await logsRes.json();
        setLogs(Array.isArray(data.logs) ? data.logs : []);
      }
      if (statsRes.ok) {
        const sData = await statsRes.json();
        setStats(sData);
      }
      if (modeRes.ok) {
        const mData = await modeRes.json();
        if (mData.api_engine) {
          setEngine(mData.api_engine);
        }
      }
    } catch {
      // Keep current state on transient network error
    } finally {
      setLoading(false);
    }
  }, [search, frameworkFilter, statusFilter, modelFilter]);

  useEffect(() => {
    void loadAll();
  }, [loadAll]);

  async function updateEngineSetting(patch: Partial<EngineSettings>) {
    const next = { ...engine, ...patch };
    setEngine(next);
    try {
      const res = await fetch("/api/engine-mode", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patch),
      });
      if (res.ok) {
        const data = await res.json();
        if (data.api_engine) setEngine(data.api_engine);
        setStatusBanner(
          en
            ? "API Engine & Shield settings saved."
            : "API-Engine & Schutzschild-Einstellungen gespeichert.",
        );
      }
    } catch {
      setStatusBanner(
        en
          ? "Could not save settings."
          : "Einstellung konnte nicht gespeichert werden.",
      );
    }
  }

  async function resetToUndetectedStandard() {
    await updateEngineSetting(SAFE_UNDETECTED_DEFAULTS);
    setStatusBanner(
      en
        ? "All settings restored to the recommended safe default profile."
        : "Alle Einstellungen wurden auf den empfohlenen sicheren Standard zurückgesetzt.",
    );
  }

  async function handleRevertConversation(conversationId: string) {
    if (!conversationId) return;
    try {
      const res = await fetch("/v1/chat/revert", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          conversation_id: conversationId,
          steps_back: 1,
          reason: "dashboard_ui_revert",
        }),
      });
      if (res.ok) {
        const data = await res.json();
        setStatusBanner(
          en
            ? `Conversation ${conversationId.slice(0, 8)}… reverted to Step #${data.reverted_to_step ?? 0}.`
            : `Konversation ${conversationId.slice(0, 8)}… auf Step #${data.reverted_to_step ?? 0} zurückgesetzt.`,
        );
        await loadAll();
      }
    } catch {
      setStatusBanner(en ? "Revert failed." : "Revert fehlgeschlagen.");
    }
  }

  async function handleClearLogs() {
    await fetch("/api/logs", { method: "DELETE" });
    setSelectedLog(null);
    setStatusBanner(
      en ? "Audit logs have been cleared." : "Audit-Logs wurden geleert.",
    );
    await loadAll();
  }

  function copyText(id: string, text: string) {
    if (navigator.clipboard) {
      void navigator.clipboard.writeText(text);
    }
    setCopiedSnippet(id);
    setTimeout(() => setCopiedSnippet(null), 1800);
  }

  const totals = stats?.totals ?? {};

  return (
    <section className="space-y-6">
      {/* Clean Neutral Header with DE/EN Switch */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <p className="eyebrow">
              {en
                ? "API Bridge · Audit Logs · Documentation"
                : "API-Bridge · Audit-Logs · Dokumentation"}
            </p>
            {isSafeStandard ? (
              <span className="inline-flex items-center gap-1 rounded-full border border-emerald-500/40 bg-emerald-500/10 px-2.5 py-0.5 text-[11px] font-semibold text-emerald-400">
                <CheckCircle2 className="size-3.5" />
                {en
                  ? "100% Undetected Default Active"
                  : "100 % Undetected-Standard aktiv"}
              </span>
            ) : (
              <span className="inline-flex items-center gap-1 rounded-full border border-amber-500/40 bg-amber-500/10 px-2.5 py-0.5 text-[11px] font-semibold text-amber-300">
                <ShieldAlert className="size-3.5" />
                {en ? "Custom Profile Active" : "Custom-Profil aktiv"}
              </span>
            )}
          </div>
          <h1 className="mt-2 text-3xl font-semibold">
            {en
              ? "API Logs & Interactive API Documentation"
              : "API-Logs & Interaktive API-Dokumentation"}
          </h1>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">
            {en ? (
              <>
                Persistent storage of all local API calls (<code>:8001</code>)
                with exact token and context metrics, conversation revert
                (“Revert to previous message”), engine mode switch (
                <code>rpc</code> vs. <code>ui</code>), and directly embedded API
                reference.
              </>
            ) : (
              <>
                Persistenter Speicher aller lokalen API-Aufrufe (
                <code>:8001</code>) mit exakten Token- und Kontextwerten,
                Konversations-Revert („Zurück zur vorherigen Nachricht“),
                Modus-Umschalter (<code>rpc</code> vs. <code>ui</code>) sowie
                direkt eingebetteter API-Referenz.
              </>
            )}
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {/* DE / EN Language Switcher */}
          <div
            aria-label={en ? "Language selector" : "Sprachauswahl"}
            className="inline-flex items-center gap-1 rounded-lg border border-border bg-card p-1 text-xs font-semibold"
            role="group"
          >
            <Globe className="ml-1.5 size-3.5 text-muted-foreground" />
            <button
              aria-pressed={!en}
              className={`rounded px-2 py-1 transition-colors ${
                !en
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:text-foreground"
              }`}
              onClick={() => setLang("de")}
              type="button"
            >
              DE
            </button>
            <button
              aria-pressed={en}
              className={`rounded px-2 py-1 transition-colors ${
                en
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:text-foreground"
              }`}
              onClick={() => setLang("en")}
              type="button"
            >
              EN
            </button>
          </div>

          {!isSafeStandard ? (
            <button
              className="inline-flex items-center gap-2 rounded-lg border border-emerald-500/40 bg-emerald-500/15 px-3 py-2 text-xs font-semibold text-emerald-300 hover:bg-emerald-500/25"
              onClick={() => void resetToUndetectedStandard()}
              type="button"
            >
              <ShieldCheck className="size-4" />
              {en
                ? "Reset to Safe Default"
                : "Auf sicheren Standard zurücksetzen"}
            </button>
          ) : null}
          <button
            className="inline-flex items-center gap-2 rounded-lg border border-border bg-card px-3 py-2 text-xs font-semibold hover:bg-accent"
            onClick={() => setShowCustomSettings((prev) => !prev)}
            type="button"
          >
            <Settings2 className="size-4" />
            {showCustomSettings
              ? en
                ? "Hide Custom Settings"
                : "Custom-Settings ausblenden"
              : en
                ? "Customize Settings"
                : "Custom-Settings anpassen"}
          </button>
          <button
            className="inline-flex items-center gap-2 rounded-lg border border-border bg-card px-3 py-2 text-xs font-semibold hover:bg-accent"
            onClick={() => void loadAll()}
            type="button"
          >
            <RefreshCw className="size-4" />
            {en ? "Refresh" : "Aktualisieren"}
          </button>
          <a
            className="inline-flex items-center gap-2 rounded-lg border border-border bg-card px-3 py-2 text-xs font-semibold hover:bg-accent"
            href="/api/logs/export"
          >
            <Download className="size-4" />
            JSONL Export
          </a>
          <button
            className="inline-flex items-center gap-2 rounded-lg border border-border bg-card px-3 py-2 text-xs font-semibold text-destructive hover:bg-accent"
            onClick={() => void handleClearLogs()}
            type="button"
          >
            <Trash2 className="size-4" />
            {en ? "Clear Logs" : "Logs leeren"}
          </button>
        </div>
      </div>

      {statusBanner ? (
        <div
          className="rounded-xl border border-primary/40 bg-primary/10 px-4 py-3 text-sm font-medium"
          role="status"
        >
          {statusBanner}
        </div>
      ) : null}

      {/* Dual-Engine & 8 Shields Control Bar */}
      <div className="grid gap-4 rounded-xl border border-border bg-card p-5 shadow-panel lg:grid-cols-3">
        <div className="space-y-2">
          <div className="flex items-center gap-2 text-sm font-semibold">
            <Zap className="size-4 text-primary" />
            <span>
              {en
                ? "Execution Mode (Dual-Engine)"
                : "Ausführungs-Modus (Dual-Engine)"}
            </span>
          </div>
          <p className="text-xs text-muted-foreground">
            {en ? (
              <>
                <strong>RPC Direct</strong> communicates locally (
                <code>127.0.0.1</code>) directly with{" "}
                <code>language_server.exe</code> without UI clicks.{" "}
                <strong>UI / CDP</strong> remains available as backup.
              </>
            ) : (
              <>
                <strong>RPC Direct</strong> spricht lokal (
                <code>127.0.0.1</code>) ohne UI-Klicks direkt mit{" "}
                <code>language_server.exe</code>. <strong>UI / CDP</strong>{" "}
                bleibt als Backup erhalten.
              </>
            )}
          </p>
          <div className="flex gap-2 pt-1">
            <button
              aria-pressed={engine.mode === "rpc"}
              className={`rounded-lg border px-3 py-2 text-xs font-semibold transition-colors ${
                engine.mode === "rpc"
                  ? "border-primary bg-primary text-primary-foreground"
                  : "border-border bg-muted text-muted-foreground hover:text-foreground"
              }`}
              onClick={() => void updateEngineSetting({ mode: "rpc" })}
              type="button"
            >
              {en
                ? "RPC Direct (Zero-CDP · Default)"
                : "RPC Direct (Zero-CDP · Standard)"}
            </button>
            <button
              aria-pressed={engine.mode === "ui"}
              className={`rounded-lg border px-3 py-2 text-xs font-semibold transition-colors ${
                engine.mode === "ui"
                  ? "border-primary bg-primary text-primary-foreground"
                  : "border-border bg-muted text-muted-foreground hover:text-foreground"
              }`}
              onClick={() => void updateEngineSetting({ mode: "ui" })}
              type="button"
            >
              UI / CDP Backup
            </button>
          </div>
        </div>

        <div className="space-y-2">
          <div className="flex items-center gap-2 text-sm font-semibold">
            <Activity className="size-4 text-primary" />
            <span>
              {en
                ? `Shield 8: Parallel Streams (${engine.max_parallel_streams} / ${engine.slot_count} Slots)`
                : `Schild 8: Parallele Streams (${engine.max_parallel_streams} / ${engine.slot_count} Slots)`}
            </span>
          </div>
          <p className="text-xs text-muted-foreground">
            {en
              ? `Accepts up to ${engine.slot_count} concurrent requests and runs up to ${engine.max_parallel_streams} streams in parallel with ${engine.stagger_min_ms}–${engine.stagger_max_ms} ms stagger.`
              : `Nimmt bis zu ${engine.slot_count} gleichzeitige Requests an und startet bis zu ${engine.max_parallel_streams} Streams echt parallel mit ${engine.stagger_min_ms}–${engine.stagger_max_ms} ms Versatz.`}
          </p>
          <div className="flex items-center gap-3 pt-1">
            <label className="text-xs font-medium" htmlFor="parallel-streams">
              {en ? "Active Streams:" : "Aktive Streams:"}
            </label>
            <select
              aria-label={en ? "Active Streams" : "Aktive Streams"}
              className="rounded-lg border border-border bg-background px-2.5 py-1.5 text-xs"
              id="parallel-streams"
              onChange={(e) =>
                void updateEngineSetting({
                  max_parallel_streams: Number(e.target.value),
                })
              }
              value={engine.max_parallel_streams}
            >
              {[1, 2, 3, 4, 5, 6, 8, 10].map((n) => (
                <option key={n} value={n}>
                  {n}{" "}
                  {n === 4
                    ? en
                      ? "(Recommended: Multi-Project IDE)"
                      : "(Empfohlen: Multi-Projekt IDE)"
                    : ""}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="space-y-2">
          <div className="flex items-center gap-2 text-sm font-semibold">
            <ShieldCheck className="size-4 text-primary" />
            <span>
              {en
                ? "Active Anti-Ban Shields (1–8)"
                : "Aktive Anti-Ban-Schutzschilde (1–8)"}
            </span>
          </div>
          <div className="grid grid-cols-2 gap-2 pt-1 text-xs">
            <label className="flex items-center gap-2">
              <input
                checked={engine.keyword_firewall_enabled}
                onChange={(e) =>
                  void updateEngineSetting({
                    keyword_firewall_enabled: e.target.checked,
                  })
                }
                type="checkbox"
              />
              <span>
                {en
                  ? "Shield 2: Persona Firewall (0 AGENTS.md)"
                  : "Schild 2: Persona-Firewall (0 AGENTS.md)"}
              </span>
            </label>
            <label className="flex items-center gap-2">
              <input
                checked={engine.heartbeat_blocker_enabled}
                onChange={(e) =>
                  void updateEngineSetting({
                    heartbeat_blocker_enabled: e.target.checked,
                  })
                }
                type="checkbox"
              />
              <span>
                {en
                  ? "Shield 3a: Heartbeat Blocker"
                  : "Schild 3a: Heartbeat-Blocker"}
              </span>
            </label>
            <label className="flex items-center gap-2">
              <input
                checked={engine.adaptive_pacing_enabled}
                onChange={(e) =>
                  void updateEngineSetting({
                    adaptive_pacing_enabled: e.target.checked,
                  })
                }
                type="checkbox"
              />
              <span>
                {en
                  ? "Shield 3b: Human Delay (1.5–4s)"
                  : "Schild 3b: Menschliche Pause (1,5–4s)"}
              </span>
            </label>
            <label className="flex items-center gap-2">
              <input
                checked={Boolean(engine.stagger_enabled)}
                onChange={(e) =>
                  void updateEngineSetting({
                    stagger_enabled: e.target.checked,
                  })
                }
                type="checkbox"
              />
              <span>
                {en
                  ? "Shield 8b: Start Stagger (0.4–1.2s)"
                  : "Schild 8b: Start-Verzögerung (0,4–1,2s)"}
              </span>
            </label>
            <label className="flex items-center gap-2">
              <input
                checked={engine.quota_breaker_enabled}
                onChange={(e) =>
                  void updateEngineSetting({
                    quota_breaker_enabled: e.target.checked,
                  })
                }
                type="checkbox"
              />
              <span>
                {en ? "Shield 6: Quota Breaker" : "Schild 6: Quota-Breaker"} (
                {Math.round(engine.quota_min_fraction * 100)}%)
              </span>
            </label>
          </div>
        </div>
      </div>

      {/* Subtle Anecdote / Background Note with Original Logos for Hermes, OpenClaw, OpenWebUI & OpenAI */}
      <div className="flex flex-wrap items-center justify-between gap-4 rounded-xl border border-border/80 bg-card/60 px-4 py-3 text-xs text-muted-foreground">
        <div className="flex flex-wrap items-center gap-3">
          <span className="inline-flex items-center gap-1.5 font-semibold text-foreground">
            <Info className="size-4 text-primary" />
            {en
              ? "Pure Standalone API Parity & Zero-Detection Hardening:"
              : "100 % Echte API-Parität & Undetected-Härtung:"}
          </span>
          <span>
            {en ? (
              <>
                Internal IDE tools and the Antigravity persona are disabled{" "}
                <strong>natively</strong> inside the local{" "}
                <code>language_server</code> via{" "}
                <code>customAgent: &#123;toolNames: []&#125;</code> (zero{" "}
                <code>AGENTS.md</code> token overhead, zero prompt-injection
                text). External clients (<strong>Hermes Agent</strong>,{" "}
                <strong>OpenClaw</strong>, <strong>OpenWebUI</strong>) get full{" "}
                <strong>Client-Tool execution</strong>, live{" "}
                <strong>Thinking streaming</strong> (
                <code>reasoning_content</code>), and native{" "}
                <strong>Multimodal Vision</strong> (<code>media</code>) while
                remaining 100% indistinguishable from official local IDE
                traffic.
              </>
            ) : (
              <>
                Interne IDE-Tools und die Antigravity-Persona werden{" "}
                <strong>nativ</strong> im lokalen <code>language_server</code>{" "}
                über <code>customAgent: &#123;toolNames: []&#125;</code>{" "}
                abgeschaltet (<code>0</code> <code>AGENTS.md</code>-Overhead,
                kein Jailbreak-Text). Dadurch funktionieren{" "}
                <strong>Client-Tools</strong> (von <strong>Hermes Agent</strong>
                , <strong>OpenClaw</strong>, <strong>OpenWebUI</strong>),{" "}
                <strong>Live-Thinking</strong> (<code>reasoning_content</code>)
                und <strong>Multimodal-Vision (Bilder)</strong> exakt wie bei
                einer echten Standalone-API – für Google zu 100 % ununterscheidbar
                vom offiziellen lokalen IDE-Betrieb.
              </>
            )}
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-2.5">
          <span className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-background px-2.5 py-1 text-[11px] font-medium text-foreground">
            <BrandLogo
              alt="Hermes Agent Original Logo"
              className="size-4"
              src={OFFICIAL_LOGOS.hermes}
            />
            Hermes Agent Ready
          </span>
          <span className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-background px-2.5 py-1 text-[11px] font-medium text-foreground">
            <BrandLogo
              alt="OpenClaw Original Logo"
              className="size-4"
              src={OFFICIAL_LOGOS.openclaw}
            />
            OpenClaw Anti-Ban Shield
          </span>
          <span className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-background px-2.5 py-1 text-[11px] font-medium text-foreground">
            <BrandLogo
              alt="OpenWebUI Original Logo"
              className="size-4"
              src={OFFICIAL_LOGOS.openwebui}
            />
            OpenWebUI
          </span>
          <span className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-background px-2.5 py-1 text-[11px] font-medium text-foreground">
            <BrandLogo
              alt="OpenAI Original Logo"
              className="size-4"
              src={OFFICIAL_LOGOS.openai}
            />
            OpenAI SDK
          </span>
        </div>
      </div>

      {/* 2-Stage Source Detection (Auto-Detect + Custom IP Mapping, Hidden from Google) */}
      <div className="space-y-3 rounded-xl border border-border bg-card p-4 shadow-panel">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="space-y-1">
            <div className="flex flex-wrap items-center gap-2 text-sm font-semibold">
              <ShieldCheck className="size-4 text-emerald-400" />
              <span>
                {en
                  ? "Source Detection: Local Auto-Detect (OpenClaw / Hermes / You) & Custom IP Rules"
                  : "Quellen-Erkennung: Lokales Auto-Detect (OpenClaw / Hermes / Ich) & Eigene IP-Zuordnung"}
              </span>
              <span className="rounded-md border border-emerald-500/40 bg-emerald-500/10 px-2 py-0.5 text-[10px] font-semibold text-emerald-300">
                {en
                  ? "100% Invisible to Google (Scrubbed by Shield 2)"
                  : "100 % unsichtbar für Google (durch Schild 2 bereinigt)"}
              </span>
            </div>
            <p className="text-xs text-muted-foreground">
              {en ? (
                <>
                  <strong>Stage 1 (For You):</strong> Before anything is sent to{" "}
                  <code>language_server.exe</code>, the Hub automatically
                  identifies <strong>OpenClaw</strong> (via tool schemas like{" "}
                  <code>sessions_spawn</code>/<code>canvas</code>,{" "}
                  <code>SOUL.md</code>/<code>HEARTBEAT.md</code>, or IP/URL),{" "}
                  <strong>Hermes</strong> (via <code>delegate_task</code>/
                  <code>skill_view</code> or prompt), or{" "}
                  <strong>You / Local</strong>.{" "}
                  <strong>Stage 2 (For Google):</strong> Shield 2 scrubs all
                  signatures, headers, and IPs so Google only ever sees a local
                  IDE request.
                </>
              ) : (
                <>
                  <strong>Stufe 1 (Für dich im Hub):</strong> Noch bevor der
                  Request an <code>language_server.exe</code> geht, erkennt der
                  Hub vollautomatisch <strong>OpenClaw</strong> (anhand der
                  Tool-Signatur wie <code>sessions_spawn</code>/
                  <code>canvas</code>, <code>SOUL.md</code>/
                  <code>HEARTBEAT.md</code> oder IP/URL),{" "}
                  <strong>Hermes</strong> (anhand von{" "}
                  <code>delegate_task</code>/<code>skill_view</code> oder
                  System-Prompt) oder <strong>Dich (ICH / LOKAL)</strong>.{" "}
                  <strong>Stufe 2 (Für Google):</strong> Schild 2 entfernt
                  danach restlos alle Namen, Header und IPs – Google sieht immer
                  nur einen neutralen lokalen IDE-Aufruf.
                </>
              )}
            </p>
          </div>

          <label className="inline-flex items-center gap-2 rounded-lg border border-border bg-background px-3 py-1.5 text-xs font-medium">
            <input
              checked={engine.local_ip_is_user ?? true}
              onChange={(e) =>
                void updateEngineSetting({
                  local_ip_is_user: e.target.checked,
                })
              }
              type="checkbox"
            />
            <span>
              {en
                ? "Mark 127.0.0.1 (without agent signature) as 'YOU / LOCAL'"
                : "127.0.0.1 (ohne Agent-Signatur) als „ICH / LOKAL“ markieren"}
            </span>
          </label>
        </div>

        {/* Custom IP Mapping Controls */}
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border/70 pt-3 text-xs">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-semibold text-foreground">
              {en ? "Assign Custom IP → Source:" : "Eigene IP festlegen → Quelle:"}
            </span>
            <input
              aria-label={
                en
                  ? "IP address for source mapping"
                  : "IP-Adresse für Quellen-Zuordnung"
              }
              className="w-44 rounded-lg border border-border bg-background px-2.5 py-1.5 font-mono text-xs"
              onChange={(e) => setNewIpInput(e.target.value)}
              placeholder={
                en
                  ? "IP (e.g. 192.168.178.20)"
                  : "IP (z. B. 192.168.178.20)"
              }
              type="text"
              value={newIpInput}
            />
            <select
              aria-label={en ? "Target source for IP" : "Ziel-Quelle für IP"}
              className="rounded-lg border border-border bg-background px-2.5 py-1.5 text-xs"
              onChange={(e) => setNewIpSource(e.target.value)}
              value={newIpSource}
            >
              <option value="openclaw">OpenClaw</option>
              <option value="hermes">Hermes Agent</option>
              <option value="user">
                {en ? "You / Local (ICH)" : "Ich / Lokal (Mein PC)"}
              </option>
              <option value="openwebui">OpenWebUI</option>
              <option value="dokploy">Dokploy</option>
            </select>
            <button
              className="rounded-lg border border-primary/40 bg-primary/15 px-3 py-1.5 text-xs font-semibold text-primary hover:bg-primary/25"
              onClick={() => {
                const ip = newIpInput.trim();
                if (!ip) return;
                const nextMap = {
                  ...(engine.source_ip_map || {}),
                  [ip]: newIpSource,
                };
                setNewIpInput("");
                void updateEngineSetting({ source_ip_map: nextMap });
              }}
              type="button"
            >
              {en ? "+ Save IP Rule" : "+ IP-Regel speichern"}
            </button>
          </div>

          <div className="text-[11px] text-muted-foreground">
            {en ? (
              <>
                Optional URL separation on same IP:{" "}
                <code>/openclaw/v1</code> · <code>/hermes/v1</code> ·{" "}
                <code>/ich/v1</code>
              </>
            ) : (
              <>
                Optional per URL trennen (gleiche IP):{" "}
                <code>/openclaw/v1</code> · <code>/hermes/v1</code> ·{" "}
                <code>/ich/v1</code>
              </>
            )}
          </div>
        </div>

        {engine.source_ip_map &&
        Object.keys(engine.source_ip_map).length > 0 ? (
          <div className="flex flex-wrap items-center gap-2 pt-1 text-xs">
            <span className="text-[11px] text-muted-foreground">
              {en ? "Active IP Rules:" : "Aktive IP-Regeln:"}
            </span>
            {Object.entries(engine.source_ip_map).map(([ipKey, srcVal]) => (
              <span
                className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-background px-2.5 py-1 font-mono text-[11px]"
                key={ipKey}
              >
                <span>{ipKey}</span>
                <span className="text-muted-foreground">→</span>
                <FrameworkBadge en={en} source={srcVal} />
                <button
                  aria-label={
                    en ? `Delete IP rule ${ipKey}` : `IP-Regel ${ipKey} löschen`
                  }
                  className="ml-1 rounded px-1 text-muted-foreground hover:bg-destructive/20 hover:text-destructive"
                  onClick={() => {
                    const nextMap = { ...(engine.source_ip_map || {}) };
                    delete nextMap[ipKey];
                    void updateEngineSetting({ source_ip_map: nextMap });
                  }}
                  type="button"
                >
                  ×
                </button>
              </span>
            ))}
          </div>
        ) : null}
      </div>

      {/* Optional Custom Fine-Tuning Panel (Standard remains untouched unless user customizes) */}
      {showCustomSettings ? (
        <div className="space-y-4 rounded-xl border border-primary/30 bg-card p-5 shadow-panel">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <h2 className="text-base font-semibold">
                {en
                  ? "Custom Fine-Tuning of Shields & Limits"
                  : "Custom-Feinsteuerung der Schutzschilde & Grenzwerte"}
              </h2>
              <p className="text-xs text-muted-foreground">
                {en ? (
                  <>
                    By default, all parameters are locked to the{" "}
                    <strong>recommended Undetected Default</strong>. You can
                    customize them anytime or restore defaults with one click.
                  </>
                ) : (
                  <>
                    Standardmäßig sind alle Werte auf den{" "}
                    <strong>empfohlenen Undetected-Standard</strong>{" "}
                    eingestellt. Du kannst sie hier jederzeit individuell
                    anpassen oder mit einem Klick zurücksetzen.
                  </>
                )}
              </p>
            </div>
            <button
              className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-muted px-3 py-1.5 text-xs font-semibold hover:bg-accent"
              onClick={() => void resetToUndetectedStandard()}
              type="button"
            >
              <RotateCcw className="size-3.5" />
              {en ? "Restore Defaults" : "Standardwerte wiederherstellen"}
            </button>
          </div>

          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
            <label className="space-y-1 text-xs">
              <span className="font-semibold">
                {en
                  ? "Isolated Workspace Slots (Default: 10)"
                  : "Isolierte Workspace-Slots (Standard: 10)"}
              </span>
              <input
                className="w-full rounded-lg border border-border bg-background px-3 py-1.5 text-xs"
                max={16}
                min={1}
                onChange={(e) =>
                  void updateEngineSetting({
                    slot_count: Math.max(
                      1,
                      Math.min(16, Number(e.target.value) || 10),
                    ),
                  })
                }
                type="number"
                value={engine.slot_count}
              />
              <span className="block text-[11px] text-muted-foreground">
                ws-00 – ws-
                {String(Math.max(0, engine.slot_count - 1)).padStart(2, "0")}
              </span>
            </label>

            <label className="space-y-1 text-xs">
              <span className="font-semibold">
                {en
                  ? "Min. Start Stagger (Default: 400 ms)"
                  : "Min. Start-Versatz (Standard: 400 ms)"}
              </span>
              <input
                className="w-full rounded-lg border border-border bg-background px-3 py-1.5 text-xs"
                max={5000}
                min={50}
                onChange={(e) =>
                  void updateEngineSetting({
                    stagger_min_ms: Math.max(50, Number(e.target.value) || 400),
                  })
                }
                step={50}
                type="number"
                value={engine.stagger_min_ms}
              />
              <span className="block text-[11px] text-muted-foreground">
                {en
                  ? "Prevents millisecond bursts"
                  : "Verhindert Millisekunden-Bursts"}
              </span>
            </label>

            <label className="space-y-1 text-xs">
              <span className="font-semibold">
                {en
                  ? "Max. Start Stagger (Default: 1200 ms)"
                  : "Max. Start-Versatz (Standard: 1200 ms)"}
              </span>
              <input
                className="w-full rounded-lg border border-border bg-background px-3 py-1.5 text-xs"
                max={10000}
                min={100}
                onChange={(e) =>
                  void updateEngineSetting({
                    stagger_max_ms: Math.max(
                      100,
                      Number(e.target.value) || 1200,
                    ),
                  })
                }
                step={50}
                type="number"
                value={engine.stagger_max_ms}
              />
              <span className="block text-[11px] text-muted-foreground">
                {en
                  ? "Human tab-switching interval"
                  : "Menschliches Tab-Switching-Intervall"}
              </span>
            </label>

            <label className="space-y-1 text-xs">
              <span className="font-semibold">
                {en
                  ? "Quota Circuit Breaker (Default: 5%)"
                  : "Quota-Notbremse (Standard: 5 %)"}
              </span>
              <select
                className="w-full rounded-lg border border-border bg-background px-3 py-1.5 text-xs"
                onChange={(e) =>
                  void updateEngineSetting({
                    quota_min_fraction: Number(e.target.value),
                  })
                }
                value={engine.quota_min_fraction}
              >
                <option value={0.03}>3 %</option>
                <option value={0.05}>
                  {en ? "5 % (Recommended)" : "5 % Rest-Quota (Empfohlen)"}
                </option>
                <option value={0.1}>
                  {en ? "10 % (Conservative)" : "10 % Rest-Quota (Konservativ)"}
                </option>
                <option value={0.15}>15 %</option>
              </select>
              <span className="block text-[11px] text-muted-foreground">
                {en
                  ? "Stops before Google HTTP 429 loops"
                  : "Stoppt vor Google HTTP 429 Loops"}
              </span>
            </label>

            <label className="space-y-1 text-xs">
              <span className="font-semibold">
                {en
                  ? "Session Rotation (Default: 20 Turns)"
                  : "Session-Rotation (Standard: 20 Turns)"}
              </span>
              <input
                className="w-full rounded-lg border border-border bg-background px-3 py-1.5 text-xs"
                max={50}
                min={3}
                onChange={(e) =>
                  void updateEngineSetting({
                    max_turns_per_session: Math.max(
                      3,
                      Math.min(50, Number(e.target.value) || 20),
                    ),
                  })
                }
                type="number"
                value={engine.max_turns_per_session}
              />
              <span className="block text-[11px] text-muted-foreground">
                {en
                  ? "Prevents 1-turn throwaway chats"
                  : "Verhindert 1-Turn-Wegwerf-Chats"}
              </span>
            </label>
          </div>
        </div>
      ) : null}

      {/* KPI Summary Cards */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <div className="rounded-xl border border-border bg-card p-4 shadow-panel">
          <p className="text-xs text-muted-foreground">
            {en ? "Logged Requests" : "Gespeicherte Requests"}
          </p>
          <p className="mt-1 text-2xl font-semibold">
            {totals.total_requests ?? logs.length}
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            OK: {totals.success_requests ?? 0} · {en ? "Errors" : "Fehler"}:{" "}
            {totals.error_requests ?? 0}
          </p>
        </div>
        <div className="rounded-xl border border-border bg-card p-4 shadow-panel">
          <p className="text-xs text-muted-foreground">
            {en ? "Verified Total Tokens" : "Verifizierte Gesamt-Tokens"}
          </p>
          <p className="mt-1 text-2xl font-semibold">
            {(totals.total_tokens ?? 0).toLocaleString(en ? "en-US" : "de-DE")}
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            Prompt:{" "}
            {(totals.prompt_tokens ?? 0).toLocaleString(
              en ? "en-US" : "de-DE",
            )}{" "}
            · Output:{" "}
            {(totals.completion_tokens ?? 0).toLocaleString(
              en ? "en-US" : "de-DE",
            )}
          </p>
        </div>
        <div className="rounded-xl border border-border bg-card p-4 shadow-panel">
          <p className="text-xs text-muted-foreground">
            {en
              ? "Cache Hits & Thinking Tokens"
              : "Cache-Hits & Thinking-Tokens"}
          </p>
          <p className="mt-1 text-2xl font-semibold">
            {(totals.cached_tokens ?? 0).toLocaleString(
              en ? "en-US" : "de-DE",
            )}
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            Thinking/Reasoning:{" "}
            {(totals.thinking_tokens ?? 0).toLocaleString(
              en ? "en-US" : "de-DE",
            )}
          </p>
        </div>
        <div className="rounded-xl border border-border bg-card p-4 shadow-panel">
          <p className="text-xs text-muted-foreground">
            {en
              ? "Reverts (“Revert to previous message”)"
              : "Reverts („Zurück zur vorherigen Nachricht“)"}
          </p>
          <p className="mt-1 text-2xl font-semibold">
            {stats?.total_revert_events ?? 0}
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            {en ? "Avg Latency" : "Ø Antwortzeit"}:{" "}
            {Math.round(totals.avg_duration_ms ?? 0)} ms
          </p>
        </div>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3 rounded-xl border border-border bg-card p-4">
        <input
          aria-label={en ? "Search logs" : "Logs durchsuchen"}
          className="min-w-60 flex-1 rounded-lg border border-border bg-background px-3 py-2 text-xs"
          onChange={(e) => setSearch(e.target.value)}
          placeholder={
            en
              ? "Search prompt, response, conversation ID, or request ID…"
              : "Prompt, Antwort, Conversation-ID oder Request-ID suchen…"
          }
          type="text"
          value={search}
        />
        <select
          aria-label={en ? "Filter by source" : "Quelle filtern"}
          className="rounded-lg border border-border bg-background px-3 py-2 text-xs"
          onChange={(e) => setFrameworkFilter(e.target.value)}
          value={frameworkFilter}
        >
          <option value="">
            {en
              ? "All Sources (Hermes / OpenClaw / You / OpenAI)"
              : "Alle Quellen (Hermes / OpenClaw / Ich / OpenAI)"}
          </option>
          <option value="user">
            {en ? "You / Local PC (ICH / LOKAL)" : "Ich / Lokal (Eigener PC)"}
          </option>
          <option value="openclaw">OpenClaw</option>
          <option value="hermes">Hermes</option>
          <option value="openwebui">OpenWebUI</option>
          <option value="dokploy">Dokploy</option>
          <option value="openai">
            {en ? "OpenAI / Other" : "OpenAI / Sonstige"}
          </option>
        </select>
        <select
          aria-label={en ? "Filter by status" : "Status filtern"}
          className="rounded-lg border border-border bg-background px-3 py-2 text-xs"
          onChange={(e) => setStatusFilter(e.target.value)}
          value={statusFilter}
        >
          <option value="">{en ? "All Statuses" : "Alle Status"}</option>
          <option value="ok">
            {en ? "Success (200)" : "Erfolgreich (200)"}
          </option>
          <option value="reverted">
            {en ? "Reverted" : "Reverted (Zurückgesetzt)"}
          </option>
          <option value="error">
            {en
              ? "Error / Quota Stop (4xx/5xx)"
              : "Fehler / Quota-Stop (4xx/5xx)"}
          </option>
        </select>
        <input
          aria-label={en ? "Filter by model" : "Modell filtern"}
          className="w-44 rounded-lg border border-border bg-background px-3 py-2 text-xs"
          onChange={(e) => setModelFilter(e.target.value)}
          placeholder={en ? "Model (e.g. opus)…" : "Modell (z.B. opus)…"}
          type="text"
          value={modelFilter}
        />
      </div>

      {/* Audit Log Table */}
      <div className="overflow-x-auto rounded-xl border border-border bg-card shadow-panel">
        <table className="w-full text-left text-xs">
          <thead className="border-b border-border bg-muted/50 text-muted-foreground">
            <tr>
              <th className="px-4 py-3 font-semibold">
                {en ? "Timestamp" : "Uhrzeit"}
              </th>
              <th className="px-4 py-3 font-semibold">
                {en ? "Source / Client" : "Von wo / Quelle"}
              </th>
              <th className="px-4 py-3 font-semibold">
                {en ? "Mode & Slot" : "Modus & Slot"}
              </th>
              <th className="px-4 py-3 font-semibold">
                {en ? "Model" : "Modell"}
              </th>
              <th className="px-4 py-3 font-semibold">
                {en ? "Prompt & Response" : "Was geschrieben wurde"}
              </th>
              <th className="px-4 py-3 font-semibold">
                {en ? "Tokens & Context" : "Tokens & Kontext"}
              </th>
              <th className="px-4 py-3 font-semibold">
                {en ? "Status / Revert" : "Status / Revert"}
              </th>
              <th className="px-4 py-3 font-semibold">
                {en ? "Action" : "Aktion"}
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {logs.length === 0 ? (
              <tr>
                <td
                  className="px-4 py-8 text-center text-muted-foreground"
                  colSpan={8}
                >
                  {loading
                    ? en
                      ? "Loading logs…"
                      : "Logs werden geladen…"
                    : en
                      ? "No API requests logged yet."
                      : "Noch keine API-Requests protokolliert."}
                </td>
              </tr>
            ) : (
              logs.map((row) => {
                const ctxPct =
                  row.context_max_tokens > 0
                    ? Math.min(
                        100,
                        Math.round(
                          (row.context_used_tokens / row.context_max_tokens) *
                            100,
                        ),
                      )
                    : 0;
                const shieldMeta = parseRowShieldMeta(row.shield_metadata_json);
                const detectionLabel = formatDetectionLabel(
                  shieldMeta.detectionReason,
                  en,
                );
                const isAgentSource =
                  row.source_framework === "openclaw" ||
                  row.source_framework === "hermes";
                return (
                  <tr
                    className="cursor-pointer transition-colors hover:bg-accent/50"
                    key={row.req_id}
                    onClick={() => setSelectedLog(row)}
                  >
                    <td className="whitespace-nowrap px-4 py-3 font-mono">
                      {new Date(row.created_at).toLocaleString(
                        en ? "en-US" : "de-DE",
                      )}
                      <div className="text-[11px] text-muted-foreground">
                        {Math.round(row.duration_ms)} ms · #{row.req_id}
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex flex-wrap items-center gap-1.5">
                        <FrameworkBadge en={en} source={row.source_framework} />
                        {isAgentSource || shieldMeta.firewallHits > 0 ? (
                          <span
                            className="inline-flex items-center rounded border border-emerald-500/30 bg-emerald-500/10 px-1.5 py-0.5 text-[9px] font-semibold text-emerald-400"
                            title={
                              en
                                ? "Shield 2 scrubbed all agent traces before forwarding to Google"
                                : "Schild 2 hat alle Agent-Spuren entfernt, bevor Google kontaktiert wurde"
                            }
                          >
                            {en ? "Google: hidden" : "Google: getarnt"}
                          </span>
                        ) : null}
                      </div>
                      <div className="mt-1 text-[11px] text-muted-foreground">
                        {row.client_ip} · {row.api_key_name}
                      </div>
                      {detectionLabel ? (
                        <div className="mt-0.5 text-[10px] text-primary/80">
                          {detectionLabel}
                        </div>
                      ) : null}
                    </td>
                    <td className="px-4 py-3">
                      <span className="font-semibold uppercase">
                        {row.engine_mode}
                      </span>
                      <div className="text-[11px] text-muted-foreground">
                        {row.workspace_slot || "default"}
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <div className="font-semibold">{row.model_actual}</div>
                      {row.model_requested &&
                      row.model_requested !== row.model_actual ? (
                        <div className="text-[11px] text-muted-foreground">
                          {en ? "Requested" : "Angefragt"}:{" "}
                          {row.model_requested}
                        </div>
                      ) : null}
                    </td>
                    <td className="max-w-xs px-4 py-3">
                      <div className="truncate font-medium">
                        {row.user_prompt_preview ||
                          (en ? "(No text)" : "(Kein Text)")}
                      </div>
                      <div className="truncate text-[11px] text-muted-foreground">
                        → {row.response_text?.slice(0, 90) || row.error_text}
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <div className="font-mono font-semibold">
                        {row.total_tokens.toLocaleString(
                          en ? "en-US" : "de-DE",
                        )}{" "}
                        Tok. ({row.token_source})
                      </div>
                      <div className="text-[11px] text-muted-foreground">
                        In: {row.prompt_tokens} · Out: {row.completion_tokens} ·
                        Cache: {row.cached_tokens}
                      </div>
                      <div className="mt-1 flex items-center gap-2">
                        <div className="h-1.5 w-20 overflow-hidden rounded-full bg-muted">
                          <div
                            className="h-full bg-primary"
                            style={{ width: `${ctxPct}%` }}
                          />
                        </div>
                        <span className="text-[10px] text-muted-foreground">
                          {ctxPct}% (
                          {row.context_used_tokens.toLocaleString(
                            en ? "en-US" : "de-DE",
                          )}{" "}
                          /{" "}
                          {row.context_max_tokens.toLocaleString(
                            en ? "en-US" : "de-DE",
                          )}
                          )
                        </span>
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`inline-flex rounded-md px-2 py-0.5 font-semibold ${
                          row.status_code >= 400
                            ? "bg-destructive/15 text-destructive"
                            : "bg-primary/15 text-primary"
                        }`}
                      >
                        HTTP {row.status_code}
                      </span>
                      {row.reverted_at ? (
                        <div className="mt-1 text-[11px] font-medium text-amber-500">
                          Reverted @{" "}
                          {new Date(row.reverted_at).toLocaleTimeString(
                            en ? "en-US" : "de-DE",
                          )}{" "}
                          (Step #{row.reverted_to_step ?? 0})
                        </div>
                      ) : null}
                    </td>
                    <td
                      className="px-4 py-3"
                      onClick={(e) => e.stopPropagation()}
                    >
                      {row.conversation_id ? (
                        <button
                          className="inline-flex items-center gap-1 rounded-lg border border-border bg-background px-2.5 py-1.5 text-[11px] font-semibold hover:bg-accent"
                          onClick={() =>
                            void handleRevertConversation(row.conversation_id)
                          }
                          title={
                            en
                              ? "Revert conversation by 1 turn (RevertToCascadeStep)"
                              : "Konversation um 1 Turn zurückspulen (RevertToCascadeStep)"
                          }
                          type="button"
                        >
                          <RotateCcw className="size-3.5" />
                          Revert
                        </button>
                      ) : null}
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      {/* Detailed Log Inspector */}
      {selectedLog ? (
        <div className="space-y-4 rounded-xl border border-border bg-card p-5 shadow-panel">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Terminal className="size-5 text-primary" />
              <h2 className="text-lg font-semibold">
                {en ? "Request Details" : "Request-Details"} #
                {selectedLog.req_id} (
                {selectedLog.source_framework.toUpperCase()} ·{" "}
                {selectedLog.model_actual})
              </h2>
            </div>
            <button
              className="rounded-lg border border-border px-3 py-1 text-xs font-semibold hover:bg-accent"
              onClick={() => setSelectedLog(null)}
              type="button"
            >
              {en ? "Close" : "Schließen"}
            </button>
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <div>
              <h3 className="text-xs font-semibold uppercase text-muted-foreground">
                {en
                  ? "System Prompt (Turn-1 Injection + Native customAgent, 0 AGENTS.md)"
                  : "System-Prompt (Turn-1-Injektion + Natives customAgent, 0 AGENTS.md)"}
              </h3>
              <pre className="mt-2 max-h-48 overflow-auto rounded-lg border border-border bg-muted/40 p-3 text-xs whitespace-pre-wrap">
                {selectedLog.system_prompt ||
                  (en
                    ? "(No system prompt provided)"
                    : "(Kein System-Prompt übergeben)")}
              </pre>
            </div>
            <div>
              <h3 className="text-xs font-semibold uppercase text-muted-foreground">
                {en
                  ? "Shield & Context Telemetry"
                  : "Schild- & Kontext-Telemetrie"}
              </h3>
              <pre className="mt-2 max-h-48 overflow-auto rounded-lg border border-border bg-muted/40 p-3 text-xs whitespace-pre-wrap">
                {selectedLog.shield_metadata_json}
              </pre>
            </div>
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <div>
              <h3 className="text-xs font-semibold uppercase text-muted-foreground">
                {en
                  ? "Submitted Messages (messages)"
                  : "Übergebene Nachrichten (messages)"}
              </h3>
              <pre className="mt-2 max-h-72 overflow-auto rounded-lg border border-border bg-muted/40 p-3 text-xs whitespace-pre-wrap">
                {selectedLog.messages_json}
              </pre>
            </div>
            <div>
              <h3 className="text-xs font-semibold uppercase text-muted-foreground">
                {en ? "Full Model Response" : "Vollständige Modell-Antwort"}
              </h3>
              <pre className="mt-2 max-h-72 overflow-auto rounded-lg border border-border bg-muted/40 p-3 text-xs whitespace-pre-wrap">
                {selectedLog.response_text || selectedLog.error_text}
              </pre>
            </div>
          </div>
        </div>
      ) : null}

      {/* Directly Integrated API Documentation & Interactive /docs Section */}
      <div className="space-y-4 rounded-xl border border-border bg-card p-5 shadow-panel">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border pb-4">
          <div className="flex items-center gap-2.5">
            <BookOpen className="size-5 text-primary" />
            <div>
              <h2 className="text-xl font-semibold">
                {en
                  ? "API Documentation & 9 Genuine v2.24.0 Models"
                  : "API-Dokumentation & 9 Echte v2.24.0 Modelle"}
              </h2>
              <p className="text-xs text-muted-foreground">
                {en ? (
                  <>
                    Direct integration of the interactive API reference (
                    <code>/docs</code>), model slugs, and example calls.
                  </>
                ) : (
                  <>
                    Direkte Einbindung der interaktiven API-Referenz (
                    <code>/docs</code>), Modell-Slugs und Beispiel-Aufrufe.
                  </>
                )}
              </p>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <button
              className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-background px-3 py-1.5 text-xs font-semibold hover:bg-accent"
              onClick={() => setShowEmbeddedApiDocs((prev) => !prev)}
              type="button"
            >
              {showEmbeddedApiDocs
                ? en
                  ? "Collapse interactive /docs view"
                  : "Interaktive /docs-Ansicht einklappen"
                : en
                  ? "Expand interactive /docs view"
                  : "Interaktive /docs-Ansicht ausklappen"}
            </button>
            <a
              className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-background px-3 py-1.5 text-xs font-semibold hover:bg-accent"
              href={`/docs?lang=${lang}`}
              rel="noreferrer"
              target="_blank"
            >
              {en ? "Open /docs in new tab" : "/docs in neuem Tab öffnen"}
              <ExternalLink className="size-3.5" />
            </a>
          </div>
        </div>

        {/* 9 Real v2.24.0 Models Reference Table & Client Snippets */}
        <div className="grid gap-4 lg:grid-cols-2">
          <div className="overflow-x-auto rounded-xl border border-border bg-background/50">
            <div className="border-b border-border px-4 py-2.5 text-xs font-semibold">
              {en
                ? "Verified Antigravity v2.24.0 Models (GET /v1/models)"
                : "Verifizierte Antigravity v2.24.0 Modelle (GET /v1/models)"}
            </div>
            <table className="w-full text-left text-xs">
              <thead className="border-b border-border bg-muted/40 text-[11px] text-muted-foreground">
                <tr>
                  <th className="px-3 py-2">
                    {en ? "Model Name (UI & API)" : "Modellname (UI & API)"}
                  </th>
                  <th className="px-3 py-2">API-Slug (model)</th>
                  <th className="px-3 py-2">{en ? "Use Case" : "Einsatzgebiet"}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {REAL_V224_MODELS.map((m) => (
                  <tr key={m.id}>
                    <td className="px-3 py-2 font-semibold">{m.name}</td>
                    <td className="px-3 py-2 font-mono text-[11px] text-primary">
                      {m.id}
                    </td>
                    <td className="px-3 py-2 text-[11px] text-muted-foreground">
                      {en ? m.roleEn : m.roleDe}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="space-y-3">
            <div className="rounded-xl border border-border bg-background/50 p-3.5">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2 text-xs font-semibold">
                  <BrandLogo
                    alt="Hermes Agent Logo"
                    className="size-4"
                    src={OFFICIAL_LOGOS.hermes}
                  />
                  <BrandLogo
                    alt="OpenClaw Logo"
                    className="size-4"
                    src={OFFICIAL_LOGOS.openclaw}
                  />
                  <span>
                    {en
                      ? "OpenAI-Compatible Provider Setup (e.g. Hermes / OpenClaw)"
                      : "OpenAI-kompatible Provider-Anbindung (z. B. Hermes / OpenClaw)"}
                  </span>
                </div>
                <button
                  className="inline-flex items-center gap-1 rounded border border-border px-2 py-1 text-[11px] hover:bg-accent"
                  onClick={() =>
                    copyText(
                      "hermes-cfg",
                      `provider: openai\nbase_url: http://127.0.0.1:8001/v1\napi_key: YOUR_LOCAL_AUTH_TOKEN\nmodel: claude-sonnet-4-6`,
                    )
                  }
                  type="button"
                >
                  <Copy className="size-3" />
                  {copiedSnippet === "hermes-cfg"
                    ? en
                      ? "Copied!"
                      : "Kopiert!"
                    : "Copy"}
                </button>
              </div>
              <pre className="mt-2 overflow-x-auto rounded-lg bg-muted/40 p-2.5 font-mono text-[11px]">
{`provider: openai
base_url: http://127.0.0.1:8001/v1
api_key: <auth_token from ~/.gemini/config/antigravity-hub/config.json>
model: claude-sonnet-4-6   # or gemini-4-argon-high / claude-opus-4-6-thinking`}
              </pre>
            </div>

            <div className="rounded-xl border border-border bg-background/50 p-3.5">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2 text-xs font-semibold">
                  <BrandLogo
                    alt="OpenAI Logo"
                    className="size-4"
                    src={OFFICIAL_LOGOS.openai}
                  />
                  <span>
                    {en
                      ? "cURL / REST Call & Conversation Revert"
                      : "cURL / REST-Aufruf & Konversations-Revert"}
                  </span>
                </div>
                <button
                  className="inline-flex items-center gap-1 rounded border border-border px-2 py-1 text-[11px] hover:bg-accent"
                  onClick={() =>
                    copyText(
                      "curl-cfg",
                      `curl -X POST http://127.0.0.1:8001/v1/chat/completions -H "Authorization: Bearer YOUR_TOKEN" -H "Content-Type: application/json" -d '{"model":"Gemini 4 Argon (Medium)","messages":[{"role":"system","content":"Be concise."},{"role":"user","content":"Hello!"}]}'`,
                    )
                  }
                  type="button"
                >
                  <Copy className="size-3" />
                  {copiedSnippet === "curl-cfg"
                    ? en
                      ? "Copied!"
                      : "Kopiert!"
                    : "Copy"}
                </button>
              </div>
              <pre className="mt-2 overflow-x-auto rounded-lg bg-muted/40 p-2.5 font-mono text-[11px]">
{`# 1. Chat-Completion (native customAgent toolNames:[], live reasoning_content & vision media)
POST http://127.0.0.1:8001/v1/chat/completions
{
  "model": "Gemini 4 Argon (Medium)",
  "messages": [
    {"role": "system", "content": "You are a precise coding assistant."},
    {"role": "user", "content": "Explain this module."}
  ]
}

# 2. Revert conversation by 1 step (RevertToCascadeStep)
POST http://127.0.0.1:8001/v1/chat/revert
{ "conversation_id": "<cascade_id>", "steps_back": 1 }`}
              </pre>
            </div>
          </div>
        </div>

        {/* Embedded Interactive /docs Page (docs/api.html) */}
        {showEmbeddedApiDocs ? (
          <div className="overflow-hidden rounded-xl border border-border bg-background">
            <div className="flex items-center justify-between border-b border-border bg-muted/40 px-4 py-2 text-xs">
              <span className="font-semibold">
                {en ? (
                  <>
                    Interactive API Reference & Live Tester (<code>/docs</code>)
                  </>
                ) : (
                  <>
                    Interaktive API-Referenz & Live-Tester (<code>/docs</code>)
                  </>
                )}
              </span>
              <span className="text-muted-foreground">
                {en ? (
                  <>
                    Embedded directly from <code>docs/api.html</code>
                  </>
                ) : (
                  <>
                    Direkt eingebunden aus <code>docs/api.html</code>
                  </>
                )}
              </span>
            </div>
            <iframe
              className="h-[680px] w-full border-0"
              src={`/docs?lang=${lang}`}
              title={
                en
                  ? "Antigravity Web API Documentation"
                  : "Antigravity Web API Dokumentation"
              }
            />
          </div>
        ) : null}
      </div>

      {/* Deep-Dive Explanation: Was macht Revert genau & alle 8 Anti-Ban-Schutzschilde */}
      <div className="space-y-4 rounded-xl border border-border bg-card p-5 shadow-panel">
        <div className="flex flex-wrap items-start justify-between gap-4 border-b border-border pb-4">
          <div>
            <p className="eyebrow">
              {en
                ? "Technical Background Note"
                : "Technische Hintergrund-Notiz"}
            </p>
            <h2 className="mt-1 text-xl font-semibold">
              {en
                ? "What does “Revert” do exactly – and how do the 8 Anti-Ban Shields protect us?"
                : "Was macht „Revert“ genau – und wie schützen uns die 8 Anti-Ban-Schilde?"}
            </h2>
          </div>
          <a
            className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-background px-3 py-1.5 text-xs font-semibold hover:bg-accent"
            href="/docs/control-plane/anti-ban"
            rel="noreferrer"
            target="_blank"
          >
            {en
              ? "Open Architecture Note (Markdown)"
              : "Architektur-Notiz als Markdown öffnen"}
            <ExternalLink className="size-3.5" />
          </a>
        </div>

        {/* Revert Explanation Box */}
        <div className="rounded-xl border border-amber-500/30 bg-amber-500/5 p-4">
          <div className="flex items-center gap-2 text-sm font-semibold text-amber-300">
            <RotateCcw className="size-4" />
            <span>
              {en ? (
                <>
                  What does the “Revert” button (
                  <code>RevertToCascadeStep</code>) do – and why is it safe?
                </>
              ) : (
                <>
                  Was macht der Button „Revert“ (
                  <code>RevertToCascadeStep</code>) genau – und warum ist das
                  sicher?
                </>
              )}
            </span>
          </div>
          <div className="mt-2 grid gap-4 text-xs leading-5 text-muted-foreground lg:grid-cols-3">
            <div>
              <strong className="text-foreground">
                {en
                  ? "1. Why does an API need Revert?"
                  : "1. Wozu braucht die API Revert?"}
              </strong>
              <p className="mt-1">
                {en ? (
                  <>
                    When you edit an earlier message (“Edit”) or regenerate a
                    reply (“Regenerate”) in a client (e.g. OpenWebUI, Hermes, or
                    OpenClaw), the client re-sends the truncated message history
                    to <code>/v1/chat/completions</code>. Without Revert, a new
                    1-turn chat would have to be created every time.
                  </>
                ) : (
                  <>
                    Wenn du in einem Client (z. B. OpenWebUI, Hermes oder
                    OpenClaw) eine frühere Nachricht bearbeitest („Edit“) oder
                    eine Antwort neu generieren lässt („Regenerate“), schickt
                    der Client den gekürzten Verlauf erneut an{" "}
                    <code>/v1/chat/completions</code>. Ohne Revert müsste jedes
                    Mal ein neuer 1-Turn-Chat angelegt werden.
                  </>
                )}
              </p>
            </div>
            <div>
              <strong className="text-foreground">
                {en
                  ? "2. What happens technically during Revert?"
                  : "2. Was passiert technisch beim Revert?"}
              </strong>
              <p className="mt-1">
                {en ? (
                  <>
                    The bridge invokes the native ConnectRPC command{" "}
                    <code>RevertToCascadeStep(cascadeId, stepIndex)</code> on
                    the local <code>language_server.exe</code>. This rolls the
                    conversation state back to the exact step and discards only
                    the obsolete steps after it.
                  </>
                ) : (
                  <>
                    Die Bridge ruft lokal am <code>language_server.exe</code>{" "}
                    den nativen ConnectRPC-Befehl{" "}
                    <code>RevertToCascadeStep(cascadeId, stepIndex)</code> auf.
                    Das setzt den Gesprächsstand exakt auf den gewählten Schritt
                    zurück und verwirft nur die veralteten Schritte dahinter.
                  </>
                )}
              </p>
            </div>
            <div>
              <strong className="text-foreground">
                {en ? "3. Why is this 100% safe?" : "3. Warum ist das 100 % sicher?"}
              </strong>
              <p className="mt-1">
                {en ? (
                  <>
                    <code>RevertToCascadeStep</code> is the exact same call used
                    by the Antigravity IDE when clicking{" "}
                    <em>“Revert to this step”</em> in the chat. The conversation
                    continues cleanly on the same <code>cascadeId</code> instead
                    of leaving unnatural 1-turn throwaway chats.
                  </>
                ) : (
                  <>
                    <code>RevertToCascadeStep</code> ist exakt derselbe Aufruf,
                    den die Antigravity-IDE nutzt, wenn man im Chat auf den
                    Pfeil <em>„Revert to this step“</em> klickt. So läuft das
                    Gespräch sauber auf derselben <code>cascadeId</code> weiter,
                    statt unnatürliche 1-Turn-Wegwerf-Chats zu hinterlassen.
                  </>
                )}
              </p>
            </div>
          </div>
        </div>

        {/* 8 Shields Grid */}
        <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-4">
          {EIGHT_SHIELDS_INFO.map((shield) => {
            const isActive = shield.alwaysActive
              ? true
              : shield.settingKey
                ? Boolean(engine[shield.settingKey])
                : true;
            return (
              <article
                className="flex flex-col justify-between rounded-xl border border-border bg-background/60 p-3.5 text-xs"
                key={shield.numDe}
              >
                <div className="space-y-2">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-mono font-bold text-primary">
                      {en ? shield.numEn : shield.numDe}
                    </span>
                    <span
                      className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${
                        isActive
                          ? "bg-emerald-500/15 text-emerald-400"
                          : "bg-amber-500/15 text-amber-400"
                      }`}
                    >
                      {isActive
                        ? en
                          ? "ACTIVE"
                          : "AKTIV"
                        : en
                          ? "MANUAL OFF"
                          : "MANUELL AUS"}
                    </span>
                  </div>
                  <h3 className="font-semibold text-foreground">
                    {en ? shield.titleEn : shield.titleDe}
                  </h3>
                  <p className="text-[11px] leading-4 text-muted-foreground">
                    <strong className="text-foreground">
                      {en ? "Background:" : "Hintergrund:"}
                    </strong>{" "}
                    {en ? shield.threatEn : shield.threatDe}
                  </p>
                  <p className="text-[11px] leading-4 text-muted-foreground">
                    <strong className="text-foreground">
                      {en ? "Implementation:" : "Umsetzung:"}
                    </strong>{" "}
                    {en ? shield.measureEn : shield.measureDe}
                  </p>
                </div>
              </article>
            );
          })}
        </div>
      </div>
    </section>
  );
}
