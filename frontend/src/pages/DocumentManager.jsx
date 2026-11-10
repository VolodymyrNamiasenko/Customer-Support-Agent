import React, { useEffect, useState } from "react";
import FileUploader from "../components/FileUploader.jsx";
import DocumentTable from "../components/DocumentTable.jsx";
import Notification from "../components/Notification.jsx";
import { listDocuments, uploadDocument, deleteDocument } from "../api/client.js";

export default function DocumentManager() {
  const [docs, setDocs] = useState([]);
  const [stats, setStats] = useState({ total_documents: 0, total_chunks: 0 });
  const [notice, setNotice] = useState(null);
  const [changeId, setChangeId] = useState('');

  const refresh = async () => {
    const data = await listDocuments();
    setDocs(data.documents);
    setStats({ total_documents: data.total_documents, total_chunks: data.total_chunks });
  };

  useEffect(() => {
    refresh().catch((e) => setNotice({ type: "warning", message: e.message }));
  }, []);

  const handleUpload = async (files) => {
    for (const file of files) {
      try {
        const res = await uploadDocument(file, changeId);
        setNotice({ type: "success", message: `✅ ${res.filename} added — ${res.chunks_created} chunks created.` });
        await refresh();
      } catch (e) {
        setNotice({ type: "warning", message: `⚠️ ${e.message}` });
      }
    }
  };

  const handleDelete = async (filename) => {
    if (!confirm(`Delete ${filename}?`)) return;
    try {
      await deleteDocument(filename, changeId);
      await refresh();
    } catch (e) {
      setNotice({ type: "warning", message: e.message });
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between bg-slate-900/70 border border-slate-800 rounded-xl px-6 py-4">
        <div>
          <h2 className="text-lg font-semibold">Knowledge Base</h2>
          <p className="text-sm text-slate-400">
            {stats.total_documents} documents · {stats.total_chunks} chunks
          </p>
        </div>
      </div>

      {notice && <Notification type={notice.type} message={notice.message} />}

      <label className="block text-sm space-y-2">Reviewed corpus change ID
        <input className="block w-full rounded bg-slate-800 p-2" value={changeId} onChange={e => setChangeId(e.target.value)} placeholder="Prepare one evaluated change per upload/delete" />
        <span className="block text-slate-400">Pilot changes require an SME verdict, frozen held-out before/after runs and a human-approved change plan. Ratings alone never authorize changes. See docs/PILOT.md.</span>
      </label>

      <FileUploader onUpload={handleUpload} />

      <DocumentTable documents={docs} onDelete={handleDelete} />
    </div>
  );
}
