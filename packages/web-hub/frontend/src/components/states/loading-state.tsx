import { LoaderCircle } from "lucide-react";

import { StatePanel } from "@/components/states/state-panel";

interface LoadingStateProps {
  title?: string;
  description?: string;
}

export function LoadingState({
  description = "Die aktuellen Informationen werden geladen.",
  title = "Einen Moment bitte",
}: LoadingStateProps) {
  return (
    <StatePanel
      description={description}
      icon={
        <LoaderCircle className="size-5 motion-safe:animate-spin motion-reduce:animate-none" />
      }
      title={title}
    />
  );
}
