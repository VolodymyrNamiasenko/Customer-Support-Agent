import React from "react";

export default function Notification({ type = "info", message }) {
  if (!message) return null;
  const colors = {
    success: "bg-emerald-500/20 text-emerald-200 border-emerald-500/40",
    warning: "bg-amber-500/20 text-amber-200 border-amber-500/40",
    error: "bg-rose-500/20 text-rose-200 border-rose-500/40",
    info: "bg-sky-500/20 text-sky-200 border-sky-500/40"
  };
  return (
    <div className={`border px-4 py-3 rounded-lg text-sm ${colors[type]}`}>
      {message}
    </div>
  );
}
