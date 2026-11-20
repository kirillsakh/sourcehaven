import { useCallback, useEffect, useRef, useState } from "react";

import {
  ApiError,
  createConversation,
  getConversation,
  streamQuestion,
  type Conversation,
  type SessionLimits,
  type TurnEvent,
  type TurnSource,
} from "@/lib/api";
import { newRequestId } from "@/lib/format";
import { describeError } from "@/lib/messages";

const CONVERSATION_STORAGE_KEY = "sourcehaven.conversation";
const STOPPED_TEXT = "Stopped. This answer is incomplete.";
const CONNECTION_ENDED_TEXT = "The connection ended before the answer was complete.";

export interface TurnViewModel {
  key: string;
  status: string;
  question: string;
  text: string;
  sources: TurnSource[];
  invalidCitationLabels: string[];
  errorMessage: string | null;
  retryable: boolean;
  progressStage: string | null;
}

export interface ConversationState {
  turns: TurnViewModel[];
  generating: boolean;
  askError: string | null;
  question: string;
  setQuestion: (text: string) => void;
  ask: (text: string, documentIds: string[]) => Promise<void>;
  stop: () => void;
  activeTurnKey: string | null;
  activeLabel: string | null;
  /** Grows with every `activate` call, so repeating the same citation can replay its highlight. */
  activationCount: number;
  activate: (turnKey: string, label?: string) => void;
  /** Detach the sources of a removed document from every turn, keeping their labels. */
  markDocumentDeleted: (documentId: string) => void;
}

interface ActiveTurn {
  key: string | null;
  label: string | null;
}

const NO_ACTIVE_TURN: ActiveTurn = { key: null, label: null };

function readStoredConversation(): string | null {
  try {
    return window.sessionStorage.getItem(CONVERSATION_STORAGE_KEY);
  } catch {
    return null;
  }
}

function storeConversation(conversationId: string | null): void {
  try {
    if (conversationId === null) {
      window.sessionStorage.removeItem(CONVERSATION_STORAGE_KEY);
    } else {
      window.sessionStorage.setItem(CONVERSATION_STORAGE_KEY, conversationId);
    }
  } catch {
    // Without storage the conversation is simply not restored after a reload.
  }
}

function turnsFromConversation(conversation: Conversation): TurnViewModel[] {
  return conversation.turns.map((turn) => ({
    key: turn.id,
    status: turn.status,
    question: turn.question ?? "",
    text: turn.text,
    sources: turn.sources,
    invalidCitationLabels: [],
    errorMessage: null,
    retryable: false,
    progressStage: null,
  }));
}

function applyEvent(turn: TurnViewModel, event: TurnEvent): TurnViewModel {
  switch (event.type) {
    case "progress":
      return { ...turn, progressStage: event.stage };
    case "delta":
      return { ...turn, text: turn.text + event.text };
    case "sources":
      return {
        ...turn,
        sources: event.sources,
        invalidCitationLabels: event.invalidCitationLabels,
      };
    case "done":
      return { ...turn, status: "complete" };
    case "error":
      return {
        ...turn,
        status: event.status,
        errorMessage: event.message !== "" ? event.message : event.code,
        retryable: event.retryable,
      };
    default:
      return turn;
  }
}

function firstCitedLabel(sources: readonly TurnSource[]): string | null {
  return sources.find((source) => source.cited)?.label ?? null;
}

/**
 * Hold the conversation: its turns, the streamed answer being generated, and which turn (and
 * which of its citations) the evidence panel is showing.
 *
 * The conversation id is kept in `sessionStorage` and restored once the session limits are known.
 *
 * Args:
 *   limits: Session limits; the stored conversation is not loaded until they are known.
 */
export function useConversation(limits: SessionLimits | null): ConversationState {
  const [turns, setTurns] = useState<TurnViewModel[]>([]);
  const [question, setQuestion] = useState<string>("");
  const [askError, setAskError] = useState<string | null>(null);
  const [generating, setGenerating] = useState<boolean>(false);
  const [active, setActive] = useState<ActiveTurn>(NO_ACTIVE_TURN);
  const [activationCount, setActivationCount] = useState<number>(0);

  const abortRef = useRef<AbortController | null>(null);
  const conversationRef = useRef<string | null>(null);
  const restoreStarted = useRef<boolean>(false);

  useEffect(() => {
    if (limits === null || restoreStarted.current) {
      return;
    }
    restoreStarted.current = true;
    const stored: string | null = readStoredConversation();
    if (stored === null) {
      return;
    }
    void (async (): Promise<void> => {
      try {
        const conversation: Conversation = await getConversation(stored);
        if (conversationRef.current !== null) {
          return;
        }
        conversationRef.current = conversation.id;
        const restored: TurnViewModel[] = turnsFromConversation(conversation);
        setTurns(restored);
        setActive({ key: restored.at(-1)?.key ?? null, label: null });
      } catch {
        if (conversationRef.current === null) {
          storeConversation(null);
        }
      }
    })();
  }, [limits]);

  useEffect(
    () => () => {
      abortRef.current?.abort();
    },
    [],
  );

  const updateTurn: (key: string, change: (turn: TurnViewModel) => TurnViewModel) => void =
    useCallback((key: string, change: (turn: TurnViewModel) => TurnViewModel): void => {
      setTurns((previous: TurnViewModel[]): TurnViewModel[] =>
        previous.map((turn: TurnViewModel) => (turn.key === key ? change(turn) : turn)),
      );
    }, []);

  const ask = useCallback(
    async (text: string, documentIds: string[]): Promise<void> => {
      const trimmed: string = text.trim();
      if (trimmed === "" || documentIds.length === 0 || abortRef.current !== null) {
        return;
      }
      const previousActive: ActiveTurn = active;
      const key: string = newRequestId();
      const controller = new AbortController();
      abortRef.current = controller;
      setAskError(null);
      setGenerating(true);
      let streamEnded = false;
      try {
        let conversationId: string | null = conversationRef.current;
        if (conversationId === null) {
          conversationId = await createConversation();
          conversationRef.current = conversationId;
          storeConversation(conversationId);
        }
        setTurns((previous) => [
          ...previous,
          {
            key,
            status: "generating",
            question: trimmed,
            text: "",
            sources: [],
            invalidCitationLabels: [],
            errorMessage: null,
            retryable: false,
            progressStage: null,
          },
        ]);
        setActive({ key, label: null });
        setQuestion("");
        for await (const event of streamQuestion(
          conversationId,
          { clientRequestId: key, question: trimmed, documentIds },
          controller.signal,
        )) {
          if (event.type === "done" || event.type === "error") {
            streamEnded = true;
          }
          updateTurn(key, (turn) => applyEvent(turn, event));
          if (event.type === "sources") {
            const label: string | null = firstCitedLabel(event.sources);
            // Only a turn still on screen with no citation chosen yet takes the default.
            setActive((current) =>
              label !== null && current.key === key && current.label === null
                ? { key, label }
                : current,
            );
          }
        }
        if (!streamEnded) {
          updateTurn(key, (turn) => ({
            ...turn,
            status: "interrupted",
            errorMessage: CONNECTION_ENDED_TEXT,
          }));
        }
      } catch (error) {
        if (error instanceof ApiError) {
          setTurns((previous) => previous.filter((turn) => turn.key !== key));
          setActive((current) => (current.key === key ? previousActive : current));
          setQuestion(trimmed);
          setAskError(describeError(error));
        } else {
          const stopped: boolean = controller.signal.aborted;
          updateTurn(key, (turn) => ({
            ...turn,
            status: "interrupted",
            errorMessage: stopped ? STOPPED_TEXT : describeError(error),
          }));
        }
      } finally {
        abortRef.current = null;
        setGenerating(false);
      }
    },
    [active, updateTurn],
  );

  const stop = useCallback((): void => {
    abortRef.current?.abort();
  }, []);

  const activate = useCallback((turnKey: string, label?: string): void => {
    setActive({ key: turnKey, label: label ?? null });
    setActivationCount((count: number): number => count + 1);
  }, []);

  const markDocumentDeleted = useCallback((documentId: string): void => {
    setTurns((previous: TurnViewModel[]): TurnViewModel[] =>
      previous.map((turn: TurnViewModel): TurnViewModel => {
        if (!turn.sources.some((source: TurnSource) => source.document_id === documentId)) {
          return turn;
        }
        return {
          ...turn,
          sources: turn.sources.map(
            (source: TurnSource): TurnSource =>
              source.document_id === documentId
                ? { ...source, document_id: null, quote: "" }
                : source,
          ),
        };
      }),
    );
  }, []);

  return {
    turns,
    generating,
    askError,
    question,
    setQuestion,
    ask,
    stop,
    activeTurnKey: active.key,
    activeLabel: active.label,
    activationCount,
    activate,
    markDocumentDeleted,
  };
}
