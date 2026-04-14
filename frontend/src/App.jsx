import React from "react";
import { NavLink, Routes, Route, Navigate } from "react-router-dom";
import DocumentManager from "./pages/DocumentManager.jsx";
import RAGExplorer from "./pages/RAGExplorer.jsx";
import Chat from "./pages/Chat.jsx";

const NavTab = ({ to, label }) => (
  <NavLink
    to={to}
    className={({ isActive }) =>
      `px-4 py-2 rounded-full text-sm font-semibold transition ${
        isActive ? "bg-cyan-500 text-slate-950" : "bg-slate-800 text-slate-200"
      }`
    }
  >
    {label}
  </NavLink>
);

export default function App() {
  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950">
      <header className="px-8 py-6 flex items-center justify-between border-b border-slate-800">
        <div>
          <h1 className="text-2xl font-bold">Pulse RAG Manager</h1>
          <p className="text-sm text-slate-400">
            Unified document management + support chat
          </p>
        </div>
        <nav className="flex gap-3">
          <NavTab to="/documents" label="Documents" />
          <NavTab to="/explorer" label="Explorer" />
          <NavTab to="/chat" label="Chat" />
        </nav>
      </header>

      <main className="px-8 py-6">
        <Routes>
          <Route path="/" element={<Navigate to="/documents" replace />} />
          <Route path="/documents" element={<DocumentManager />} />
          <Route path="/explorer" element={<RAGExplorer />} />
          <Route path="/chat" element={<Chat />} />
        </Routes>
      </main>
    </div>
  );
}
