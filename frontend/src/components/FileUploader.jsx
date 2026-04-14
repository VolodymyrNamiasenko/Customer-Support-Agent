import React, { useRef } from "react";

export default function FileUploader({ onUpload }) {
  const inputRef = useRef(null);

  const handleFiles = (files) => {
    if (!files || files.length === 0) return;
    onUpload(files);
  };

  return (
    <div className="border border-dashed border-slate-700 rounded-xl p-6 bg-slate-900/60">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h3 className="text-lg font-semibold">Upload documents</h3>
          <p className="text-sm text-slate-400">
            Accepts .docx, .pdf, .md
          </p>
        </div>
        <button
          className="px-4 py-2 rounded-lg bg-cyan-500 text-slate-900 font-semibold"
          onClick={() => inputRef.current?.click()}
        >
          Choose files
        </button>
      </div>
      <input
        ref={inputRef}
        type="file"
        multiple
        accept=".docx,.pdf,.md"
        className="hidden"
        onChange={(e) => handleFiles(e.target.files)}
      />
    </div>
  );
}
