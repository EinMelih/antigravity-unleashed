import { ArrowUpRight, FolderGit2, GitBranch } from "lucide-react";

import type { HubProject } from "@/api/contracts";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { projectHealth } from "@/features/studio/model";
import { ProjectRemovalDialog } from "@/features/studio/project-removal-dialog";

interface ProjectCardProps {
  onRemoved: () => Promise<void>;
  project: HubProject;
}

export function ProjectCard({ onRemoved, project }: ProjectCardProps) {
  const health = projectHealth(project);
  const title = project.github_repo || project.name;
  const action = { href: `#/projects/${project.id}`, label: "Projekt öffnen" };

  return (
    <article className="project-card">
      <div className="flex min-w-0 items-start gap-3">
        <span className="project-card-icon">
          <FolderGit2 className="size-4" />
        </span>
        <div className="min-w-0">
          <h3 className="truncate font-semibold">{title}</h3>
          <p className="mt-1 truncate text-sm text-muted-foreground">
            {project.antigravity_linked
              ? project.antigravity_project_name || "Mit Anti-Gravity verknüpft"
              : "Noch nicht mit Anti-Gravity verknüpft"}
          </p>
        </div>
        <Badge className="ml-auto shrink-0" variant={health.tone}>
          {health.label}
        </Badge>
      </div>
      <div className="mt-5 flex flex-wrap items-center gap-3 border-t border-border pt-4">
        <span className="flex min-w-0 items-center gap-1.5 text-xs text-muted-foreground">
          <GitBranch className="size-3.5" />
          <span className="truncate">{project.git_branch || project.default_branch || "main"}</span>
        </span>
        <Button asChild className="ml-auto" size="sm" variant="secondary">
          <a
            href={action.href}
          >
            {action.label}
            <ArrowUpRight className="size-3.5" />
          </a>
        </Button>
        <ProjectRemovalDialog onRemoved={onRemoved} project={project} />
      </div>
    </article>
  );
}
