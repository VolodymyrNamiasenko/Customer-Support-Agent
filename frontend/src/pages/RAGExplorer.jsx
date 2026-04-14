import React, { useEffect, useState } from "react";
import { listDocuments, fetchChunks } from "../api/client.js";
import ChunkViewer from "../components/ChunkViewer.jsx";

export default function RAGExplorer() {
  const [docs, setDocs] = useState([]);
  const [filename, setFilename] = useState("");
  const [search, setSearch] = useState("");
  const [chunks, setChunks] = useState([]);

  useEffect(() => {
    listDocuments().then((data) => setDocs(data.documents));
  }, []);

  useEffect(() => {
    const load = async () => {
      const data = await fetchChunks({ filename, search, limit: 50, offset: 0 });
      setChunks(data.chunks);
    };
    load();
  }, [filename, search]);

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
        <input
          className="w-full md:w-2/3 px-4 py-2 rounded-lg bg-slate-900 border border-slate-700"
          placeholder="Semantic search..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <select
          className="px-4 py-2 rounded-lg bg-slate-900 border border-slate-700"
          value={filename}
          onChange={(e) => setFilename(e.target.value)}
        >
          <option value="">All documents</option>
          {docs.map((d) => (
            <option key={d.filename} value={d.filename}>
              {d.filename}
            </option>
          ))}
        </select>
      </div>

      <div className="grid gap-4">
        {chunks.map((chunk, idx) => (
          <ChunkViewer key={`${chunk.id}-${idx}`} chunk={chunk} />
        ))}
        {chunks.length === 0 && (
          <p className="text-slate-400">No chunks found.</p>
        )}
      </div>
    </div>
  );
}
