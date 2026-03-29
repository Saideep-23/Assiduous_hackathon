import React from "react";

export function ProvenancePanel({
  open,
  onClose,
  children,
}: {
  open: boolean;
  onClose: () => void;
  children: React.ReactNode;
}) {
  if (!open) return null;
  return (
    <div className="prov-overlay" onClick={onClose}>
      <aside className="prov-panel" onClick={(e) => e.stopPropagation()}>
        <button type="button" className="btn btn-ghost prov-close" onClick={onClose}>
          Close
        </button>
        {children}
      </aside>
    </div>
  );
}
