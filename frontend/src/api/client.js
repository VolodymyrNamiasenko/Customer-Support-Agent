const API_BASE = (import.meta.env.VITE_API_BASE_URL || "http://localhost:8000").replace(/\/$/, "");

async function request(path, options = {}) {
  const res = await fetch(`${API_BASE}${path}`, options);
  const contentType = res.headers.get("content-type") || "";
  const data = contentType.includes("application/json") ? await res.json() : null;
  if (!res.ok) {
    const message = data?.detail || data?.error || "Request failed";
    throw new Error(message);
  }
  return data;
}

export async function listDocuments() {
  return request("/api/documents");
}

export async function uploadDocument(file) {
  const form = new FormData();
  form.append("file", file);
  return request("/api/documents/upload", { method: "POST", body: form });
}

export async function deleteDocument(filename) {
  return request(`/api/documents/${encodeURIComponent(filename)}`, { method: "DELETE" });
}

export async function fetchChunks({ filename, search, limit = 50, offset = 0 }) {
  const params = new URLSearchParams();
  if (filename) params.append("filename", filename);
  if (search) params.append("search", search);
  params.append("limit", limit);
  params.append("offset", offset);
  return request(`/api/rag/chunks?${params.toString()}`);
}

export async function chatQuery(payload) {
  return request("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
}
