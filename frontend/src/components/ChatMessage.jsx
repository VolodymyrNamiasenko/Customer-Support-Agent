import React from "react";

export default function ChatMessage({ role, content, sources, guard }) {
  const isUser = role === "user";
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-2xl px-4 py-3 rounded-2xl ${
          isUser ? "bg-cyan-500 text-slate-950" : "bg-slate-800 text-slate-100"
        }`}
      >
        <div className="whitespace-pre-wrap text-sm">{content}</div>
        {!isUser && (
          <div className="mt-3 text-xs text-slate-300">
            {guard && (
              <span
                className={`mr-2 inline-flex items-center rounded-full px-2 py-1 ${
                  guard.is_valid ? "bg-emerald-500/30" : "bg-rose-500/30"
                }`}
              >
                {guard.is_valid ? "✓ Verified" : "⚠ Blocked"}
              </span>
            )}
            {sources?.length > 0 && (
              <span>Sources: {sources.join(", ")}</span>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
