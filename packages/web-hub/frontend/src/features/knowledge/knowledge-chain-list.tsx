import { ExternalLink } from "lucide-react";
import type { ReactNode } from "react";

import type {
  ControlKnowledgeArtifactSummary,
  ControlKnowledgeBranch,
  ControlKnowledgeChain,
  ControlKnowledgeChainsResponse,
  ControlKnowledgeCoverageState,
  ControlKnowledgeDeploymentSummary,
} from "@/api/contracts";
import {
  artifactTypeLabel,
  deploymentEnvironmentLabel,
  domainStatusLabel,
  knowledgeRelationLabel,
  knowledgeSourceLabel,
} from "@/lib/domain-labels";

interface KnowledgeChainListProps {
  data: ControlKnowledgeChainsResponse;
  search?: string;
}

type CoverageTone = "present" | "missing" | "not-required" | "pending" | "unknown";
const expectedIdeaGroupFiles = 5;

const coverageLabels: Record<CoverageTone, string> = {
  present: "Vorhanden",
  missing: "Fehlt",
  "not-required": "Nicht erforderlich",
  pending: "Ausstehend",
  unknown: "Unklar",
};

const dateFormatter = new Intl.DateTimeFormat("de-DE", {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

function list<T>(value: T[] | null | undefined): T[] {
  return Array.isArray(value) ? value : [];
}

function coverageTone(value: ControlKnowledgeCoverageState): CoverageTone {
  const normalized = String(value || "").trim().toLowerCase().replaceAll("-", "_");
  if (["present", "materialized", "complete", "recorded"].includes(normalized)) return "present";
  if (["missing", "failed"].includes(normalized)) return "missing";
  if (["not_required", "not_applicable", "not_requested"].includes(normalized)) return "not-required";
  if (["pending", "planned", "unmaterialized"].includes(normalized)) return "pending";
  return "unknown";
}

function CoverageBadge({
  label: explicitLabel,
  state,
}: {
  label?: string;
  state: ControlKnowledgeCoverageState;
}) {
  const tone = coverageTone(state);
  const normalized = String(state || "").trim().toLowerCase().replaceAll("-", "_");
  const label = explicitLabel || (normalized === "not_requested"
    ? "Nicht angefordert"
    : normalized === "failed"
      ? "Fehlgeschlagen"
      : coverageLabels[tone]);
  return <span className={`knowledge-coverage-badge is-${tone}`}>{label}</span>;
}

function formatDate(value: string | null | undefined) {
  if (!value) return "Nicht aufgezeichnet";
  const parsed = new Date(value.includes("T") ? value : value.replace(" ", "T"));
  return Number.isNaN(parsed.getTime()) ? "Ungültiger Zeitwert" : dateFormatter.format(parsed);
}

function displayValue(value: string | null | undefined, fallback = "Nicht aufgezeichnet") {
  const normalized = String(value || "").trim();
  if (!normalized) return fallback;
  return normalized.length > 240 ? `${normalized.slice(0, 239)}…` : normalized;
}

function displaySha(value: string | null | undefined) {
  const normalized = String(value || "").trim();
  return /^[a-f0-9]{7,64}$/i.test(normalized) ? normalized : "Nicht aufgezeichnet";
}

function safeGitHubUrl(value: string | null | undefined) {
  try {
    const url = new URL(String(value || "").trim());
    const hostname = url.hostname.toLowerCase();
    const safeProtocol = url.protocol === "http:" || url.protocol === "https:";
    const githubHost = hostname === "github.com" || hostname.endsWith(".github.com");
    return safeProtocol && githubHost ? url.toString() : null;
  } catch {
    return null;
  }
}

function GitHubReference({ href, label }: { href: string; label: string }) {
  const safeHref = safeGitHubUrl(href);
  if (!safeHref) return <span>{label} · kein sicherer Link aufgezeichnet</span>;
  return (
    <a href={safeHref} rel="noreferrer" target="_blank">
      {label} auf GitHub öffnen <ExternalLink aria-hidden="true" className="size-3.5" />
    </a>
  );
}

function KnowledgeStage({
  children,
  label,
  state,
}: {
  children: ReactNode;
  label: string;
  state: ControlKnowledgeCoverageState;
}) {
  return (
    <li className="knowledge-stage">
      <div className="knowledge-stage-marker" aria-hidden="true" />
      <div className="knowledge-stage-body">
        <header><h3>{label}</h3><CoverageBadge state={state} /></header>
        {children}
      </div>
    </li>
  );
}

function ArtifactItem({ artifact }: { artifact: ControlKnowledgeArtifactSummary }) {
  return (
    <article className="knowledge-artifact">
      <header>
        <div><strong>{artifact.title}</strong><small>{artifactTypeLabel(artifact.artifact_type)} · {domainStatusLabel(artifact.status)}</small></div>
        <CoverageBadge state={artifact.materialization_status} />
      </header>
      <details>
        <summary>Details anzeigen</summary>
        <dl>
          <div><dt>Version</dt><dd>{artifact.version}</dd></div>
          <div><dt>Interner Typ</dt><dd><code>{displayValue(artifact.artifact_type)}</code></dd></div>
          <div><dt>Interner Status</dt><dd><code>{displayValue(artifact.status)}</code></dd></div>
          <div><dt>Datei</dt><dd>{displayValue(artifact.relative_path)}</dd></div>
          <div><dt>Content SHA-256</dt><dd><code>{displaySha(artifact.content_sha256)}</code></dd></div>
          <div><dt>Materialisierter SHA-256</dt><dd><code>{displaySha(artifact.materialized_sha256)}</code></dd></div>
          <div><dt>Commit</dt><dd><code>{displaySha(artifact.materialized_commit_sha)}</code></dd></div>
          <div><dt>Materialisiert</dt><dd>{formatDate(artifact.materialized_at)}</dd></div>
        </dl>
      </details>
    </article>
  );
}

function ArtifactList({ artifacts }: { artifacts: ControlKnowledgeArtifactSummary[] }) {
  const rows = list(artifacts);
  return rows.length ? <div className="knowledge-artifact-list">{rows.map((artifact) => <ArtifactItem artifact={artifact} key={artifact.id} />)}</div> : <p>Noch kein verknüpftes Artefakt aufgezeichnet.</p>;
}

function RecordedDeployment({ deployment }: { deployment: ControlKnowledgeDeploymentSummary }) {
  return (
    <details className="knowledge-deployment">
      <summary><span>{deploymentEnvironmentLabel(deployment.environment)}</span><span>{domainStatusLabel(deployment.status)} · aufgezeichnet</span></summary>
      <dl>
        <div><dt>Interne Umgebung</dt><dd><code>{displayValue(deployment.environment)}</code></dd></div>
        <div><dt>Interner Status</dt><dd><code>{displayValue(deployment.status)}</code></dd></div>
        <div><dt>SHA</dt><dd><code>{displaySha(deployment.sha)}</code></dd></div>
        <div><dt>Artifact</dt><dd>{displayValue(deployment.artifact_ref)}</dd></div>
        <div><dt>Vorheriger stabiler SHA</dt><dd><code>{displaySha(deployment.previous_stable_sha)}</code></dd></div>
        <div><dt>Rollback von</dt><dd>{displayValue(deployment.rollback_of)}</dd></div>
        <div><dt>Gestartet</dt><dd>{formatDate(deployment.started_at)}</dd></div>
        <div><dt>Beendet</dt><dd>{formatDate(deployment.finished_at)}</dd></div>
      </dl>
    </details>
  );
}

function Branch({ branch }: { branch: ControlKnowledgeBranch }) {
  const task = branch.task;
  const issueRecorded = Boolean(task?.issue_number);
  const pullRequestRecorded = Boolean(task?.pr_number);
  const evidenceRecorded = Boolean(branch.evidence);
  const deployments = list(branch.deployments);

  return (
    <article className="knowledge-branch">
      <header className="knowledge-branch-header">
        <div><span>Geplanter PR · Priorität {branch.candidate.priority}</span><h3>{branch.candidate.title}</h3></div>
        <span className="knowledge-record-status">{domainStatusLabel(branch.candidate.status)}</span>
      </header>
      <ol className="knowledge-branch-flow">
        <KnowledgeStage label="Geplanter PR" state="present">
          <details>
            <summary>Technische Referenz</summary>
            <p><code>{branch.candidate.id}</code></p>
            <code>{displaySha(branch.candidate.base_sha)}</code>
          </details>
          <ArtifactList artifacts={branch.artifacts} />
        </KnowledgeStage>
        <KnowledgeStage label="GitHub-Aufgabe" state={issueRecorded ? "present" : "pending"}>
          {issueRecorded && task ? <GitHubReference href={task.issue_url} label={`Aufgabe #${task.issue_number}`} /> : <p>Noch keine GitHub-Aufgabe aufgezeichnet.</p>}
        </KnowledgeStage>
        <KnowledgeStage label="Pull Request" state={pullRequestRecorded ? "present" : "pending"}>
          {pullRequestRecorded && task ? <GitHubReference href={task.pr_url} label={`PR #${task.pr_number}`} /> : <p>Noch kein Pull Request aufgezeichnet.</p>}
          {task ? <div className="knowledge-sha-pair"><span>Aktuell <code>{displaySha(task.current_sha)}</code></span><span>Gemergt <code>{displaySha(task.merged_sha)}</code></span></div> : null}
        </KnowledgeStage>
        <KnowledgeStage label="Prüfnachweise" state={evidenceRecorded ? "present" : "pending"}>
          {branch.evidence ? (
            <details className="knowledge-evidence">
              <summary>{domainStatusLabel(branch.evidence.status)} · Details anzeigen</summary>
              <p>{displayValue(branch.evidence.summary)}</p>
              <code>{displaySha(branch.evidence.sha)}</code>
              <p><small>Interner Status: <code>{displayValue(branch.evidence.status)}</code></small></p>
            </details>
          ) : <p>Noch keine Prüfnachweise aufgezeichnet.</p>}
        </KnowledgeStage>
        <KnowledgeStage label="Auslieferung" state={deployments.length ? "present" : "pending"}>
          <p className="knowledge-deployment-notice">Vom Control Center aufgezeichneter Zustand – kein Nachweis einer externen Auslieferung.</p>
          {deployments.length ? <div className="knowledge-deployment-list">{deployments.map((deployment) => <RecordedDeployment deployment={deployment} key={deployment.id} />)}</div> : <p>Noch keine Auslieferung aufgezeichnet.</p>}
        </KnowledgeStage>
      </ol>
    </article>
  );
}

function countState(value: number, emptyState: ControlKnowledgeCoverageState = "pending") {
  return value > 0 ? "present" : emptyState;
}

function ChainCoverage({ chain }: { chain: ControlKnowledgeChain }) {
  const coverage = chain.coverage;
  const ideaGroupComplete = coverage.idea_group_files === expectedIdeaGroupFiles;
  return (
    <dl className="knowledge-coverage-grid" aria-label="Abdeckung der Wissenskette">
      <div>
        <dt>Ideen-Dokumente</dt>
        <dd>
          {coverage.idea_group_files}/{expectedIdeaGroupFiles}
          <CoverageBadge
            label={ideaGroupComplete ? "Vollständig" : "Unvollständig"}
            state={ideaGroupComplete ? "present" : "missing"}
          />
        </dd>
      </div>
      <div><dt>Verknüpfte Artefakte</dt><dd>{coverage.linked_artifacts}<CoverageBadge state={countState(coverage.linked_artifacts)} /></dd></div>
      <div><dt>Lose Artefakte</dt><dd>{coverage.unlinked_artifacts}<CoverageBadge state={coverage.unlinked_artifacts ? "missing" : "present"} /></dd></div>
      <div><dt>Verknüpfte PR-Slices</dt><dd>{coverage.linked_candidates}<CoverageBadge state={countState(coverage.linked_candidates)} /></dd></div>
      <div><dt>Lose PR-Slices</dt><dd>{coverage.unlinked_candidates}<CoverageBadge state={coverage.unlinked_candidates ? "missing" : "present"} /></dd></div>
    </dl>
  );
}

function KnowledgeChainCard({ chain }: { chain: ControlKnowledgeChain }) {
  const ideaGroup = list(chain.idea_group);
  const ideaGroupIds = new Set(ideaGroup.map((artifact) => artifact.id));
  const artifacts = list(chain.artifacts).filter((artifact) => !ideaGroupIds.has(artifact.id));
  const branches = list(chain.branches);
  const relations = list(chain.relations);
  const artifactNames = new Map([...ideaGroup, ...artifacts].map((artifact) => [artifact.id, artifact.title]));
  const title = chain.idea_seed?.title || chain.campaign?.title || `Wissenskette für ${chain.project.name}`;

  return (
    <article className="knowledge-chain-card">
      <header className="knowledge-chain-header">
        <div><span>{chain.project.name}</span><h2>{title}</h2></div>
        <span className="knowledge-record-status">{domainStatusLabel(chain.campaign?.status || chain.idea_seed?.status, "Unvollständig")}</span>
      </header>
      <ChainCoverage chain={chain} />
      <ol className="knowledge-chain-timeline">
        <KnowledgeStage label="Ursprüngliche Idee" state={chain.idea_seed ? "present" : "missing"}>
          {chain.idea_seed ? <p>{knowledgeSourceLabel(chain.idea_seed.source)} · {formatDate(chain.idea_seed.created_at)}</p> : <p>Keine Herkunftsidee verknüpft.</p>}
        </KnowledgeStage>
        <KnowledgeStage label="Ideen-Dokumente" state={ideaGroup.length ? "present" : "missing"}>
          <ArtifactList artifacts={ideaGroup} />
        </KnowledgeStage>
        <KnowledgeStage label="Design & Entscheidungen" state={artifacts.length ? "present" : "pending"}>
          <ArtifactList artifacts={artifacts} />
          {relations.length ? (
            <details className="knowledge-relations">
              <summary>{relations.length} Querverweis{relations.length === 1 ? "" : "e"} anzeigen</summary>
              <ul>{relations.map((relation, index) => <li key={`${relation.source_artifact_id}-${relation.target_artifact_id}-${index}`}>{artifactNames.get(relation.source_artifact_id) || relation.source_artifact_id} → {knowledgeRelationLabel(relation.relation_type)} → {artifactNames.get(relation.target_artifact_id) || relation.target_artifact_id}<small>Interner Beziehungstyp: <code>{relation.relation_type}</code></small></li>)}</ul>
            </details>
          ) : null}
        </KnowledgeStage>
        <KnowledgeStage label="Umsetzungsplan" state={chain.campaign ? "present" : "pending"}>
          {chain.campaign ? <div className="knowledge-campaign-summary"><strong>{chain.campaign.title}</strong><span>Version {chain.campaign.version}</span><details><summary>Technische Planreferenz</summary><code>{displaySha(chain.campaign.base_sha)}</code><small>Plan-Signatur: {displayValue(chain.campaign.plan_signature)}</small></details></div> : <p>Noch kein Umsetzungsplan aufgezeichnet.</p>}
        </KnowledgeStage>
      </ol>
      <section className="knowledge-branches" aria-label={`PR-Zweige für ${title}`}>
        <header><h3>Geplante PRs</h3><span>{branches.length} geplanter PR{branches.length === 1 ? "" : "s"}</span></header>
        {branches.length ? branches.map((branch) => <Branch branch={branch} key={branch.candidate.id} />) : <p>Noch keine geplanten PRs verknüpft.</p>}
      </section>
    </article>
  );
}

function chainMatches(chain: ControlKnowledgeChain, needle: string) {
  if (!needle) return true;
  const artifacts = [...list(chain.idea_group), ...list(chain.artifacts), ...list(chain.branches).flatMap((branch) => list(branch.artifacts))];
  const text = [
    chain.project.name,
    chain.idea_seed?.title,
    chain.campaign?.title,
    ...artifacts.flatMap((artifact) => [artifact.title, artifact.artifact_type, artifact.relative_path]),
    ...list(chain.branches).flatMap((branch) => [branch.candidate.title, branch.task?.issue_number, branch.task?.pr_number, branch.evidence?.summary]),
  ].filter((value) => value !== null && value !== undefined).join(" ").toLocaleLowerCase("de");
  return text.includes(needle);
}

function UnlinkedKnowledge({ data }: { data: ControlKnowledgeChainsResponse["unlinked"] }) {
  const seeds = list(data?.idea_seeds);
  const artifacts = list(data?.artifacts);
  const candidates = list(data?.candidates);
  const total = seeds.length + artifacts.length + candidates.length;
  if (!total) return null;
  return (
    <details className="knowledge-unlinked">
      <summary>{total} nicht verbundene Wissenselemente</summary>
      <p>Diese Einträge sind gespeichert, gehören aber noch nicht zu einer vollständigen Wissenskette.</p>
      {seeds.length ? <section><h3>Ursprüngliche Ideen</h3><ul>{seeds.map((seed) => <li key={seed.id}><strong>{seed.title}</strong><span>Projekt #{seed.project_id ?? "?"} · {domainStatusLabel(seed.status)}</span></li>)}</ul></section> : null}
      {artifacts.length ? <section><h3>Dokumente</h3><ul>{artifacts.map((artifact) => <li key={artifact.id}><strong>{artifact.title}</strong><span>Projekt #{artifact.project_id} · {domainStatusLabel(artifact.status)}</span></li>)}</ul></section> : null}
      {candidates.length ? <section><h3>Geplante PRs</h3><ul>{candidates.map((candidate) => <li key={candidate.id}><strong>{candidate.title}</strong><span>{candidate.campaign_id ? "Mit einem Umsetzungsplan verknüpft" : "Nicht mit einem Umsetzungsplan verknüpft"} · {domainStatusLabel(candidate.status)}</span></li>)}</ul></section> : null}
    </details>
  );
}

export function KnowledgeChainList({ data, search = "" }: KnowledgeChainListProps) {
  const chains = list(data?.chains);
  const needle = search.trim().toLocaleLowerCase("de");
  const visible = chains.filter((chain) => chainMatches(chain, needle));

  return (
    <div className="knowledge-chain-list">
      {visible.length ? visible.map((chain, index) => <KnowledgeChainCard chain={chain} key={`${chain.project.id}-${chain.idea_seed?.id || chain.campaign?.id || index}`} />) : (
        <div className="knowledge-chain-empty" role="status">
          <h2>{needle ? "Keine passende Wissenskette" : "Noch keine Wissenskette"}</h2>
          <p>{needle ? "Passe den Suchbegriff an." : "Sobald Ideen, Artefakte und PR-Slices verbunden sind, erscheint hier ihre nachvollziehbare Kette."}</p>
        </div>
      )}
      <UnlinkedKnowledge data={data?.unlinked ?? { idea_seeds: [], artifacts: [], candidates: [] }} />
    </div>
  );
}
