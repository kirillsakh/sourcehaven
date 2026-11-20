import { useEffect, useRef, useState, type ReactElement, type RefObject } from "react";

import { describeLimits } from "@/components/documents/drop-tray";
import styles from "@/components/documents/drop-overlay.module.css";
import type { SessionLimits } from "@/lib/api";

interface Dragging {
  count: number | null;
}

function carriesFiles(event: DragEvent): boolean {
  return Array.from(event.dataTransfer?.types ?? []).includes("Files");
}

function describeDrop(count: number | null): string {
  if (count === null) {
    return "Drop to upload PDFs";
  }
  return `Drop to upload ${count} ${count === 1 ? "PDF" : "PDFs"}`;
}

export function DropOverlay({
  enabled,
  limits,
  onFiles,
}: {
  enabled: boolean;
  limits: SessionLimits | null;
  onFiles: (files: File[]) => void;
}): ReactElement | null {
  const [dragging, setDragging] = useState<Dragging | null>(null);
  const enabledRef: RefObject<boolean> = useRef<boolean>(enabled);
  const onFilesRef: RefObject<(files: File[]) => void> = useRef<(files: File[]) => void>(onFiles);

  useEffect(() => {
    enabledRef.current = enabled;
    onFilesRef.current = onFiles;
  }, [enabled, onFiles]);

  useEffect(() => {
    // Subscribed once, with the latest props read through refs, so the depth counter survives
    // `enabled` changing mid-drag and a drag that ends while disabled is still tracked.
    // dragenter and dragleave fire for every element the pointer crosses, so the overlay is
    // shown while the number of entered-but-not-left elements is positive.
    let depth: number = 0;

    function hide(): void {
      depth = 0;
      setDragging(null);
    }

    function onDragEnter(event: DragEvent): void {
      if (!carriesFiles(event)) {
        return;
      }
      depth += 1;
      const items: number = event.dataTransfer?.items.length ?? 0;
      setDragging({ count: items > 0 ? items : null });
    }

    function onDragOver(event: DragEvent): void {
      // Without this the browser navigates to a dropped PDF, even while uploads are disabled.
      if (carriesFiles(event)) {
        event.preventDefault();
      }
    }

    function onDragLeave(event: DragEvent): void {
      if (!carriesFiles(event)) {
        return;
      }
      depth -= 1;
      if (depth <= 0) {
        hide();
      }
    }

    function onDrop(event: DragEvent): void {
      if (!carriesFiles(event)) {
        return;
      }
      event.preventDefault();
      hide();
      if (enabledRef.current) {
        onFilesRef.current(Array.from(event.dataTransfer?.files ?? []));
      }
    }

    window.addEventListener("dragenter", onDragEnter);
    window.addEventListener("dragover", onDragOver);
    window.addEventListener("dragleave", onDragLeave);
    window.addEventListener("drop", onDrop);
    window.addEventListener("dragend", hide);
    return (): void => {
      window.removeEventListener("dragenter", onDragEnter);
      window.removeEventListener("dragover", onDragOver);
      window.removeEventListener("dragleave", onDragLeave);
      window.removeEventListener("drop", onDrop);
      window.removeEventListener("dragend", hide);
    };
  }, []);

  if (!enabled || dragging === null) {
    return null;
  }
  return (
    <div className={styles.overlay}>
      <div className={styles.message}>
        <p className={styles.title}>{describeDrop(dragging.count)}</p>
        {limits !== null && <p className={styles.limits}>{describeLimits(limits)}</p>}
      </div>
    </div>
  );
}
