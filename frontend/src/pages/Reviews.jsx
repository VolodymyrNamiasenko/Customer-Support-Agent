import React, { useEffect, useState } from 'react';
import { listReviews, reviewMetrics, reviewDetail, submitReview, releasedAnswer, expertQueue, expertPolicy } from '../api/client.js';

function ReviewCard({ item, refresh, buckets }) {
  const [actor, setActor] = useState('');
  const [note, setNote] = useState('');
  const [rating, setRating] = useState('');
  const [feedback, setFeedback] = useState('');
  const [correctness, setCorrectness] = useState('');
  const [bucket, setBucket] = useState('');
  const [evidence, setEvidence] = useState('');
  const [sme, setSme] = useState(false);
  const [trace, setTrace] = useState(null);
  const [events, setEvents] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const completed = ['completed', 'legacy'].includes(item.generation_state);
  const eligible = completed && item.response.sources?.length > 0 && item.response.hallucination_guard?.is_valid && !['incorrect', 'partially_correct'].includes(item.correctness);
  const save = async (action, value) => {
    setBusy(true); setError('');
    try {
      const body = action === 'rating' ? { version: item.version, note: feedback, ...value }
        : action === 'expert-verdict' ? { version: item.version, rationale: note, evidence: evidence.split('\n').map(e => e.trim()).filter(Boolean), ...value }
        : { version: item.version, actor, note, ...value };
      await submitReview(item.id, action, body);
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
    <p className="text-sm">Expert correctness: {item.correctness || 'not reviewed'}{item.error_bucket ? ` · ${item.error_bucket}` : ''}</p>
    {item.selection_reasons && <p className="text-sm text-amber-300">Queue reasons: {item.selection_reasons.join(', ')}</p>}
    {!completed && <p className="text-sm text-amber-300">Generation: {item.generation_state}. This is not a completed answer.</p>}
    {!eligible && <p className="text-amber-300 text-sm">Approval is unavailable because evidence is missing or a rule check failed.</p>}
    <div className="grid md:grid-cols-2 gap-3">
      <label className="text-sm">Reviewer name<input className="block w-full rounded bg-slate-800 p-2 mt-1" value={actor} maxLength={80} onChange={e => setActor(e.target.value)} /></label>
      <label className="text-sm">Notes<textarea className="block w-full rounded bg-slate-800 p-2 mt-1" value={note} maxLength={4000} onChange={e => setNote(e.target.value)} /></label>
    </div>
    <div className="flex flex-wrap items-center gap-3 text-sm">
      <button disabled={busy || !actor.trim() || !eligible} className="bg-emerald-800 rounded px-3 py-2 disabled:opacity-40" onClick={() => save('decision', { decision: 'approved' })}>Approve</button>
      <button disabled={busy || !actor.trim()} className="bg-rose-900 rounded px-3 py-2 disabled:opacity-40" onClick={() => save('decision', { decision: 'rejected' })}>Reject</button>
      <label>Customer satisfaction (not correctness) <select aria-label="Rating" className="bg-slate-800 p-2 rounded" value={rating} onChange={e => setRating(e.target.value)}>
        <option value="">Choose</option>{[1, 2, 3, 4, 5].map(n => <option key={n} value={n}>{n} / 5</option>)}
      </select></label>
      <button disabled={busy || !completed || !rating} className="bg-slate-700 rounded px-3 py-2 disabled:opacity-40" onClick={() => save('rating', { rating: Number(rating) })}>Save anonymous rating</button>
      {item.status === 'approved' && <button className="underline text-cyan-300" onClick={copy}>{copied ? 'Copied approved answer' : 'Copy approved answer'}</button>}
      <button className="underline" onClick={async () => { try { const detail = await reviewDetail(item.id); setEvents(detail.events); setTrace(detail.retrieval_trace); } catch (e) { setError(e.message); } }}>History and retrieval trace</button>
    </div>
    <label className="block text-sm">Customer feedback (optional; do not enter the rater's identity)<textarea className="block w-full rounded bg-slate-800 p-2" value={feedback} maxLength={4000} onChange={e => setFeedback(e.target.value)} /></label>
    <fieldset className="border border-slate-700 rounded p-3 space-y-3">
      <legend>Separate expert review</legend>
      <label className="block text-sm"><input type="checkbox" checked={sme} onChange={e => setSme(e.target.checked)} /> I am reviewing as Manufacturing Engineer (self-reported, not authenticated).</label>
      <label>Correctness <select aria-label="Expert correctness" className="bg-slate-800 p-2 rounded" value={correctness} onChange={e => setCorrectness(e.target.value)}><option value="">Choose</option>{['correct', 'partially_correct', 'incorrect'].map(v => <option key={v}>{v}</option>)}</select></label>
      <label className="block">Error bucket <select aria-label="Error bucket" className="bg-slate-800 p-2 rounded" value={bucket} onChange={e => setBucket(e.target.value)} disabled={correctness === 'correct'}><option value="">Choose</option>{buckets.map(v => <option key={v}>{v}</option>)}</select></label>
      <label className="block text-sm">Evidence references, one per line<textarea className="block w-full rounded bg-slate-800 p-2" value={evidence} maxLength={4000} onChange={e => setEvidence(e.target.value)} /></label>
      <p className="text-sm">Use Notes above for expert rationale. Ratings and approvals do not supply a correctness label.</p>
      <button className="bg-cyan-900 rounded px-3 py-2 disabled:opacity-40" disabled={busy || !completed || !sme || !correctness || !note.trim() || !evidence.trim() || (correctness !== 'correct' && !bucket)} onClick={() => save('expert-verdict', { correctness, error_bucket: correctness === 'correct' ? null : bucket })}>Save SME verdict</button>
    </fieldset>
    {item.rating != null && <p className="text-sm">Saved rating: {item.rating} / 5</p>}
    {events && <ol className="text-xs text-slate-400 space-y-1">{events.map((e, i) => <li key={i}>{e.created_at} · {e.actor} · {e.action}{e.note ? ` · ${e.note}` : ''}</li>)}</ol>}
    {events && <details><summary>Chroma retrieval trace (context supplied to DSPy, not proven claim usage)</summary><pre className="text-xs whitespace-pre-wrap break-all">{trace ? JSON.stringify(trace, null, 2) : 'Trace unavailable for this legacy record or retrieval has not completed.'}</pre></details>}
    {error && <p role="alert" className="text-red-300">{error}</p>}
  </article>;
}

export default function Reviews() {
  const [status, setStatus] = useState('pending'); const [offset, setOffset] = useState(0);
  const [queueOnly, setQueueOnly] = useState(false); const [buckets, setBuckets] = useState([]);
  const [data, setData] = useState({ items: [], total: 0 }); const [metrics, setMetrics] = useState(null);
  const [error, setError] = useState(''); const [loading, setLoading] = useState(true);
  const load = async () => {
    setError(''); setLoading(true);
    try { const [rows, counts] = await Promise.all([queueOnly ? expertQueue(offset) : listReviews(status, offset), reviewMetrics()]); setData(rows); setMetrics(counts); }
    catch (e) { setError(e.message); } finally { setLoading(false); }
  };
  useEffect(() => { let active = true; setLoading(true); setError('');
    Promise.all([queueOnly ? expertQueue(offset) : listReviews(status, offset), reviewMetrics(), expertPolicy()]).then(([rows, counts, policy]) => { if (active) { setData(rows); setMetrics(counts); setBuckets(policy.error_buckets); } })
      .catch(e => { if (active) setError(e.message); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [status, offset, queueOnly]);
  return <div className="space-y-5">
    <h1 className="text-xl font-semibold">Answer review and feedback</h1>
    {metrics && <div className="text-sm space-y-2 text-slate-300">
      <p>{metrics.total} stored responses · {metrics.pending} pending release review · {metrics.approved} approved · {metrics.rejected} rejected</p>
      <p>Customer satisfaction: {metrics.pilot.satisfaction.mean_rating?.toFixed(2) ?? 'not measured'} / 5 · N={metrics.pilot.satisfaction.N}</p>
      <p>Expert correctness in selected sample: {metrics.pilot.expert_correctness.counts.correct}/{metrics.pilot.expert_correctness.N_reviewed} correct · {metrics.pilot.expert_correctness.counts.partially_correct} partially correct · {metrics.pilot.expert_correctness.counts.incorrect} incorrect. This is not whole-pilot accuracy.</p>
      <p>Legacy/non-pilot responses excluded from pilot metrics: {metrics.pilot.legacy_or_nonpilot_responses}</p>
    </div>}
    <label className="block"><input type="checkbox" checked={queueOnly} onChange={e => { setQueueOnly(e.target.checked); setOffset(0); }} /> Expert queue: low ratings, stable 10% sample of high ratings, and all guard-relevant high ratings</label>
    <label>Release status (all statuses in expert queue) <select disabled={queueOnly} className="bg-slate-800 p-2 rounded ml-2" value={status} onChange={e => { setStatus(e.target.value); setOffset(0); }}>
      <option value="">All</option>{['pending', 'approved', 'rejected'].map(s => <option key={s}>{s}</option>)}
    </select></label>
    {error && <p role="alert" className="text-red-300">{error}</p>}
    {loading ? <p>Loading reviews…</p> : data.items.length ? data.items.map(item => <ReviewCard key={item.id} item={item} refresh={load} buckets={buckets} />) : <p>No responses in this view. Ask a question in Chat to create a review draft.</p>}
    <div className="flex gap-4"><button disabled={loading || offset === 0} onClick={() => setOffset(Math.max(0, offset - 25))}>Previous</button>
      <button disabled={loading || offset + 25 >= data.total} onClick={() => setOffset(offset + 25)}>Next</button></div>
  </div>;
}
