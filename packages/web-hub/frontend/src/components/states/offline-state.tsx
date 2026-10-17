import { WifiOff } from "lucide-react";

import { Button } from "@/components/ui/button";
import { StatePanel } from "@/components/states/state-panel";

interface OfflineStateProps {
  onRetry?: () => void;
}

export function OfflineState({ onRetry }: OfflineStateProps) {
  return (
    <StatePanel
      action={
        onRetry ? <Button onClick={onRetry}>Verbindung erneut prüfen</Button> : undefined
      }
      description="Der lokale Python-Hub antwortet nicht. Deine Eingaben bleiben erhalten; prüfe den Dienst und versuche es erneut."
      icon={<WifiOff className="size-5 text-warning" />}
      role="alert"
      title="Hub nicht erreichbar"
    />
  );
}
