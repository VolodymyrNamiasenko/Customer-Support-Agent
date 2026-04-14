import React from "react";

export default function ChunkViewer({ chunk }) {
  return (
    <div className="border border-slate-800 rounded-xl p-4 bg-slate-900/60">
      <div className="flex items-center justify-between mb-2">
        <div className="text-xs text-slate-400">
          {chunk.metadata?.manual_name || "Unknown Source"}
        </div>
        {chunk.score !== undefined && (
          <span className="text-xs text-cyan-300">
            score: {chunk.score.toFixed(3)}
          </span>
        )}
      </div>
      <p className="text-sm text-slate-200 whitespace-pre-wrap">
        {chunk.content_preview}
      </p>
      <div className="mt-3 flex flex-wrap gap-2 text-xs text-slate-400">
        {Object.entries(chunk.metadata || {}).slice(0, 4).map(([k, v]) => (
          <span key={k} className="px-2 py-1 bg-slate-800 rounded">
            {k}: {String(v)}
          </span>
        ))}
      </div>
    </div>
  );
}
