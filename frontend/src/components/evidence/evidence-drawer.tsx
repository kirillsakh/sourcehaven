import {
  useLayoutEffect,
  useRef,
  type MouseEvent,
  type PointerEvent,
  type ReactElement,
  type ReactNode,
  type RefObject,
} from "react";

import styles from "@/components/evidence/evidence-drawer.module.css";

/**
 * Show evidence in a modal side sheet for screens too narrow for the evidence column.
 *
 * Escape, the Close evidence button and a click on the backdrop all report through `onClose`;
 * the browser returns focus to the element that opened it.
 */
export function EvidenceDrawer({
  open,
  onClose,
  children,
}: {
  open: boolean;
  onClose: () => void;
  children: ReactNode;
}): ReactElement {
  const dialog: RefObject<HTMLDialogElement | null> = useRef<HTMLDialogElement | null>(null);
  const pressedOnBackdrop: RefObject<boolean> = useRef<boolean>(false);

  // A layout effect runs before the children's passive effects, so the dialog is already showing
  // when the highlighted evidence item scrolls itself into view.
  useLayoutEffect(() => {
    const element: HTMLDialogElement | null = dialog.current;
    if (element === null) {
      return;
    }
    if (open && !element.open) {
      element.showModal();
    } else if (!open && element.open) {
      element.close();
    }
  }, [open]);

  return (
    <dialog
      ref={dialog}
      className={styles.drawer}
      aria-label="Evidence"
      onClose={onClose}
      onPointerDown={(event: PointerEvent<HTMLDialogElement>): void => {
        pressedOnBackdrop.current = event.target === event.currentTarget;
      }}
      onClick={(event: MouseEvent<HTMLDialogElement>): void => {
        // The sheet fills the dialog, so a click that targets the dialog itself hit the backdrop.
        // A text selection dragged out of the sheet also ends there; it started on the sheet.
        if (event.target === event.currentTarget && pressedOnBackdrop.current) {
          onClose();
        }
      }}
    >
      <div className={styles.sheet}>
        <div className={styles.bar}>
          <button type="button" className={styles.close} onClick={onClose}>
            Close evidence
          </button>
        </div>
        {children}
      </div>
    </dialog>
  );
}
