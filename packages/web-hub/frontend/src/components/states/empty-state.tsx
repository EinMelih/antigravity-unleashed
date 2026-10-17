import { Inbox } from "lucide-react";
import type { ReactNode } from "react";

import { StatePanel } from "@/components/states/state-panel";

interface EmptyStateProps {
  title: string;
  description: string;
  action?: ReactNode;
}

export function EmptyState({ action, description, title }: EmptyStateProps) {
  return (
    <StatePanel
      action={action}
      description={description}
      icon={<Inbox className="size-5" />}
      title={title}
    />
  );
}
