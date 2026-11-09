import React, { useState } from "react";
import ChatMessage from "../components/ChatMessage.jsx";
import { chatQuery } from "../api/client.js";

export default function Chat() {
  const [messages, setMessages] = useState([]);
  const [question, setQuestion] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const [settings, setSettings] = useState({
    k: 5,
    temperature: 0.1,
    max_tokens: 512
  });

  const send = async () => {
    if (!question.trim() || sending) return;
    setSending(true);
    setError("");
    const userMsg = { role: "user", content: question };
    setMessages((m) => [...m, userMsg]);
    setQuestion("");
    try {
      const res = await chatQuery({ question, ...settings });
      const assistantMsg = {
        role: "assistant",
        content: res.answer,
        sources: res.sources,
        guard: res.hallucination_guard,
        reviewId: res.review_id
      };
      setMessages((m) => [...m, assistantMsg]);
    } catch (err) {
      setError(`Could not get an answer: ${err.message}. Check the backend and Ollama, then retry your question.`);
      setQuestion(question);
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="grid gap-6 md:grid-cols-[2fr,1fr]">
      <div className="space-y-4">
        <div className="min-h-[60vh] space-y-4">
          {messages.map((msg, idx) => (
            <ChatMessage
              key={idx}
              role={msg.role}
              content={msg.content}
              sources={msg.sources}
              guard={msg.guard}
              reviewId={msg.reviewId}
            />
          ))}
        </div>
        <div className="flex gap-3">
          <input
            className="flex-1 px-4 py-3 rounded-lg bg-slate-900 border border-slate-700"
            placeholder="Ask a question..."
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            disabled={sending}
            maxLength={16000}
          />
          <button
            className="px-5 py-3 rounded-lg bg-cyan-500 text-slate-950 font-semibold"
            onClick={send}
            disabled={sending || !question.trim()}
          >
            {sending ? "Answering..." : "Send"}
          </button>
        </div>
        {error && <p role="alert" className="text-red-400">{error}</p>}
        <p className="text-sm text-slate-400">Answers are saved as drafts. Review the sources and approve or reject each answer in the Reviews tab before using it.</p>
      </div>

      <div className="bg-slate-900/70 border border-slate-800 rounded-xl p-5 space-y-4">
        <h3 className="font-semibold">Settings</h3>
        <div className="space-y-3 text-sm">
          <label className="flex flex-col gap-2">
            K (snippets)
            <input
              type="range"
              min="1"
              max="15"
              value={settings.k}
              onChange={(e) =>
                setSettings((s) => ({ ...s, k: Number(e.target.value) }))
              }
            />
          </label>
          <label className="flex flex-col gap-2">
            Temperature
            <input
              type="range"
              min="0"
              max="1"
              step="0.05"
              value={settings.temperature}
              onChange={(e) =>
                setSettings((s) => ({
                  ...s,
                  temperature: Number(e.target.value)
                }))
              }
            />
          </label>
          <label className="flex flex-col gap-2">
            Max Tokens
            <select
              className="px-3 py-2 bg-slate-950 border border-slate-700 rounded"
              value={settings.max_tokens}
              onChange={(e) =>
                setSettings((s) => ({ ...s, max_tokens: Number(e.target.value) }))
              }
            >
              {[256, 512, 1024, 2048].map((v) => (
                <option key={v} value={v}>
                  {v}
                </option>
              ))}
            </select>
          </label>
        </div>
      </div>
    </div>
  );
}
