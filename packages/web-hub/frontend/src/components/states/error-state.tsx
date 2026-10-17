import { CircleAlert } from "lucide-react";

import { Button } from "@/components/ui/button";
import { StatePanel } from "@/components/states/state-panel";

interface ErrorStateProps {
  title?: string;
  description: string;
  onRetry?: () => void;
}

export function ErrorState({
  description,
  onRetry,
  title = "Das hat nicht funktioniert",
}: ErrorStateProps) {
  return (
    <StatePanel
      action={
        onRetry ? <Button onClick={onRetry}>Erneut versuchen</Button> : undefined
      }
      description={description}
      icon={<CircleAlert className="size-5 text-destructive" />}
      role="alert"
      title={title}
    />
  );
}
