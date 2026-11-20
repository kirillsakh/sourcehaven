import { useEffect, useRef, useState } from "react";

import { createSession, type SessionLimits } from "@/lib/api";
import { describeError } from "@/lib/messages";

export interface SessionState {
  limits: SessionLimits | null;
  error: string | null;
}

/** Start the visitor session once and expose its limits, or a visitor-facing start error. */
export function useSession(): SessionState {
  const [limits, setLimits] = useState<SessionLimits | null>(null);
  const [error, setError] = useState<string | null>(null);
  const started = useRef<boolean>(false);

  useEffect(() => {
    // React strict mode runs effects twice in development; the session must be created once.
    if (started.current) {
      return;
    }
    started.current = true;
    void (async (): Promise<void> => {
      try {
        const session = await createSession();
        setLimits(session.limits);
      } catch (caught) {
        setError(describeError(caught));
      }
    })();
  }, []);

  return { limits, error };
}
