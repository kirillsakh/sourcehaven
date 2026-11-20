import { useEffect, useRef, type ReactElement, type RefObject } from "react";

import styles from "@/components/documents/select-all.module.css";
import type { SelectAllState } from "@/lib/selection";

export function SelectAll({
  state,
  disabled,
  onSelectAll,
}: {
  state: SelectAllState;
  disabled: boolean;
  onSelectAll: (all: boolean) => void;
}): ReactElement {
  const input: RefObject<HTMLInputElement | null> = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (input.current !== null) {
      input.current.indeterminate = state === "some";
    }
  }, [state]);

  return (
    <label className={styles.selectAll}>
      <input
        ref={input}
        type="checkbox"
        checked={state === "all"}
        disabled={disabled}
        onChange={(): void => onSelectAll(state !== "all")}
      />
      Use all ready documents
    </label>
  );
}
