"use client";

/**
 * Hands a saved investigation from the account dock to the case view.
 *
 * The dock lives in the layout and the case view lives in the page, so
 * reopening a case previously rendered a second, smaller summary of it. A
 * victim returning to their case should get the investigation they left, not a
 * reduced copy of it, so the two are connected rather than duplicated.
 */
type SavedCase = {id: string; [key: string]: unknown};

const listeners = new Set<(saved: SavedCase) => void>();

export function openSavedCase(saved: SavedCase) {
  listeners.forEach(listener => listener(saved));
  return listeners.size > 0;
}

export function onOpenSavedCase(listener: (saved: SavedCase) => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
