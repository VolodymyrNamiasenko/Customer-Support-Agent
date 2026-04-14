import React from "react";

export default function DocumentTable({ documents, onDelete }) {
  return (
    <div className="overflow-hidden rounded-xl border border-slate-800">
      <table className="w-full text-sm">
        <thead className="bg-slate-900">
          <tr>
            <th className="text-left px-4 py-3">Filename</th>
            <th className="text-left px-4 py-3">Type</th>
            <th className="text-left px-4 py-3">Uploaded</th>
            <th className="text-left px-4 py-3">Chunks</th>
            <th className="text-left px-4 py-3">Status</th>
            <th className="text-right px-4 py-3">Actions</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-800">
          {documents.map((doc) => (
            <tr key={doc.filename} className="bg-slate-950/40">
              <td className="px-4 py-3">{doc.filename}</td>
              <td className="px-4 py-3 uppercase">{doc.file_type}</td>
              <td className="px-4 py-3">{doc.upload_timestamp}</td>
              <td className="px-4 py-3">{doc.chunk_count}</td>
              <td className="px-4 py-3">{doc.status}</td>
              <td className="px-4 py-3 text-right">
                <button
                  className="text-rose-300 hover:text-rose-200"
                  onClick={() => onDelete(doc.filename)}
                >
                  Delete
                </button>
              </td>
            </tr>
          ))}
          {documents.length === 0 && (
            <tr>
              <td className="px-4 py-6 text-center text-slate-400" colSpan={6}>
                No documents uploaded yet.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
