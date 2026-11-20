import { useSyncExternalStore } from "react";

export const WIDE_LAYOUT_QUERY = "(min-width: 1280px)";
export const TWO_COLUMN_QUERY = "(min-width: 800px)";

/**
 * Report whether a media query matches right now.
 *
 * Environments without `matchMedia` (jsdom, the server) count as wide, where nothing is hidden.
 */
export function matchesQuery(query: string): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return true;
  }
  return window.matchMedia(query).matches;
}

function subscribeTo(query: string, notify: () => void): () => void {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return (): void => {};
  }
  const list: MediaQueryList = window.matchMedia(query);
  list.addEventListener("change", notify);
  return (): void => list.removeEventListener("change", notify);
}

/** Follow a media query; counts as matching during server rendering. */
export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (notify: () => void): (() => void) => subscribeTo(query, notify),
    (): boolean => matchesQuery(query),
    (): boolean => true,
  );
}
