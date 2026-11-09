import React, { useEffect, useState } from 'react';
import { listReviews, reviewMetrics, reviewDetail, submitReview, releasedAnswer } from '../api/client.js';

function ReviewCard({ item, refresh }) {
  const [actor, setActor] = useState('');
  const [note, setNote] = useState('');
  const [rating, setRating] = useState('');
  const [events, setEvents] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const eligible = item.response.sources?.length > 0 && item.response.hallucination_guard?.is_valid;
  const save = async (action, value) => {
    setBusy(true); setError('');
    try {
      await submitReview(item.id, action, { version: item.version, actor, note, ...value });
      setEvents(null); setCopied(false); await refresh();
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  };
  const copy = async () => {
    setError('');
    try { const result = await releasedAnswer(item.id); await navigator.clipboard.writeText(result.answer); setCopied(true); }
    catch (e) { setError(e.message); }
  };
  return <article id={item.id} className="p-5 rounded-xl border border-slate-700 bg-slate-900 space-y-3">
    <div className="flex justify-between gap-4"><h2 className="font-semibold">{item.question}</h2><span>{item.status}</span></div>
    <p className="whitespace-pre-wrap text-sm">{item.response.answer}</p>
    <p className="text-sm text-slate-400">Sources: {item.response.sources?.join(', ') || 'No supporting source'}</p>
    {!eligible && <p className="text-amber-300 text-sm">Approval is unavailable because evidence is missing or a rule check failed.</p>}
    <div className="grid md:grid-cols-2 gap-3">
      <label className="text-sm">Reviewer name<input className="block w-full rounded bg-slate-800 p-2 mt-1" value={actor} maxLength={80} onChange={e => setActor(e.target.value)} /></label>
      <label className="text-sm">Notes<textarea className="block w-full rounded bg-slate-800 p-2 mt-1" value={note} maxLength={4000} onChange={e => setNote(e.target.value)} /></label>
    </div>
    <div className="flex flex-wrap items-center gap-3 text-sm">
      <button disabled={busy || !actor.trim() || !eligible} className="bg-emerald-800 rounded px-3 py-2 disabled:opacity-40" onClick={() => save('decision', { decision: 'approved' })}>Approve</button>
      <button disabled={busy || !actor.trim()} className="bg-rose-900 rounded px-3 py-2 disabled:opacity-40" onClick={() => save('decision', { decision: 'rejected' })}>Reject</button>
      <label>Rating <select aria-label="Rating" className="bg-slate-800 p-2 rounded" value={rating} onChange={e => setRating(e.target.value)}>
        <option value="">Choose</option>{[1, 2, 3, 4, 5].map(n => <option key={n} value={n}>{n} / 5</option>)}
      </select></label>
      <button disabled={busy || !actor.trim() || !rating} className="bg-slate-700 rounded px-3 py-2 disabled:opacity-40" onClick={() => save('rating', { rating: Number(rating) })}>Save rating</button>
      {item.status === 'approved' && <button className="underline text-cyan-300" onClick={copy}>{copied ? 'Copied approved answer' : 'Copy approved answer'}</button>}
      <button className="underline" onClick={async () => { try { setEvents((await reviewDetail(item.id)).events); } catch (e) { setError(e.message); } }}>Review history</button>
    </div>
    {item.rating != null && <p className="text-sm">Saved rating: {item.rating} / 5</p>}
    {events && <ol className="text-xs text-slate-400 space-y-1">{events.map((e, i) => <li key={i}>{e.created_at} · {e.actor} · {e.action}{e.note ? ` · ${e.note}` : ''}</li>)}</ol>}
    {error && <p role="alert" className="text-red-300">{error}</p>}
  </article>;
}

export default function Reviews() {
  const [status, setStatus] = useState('pending'); const [offset, setOffset] = useState(0);
  const [data, setData] = useState({ items: [], total: 0 }); const [metrics, setMetrics] = useState(null);
  const [error, setError] = useState(''); const [loading, setLoading] = useState(true);
  const load = async () => {
    setError(''); setLoading(true);
    try { const [rows, counts] = await Promise.all([listReviews(status, offset), reviewMetrics()]); setData(rows); setMetrics(counts); }
    catch (e) { setError(e.message); } finally { setLoading(false); }
  };
  useEffect(() => { let active = true; setLoading(true); setError('');
    Promise.all([listReviews(status, offset), reviewMetrics()]).then(([rows, counts]) => { if (active) { setData(rows); setMetrics(counts); } })
      .catch(e => { if (active) setError(e.message); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [status, offset]);
  return <div className="space-y-5">
    <h1 className="text-xl font-semibold">Answer review and feedback</h1>
    {metrics && <p className="text-sm text-slate-300">{metrics.total} responses · {metrics.pending} awaiting review · {metrics.approved} approved · {metrics.rejected} rejected · {metrics.rated_responses} rated{metrics.mean_rating != null ? ` · average ${metrics.mean_rating.toFixed(1)} / 5` : ''}</p>}
    <label>Show <select className="bg-slate-800 p-2 rounded ml-2" value={status} onChange={e => { setStatus(e.target.value); setOffset(0); }}>
      <option value="">All</option>{['pending', 'approved', 'rejected'].map(s => <option key={s}>{s}</option>)}
    </select></label>
    {error && <p role="alert" className="text-red-300">{error}</p>}
    {loading ? <p>Loading reviews…</p> : data.items.length ? data.items.map(item => <ReviewCard key={item.id} item={item} refresh={load} />) : <p>No responses in this view. Ask a question in Chat to create a review draft.</p>}
    <div className="flex gap-4"><button disabled={loading || offset === 0} onClick={() => setOffset(Math.max(0, offset - 25))}>Previous</button>
      <button disabled={loading || offset + 25 >= data.total} onClick={() => setOffset(offset + 25)}>Next</button></div>
  </div>;
}
