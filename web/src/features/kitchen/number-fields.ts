"use client";
import { useEffect } from "react";

const LEADING_ZERO = /^(-?)0+(?=\d)/;

/** Typing into a number field that shows 0 replaces the 0: "05" reads "5".
 * React leaves "05" on screen because it equals 5, so after React has handled
 * the keystroke the field is tidied once. "0.5" stays as typed. */
export function useNumberFieldTidying() {
  useEffect(() => {
    const tidy = (event: Event) => {
      const field = event.target;
      if (!(field instanceof HTMLInputElement) || field.type !== "number") return;
      queueMicrotask(() => {
        const tidied = field.value.replace(LEADING_ZERO, "$1");
        if (tidied !== field.value) field.value = tidied;
      });
    };
    document.addEventListener("input", tidy);
    return () => document.removeEventListener("input", tidy);
  }, []);
}
