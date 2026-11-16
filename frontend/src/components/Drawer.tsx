/**
 * Drawer — the click-in pattern. No page navigation; the detail slides
 * over the current context. Close with X, Escape, or clicking the
 * backdrop. The content is whatever the caller renders.
 */

import React, { useEffect } from 'react';

export function Drawer({
  open,
  onClose,
  title,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: React.ReactNode;
}) {
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50" role="dialog" aria-modal="true" aria-label={title}>
      <div
        className="absolute inset-0 bg-black/60"
        onClick={onClose}
        aria-hidden="true"
      />
      <div
        className="absolute right-0 top-0 bottom-0 w-full max-w-2xl bg-[#1a1a1a] border-l border-[#3a3a3a] shadow-2xl overflow-y-auto"
        style={{ animation: 'slideIn 200ms ease-out' }}
      >
        <style>{`@keyframes slideIn { from { transform: translateX(100%); } to { transform: translateX(0); } }`}</style>
        <div className="sticky top-0 bg-[#1a1a1a] border-b border-[#2e2e2e] px-6 py-4 flex items-center justify-between z-10">
          <h2 className="text-lg font-bold text-white truncate">{title}</h2>
          <button
            onClick={onClose}
            className="text-[#6A6E73] hover:text-white transition p-2 -mr-2"
            aria-label="Close drawer"
          >
            <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M5 5l10 10M15 5L5 15" />
            </svg>
          </button>
        </div>
        <div className="p-6 space-y-4">{children}</div>
      </div>
    </div>
  );
}
