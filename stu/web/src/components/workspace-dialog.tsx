"use client";

import { X } from "@phosphor-icons/react";
import { useEffect, type ReactNode } from "react";

export function WorkspaceDialog({
  open,
  title,
  onClose,
  children,
}: {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
  useEffect(() => {
    if (!open) return;
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [onClose, open]);

  if (!open) return null;
  return (
    <div className="workspace-dialog-backdrop" role="presentation" onMouseDown={onClose}>
      <section
        aria-labelledby="workspace-dialog-title"
        aria-modal="true"
        className="workspace-dialog"
        role="dialog"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header>
          <h2 id="workspace-dialog-title">{title}</h2>
          <button aria-label="Close" className="icon-button" type="button" onClick={onClose}>
            <X size={18} weight="bold" />
          </button>
        </header>
        {children}
      </section>
    </div>
  );
}
