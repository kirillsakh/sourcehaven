import { useCallback, useEffect, useRef, useState } from "react";

import {
  ApiError,
  deleteDocument,
  listDocuments,
  uploadDocumentWithProgress,
  type DocumentInfo,
  type SessionLimits,
} from "@/lib/api";
import { newRequestId } from "@/lib/format";
import { describeError } from "@/lib/messages";
import { checkFiles } from "@/lib/upload-checks";

const POLL_INTERVAL_MS = 2000;
const MAX_PARALLEL_UPLOADS = 3;

export type UploadRow =
  | { key: string; name: string; status: "uploading"; fraction: number }
  | { key: string; name: string; status: "rejected"; reason: string };

export interface DocumentsState {
  documents: DocumentInfo[];
  uploads: UploadRow[];
  selected: ReadonlySet<string>;
  pollError: string | null;
  removing: ReadonlySet<string>;
  removeErrors: ReadonlyMap<string, string>;
  addFiles: (files: readonly File[]) => void;
  dismissUpload: (key: string) => void;
  toggle: (id: string) => void;
  setAllSelected: (all: boolean) => void;
  /** Remove a document; resolves to whether it was removed. */
  remove: (id: string) => Promise<boolean>;
}

interface UploadJob {
  key: string;
  file: File;
}

function isActive(document: DocumentInfo): boolean {
  return document.state === "queued" || document.state === "processing";
}

/**
 * Track the session's documents: listing, polling while any are being processed, uploads with
 * progress, and which ready documents are selected for questions.
 *
 * Args:
 *   limits: Session limits; nothing is requested until they are known.
 */
export function useDocuments(limits: SessionLimits | null): DocumentsState {
  const [documents, setDocuments] = useState<DocumentInfo[]>([]);
  const [uploads, setUploads] = useState<UploadRow[]>([]);
  const [selected, setSelected] = useState<ReadonlySet<string>>(new Set());
  const [pollError, setPollError] = useState<string | null>(null);

  const [removing, setRemoving] = useState<ReadonlySet<string>>(new Set());
  const [removeErrors, setRemoveErrors] = useState<ReadonlyMap<string, string>>(new Map());

  const knownReady = useRef<Set<string>>(new Set());
  // Read synchronously, so two calls in the same tick cannot both pass the guard.
  const removingNow = useRef<Set<string>>(new Set());
  // A list request that began before a removal may still return the document afterwards.
  const removedIds = useRef<Set<string>>(new Set());
  const queue = useRef<UploadJob[]>([]);
  const workers = useRef<number>(0);

  // Merge instead of replace: an upload that finished after a list request began must stay listed.
  const mergeDocuments = useCallback((all: readonly DocumentInfo[]): void => {
    const incoming: DocumentInfo[] = all.filter((doc) => !removedIds.current.has(doc.id));
    setDocuments((previous) => {
      const merged = new Map<string, DocumentInfo>(previous.map((doc) => [doc.id, doc]));
      for (const doc of incoming) {
        merged.set(doc.id, doc);
      }
      return Array.from(merged.values()).sort((a, b) => a.created_at.localeCompare(b.created_at));
    });
    const newlyReady: string[] = incoming
      .filter((doc) => doc.state === "ready" && !knownReady.current.has(doc.id))
      .map((doc) => doc.id);
    if (newlyReady.length > 0) {
      for (const id of newlyReady) {
        knownReady.current.add(id);
      }
      setSelected((previous) => new Set([...previous, ...newlyReady]));
    }
  }, []);

  // Resolves to whether polling should continue.
  const refresh = useCallback(
    async (signal: AbortSignal, reportAnyFailure: boolean): Promise<boolean> => {
      try {
        mergeDocuments(await listDocuments(signal));
        setPollError(null);
        return true;
      } catch (error) {
        if (signal.aborted) {
          return false;
        }
        const sessionLost: boolean = error instanceof ApiError && error.code === "session_required";
        if (sessionLost || reportAnyFailure) {
          setPollError(describeError(error));
        }
        return !sessionLost;
      }
    },
    [mergeDocuments],
  );

  useEffect(() => {
    if (limits === null) {
      return;
    }
    const controller = new AbortController();
    void (async (): Promise<void> => {
      await refresh(controller.signal, true);
    })();
    return () => controller.abort();
  }, [limits, refresh]);

  const hasActiveDocuments: boolean = documents.some(isActive);

  useEffect(() => {
    if (!hasActiveDocuments) {
      return;
    }
    const controller = new AbortController();
    let timer: number | undefined;
    // Each poll is scheduled only after the previous one settles, so requests never overlap.
    const poll = async (): Promise<void> => {
      if (await refresh(controller.signal, false)) {
        timer = window.setTimeout(() => void poll(), POLL_INTERVAL_MS);
      }
    };
    timer = window.setTimeout(() => void poll(), POLL_INTERVAL_MS);
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [hasActiveDocuments, refresh]);

  const uploadJob = useCallback(
    async ({ key, file }: UploadJob): Promise<void> => {
      const onProgress = (fraction: number): void => {
        setUploads((rows) =>
          rows.map((row) =>
            row.key === key && row.status === "uploading" ? { ...row, fraction } : row,
          ),
        );
      };
      try {
        const document: DocumentInfo = await uploadDocumentWithProgress(file, onProgress);
        mergeDocuments([document]);
        setUploads((rows) => rows.filter((row) => row.key !== key));
      } catch (error) {
        const rejected: UploadRow = {
          key,
          name: file.name,
          status: "rejected",
          reason: describeError(error),
        };
        setUploads((rows) => rows.map((row) => (row.key === key ? rejected : row)));
      }
    },
    [mergeDocuments],
  );

  // Workers share one queue, so the parallel limit also holds across separate drops.
  const drainQueue = useCallback(async (): Promise<void> => {
    for (let job = queue.current.shift(); job !== undefined; job = queue.current.shift()) {
      await uploadJob(job);
    }
  }, [uploadJob]);

  const addFiles = useCallback(
    (files: readonly File[]): void => {
      if (limits === null || files.length === 0) {
        return;
      }
      const usedSlots: number =
        documents.length + uploads.filter((row) => row.status === "uploading").length;
      const rows: UploadRow[] = [];
      for (const check of checkFiles(files, limits, usedSlots)) {
        const key: string = newRequestId();
        if (check.ok) {
          rows.push({ key, name: check.file.name, status: "uploading", fraction: 0 });
          queue.current.push({ key, file: check.file });
        } else {
          rows.push({ key, name: check.file.name, status: "rejected", reason: check.reason });
        }
      }
      setUploads((previous) => [...previous, ...rows]);
      while (workers.current < MAX_PARALLEL_UPLOADS) {
        workers.current += 1;
        void drainQueue().finally(() => {
          workers.current -= 1;
        });
      }
    },
    [limits, documents, uploads, drainQueue],
  );

  const dismissUpload = useCallback((key: string): void => {
    setUploads((previous) => previous.filter((row) => row.key !== key));
  }, []);

  const toggle = useCallback((id: string): void => {
    setSelected((previous) => {
      const next = new Set(previous);
      if (!next.delete(id)) {
        next.add(id);
      }
      return next;
    });
  }, []);

  const setAllSelected = useCallback(
    (all: boolean): void => {
      setSelected(
        new Set(all ? documents.filter((doc) => doc.state === "ready").map((doc) => doc.id) : []),
      );
    },
    [documents],
  );

  const remove = useCallback(async (id: string): Promise<boolean> => {
    if (removingNow.current.has(id)) {
      return false;
    }
    removingNow.current.add(id);
    setRemoving((previous) => new Set(previous).add(id));
    setRemoveErrors((previous) => {
      const next = new Map(previous);
      next.delete(id);
      return next;
    });
    try {
      await deleteDocument(id);
      removedIds.current.add(id);
      knownReady.current.delete(id);
      setDocuments((previous) => previous.filter((doc) => doc.id !== id));
      setSelected((previous) => {
        const next = new Set(previous);
        next.delete(id);
        return next;
      });
      return true;
    } catch (error) {
      setRemoveErrors((previous) => new Map(previous).set(id, describeError(error)));
      return false;
    } finally {
      removingNow.current.delete(id);
      setRemoving((previous) => {
        const next = new Set(previous);
        next.delete(id);
        return next;
      });
    }
  }, []);

  return {
    documents,
    uploads,
    selected,
    pollError,
    removing,
    removeErrors,
    addFiles,
    dismissUpload,
    toggle,
    setAllSelected,
    remove,
  };
}
