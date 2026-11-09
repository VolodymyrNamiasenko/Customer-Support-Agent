# Review, feedback and evaluation

## Workflow

Start the backend and frontend as in the README. Upload only the invented guide in `examples/synthetic_support_guide.md`, then ask about Demo Orders.

1. A chat response creates a persisted **pending** record with its question, answer, sources and rule-check result.
2. Open **Reviews**. Inspect the source, enter a reviewer name and record an approval/rejection. Missing sources or a failed rule check prevent approval.
3. The API release endpoint and **Copy approved answer** action work only for approved records. A later rejection revokes release. Raw draft text remains visible for human inspection.
4. Save a rating explicitly. Metrics count unique rated responses using each response's latest rating; history retains prior changes. No historical workplace feedback is preloaded.
5. Refresh after a version conflict. Decisions and ratings use SQLite transactions and expected versions to prevent stale updates overwriting newer reviews.

Reviewer identity is self-reported. This is a local single-user workflow, not enterprise authentication, separation of duties or a guarantee that advice is correct. Questions, answers and comments are private local data; do not commit the database.

## Reproducible checks

```bash
python -m unittest discover -s tests -v
python -m evaluation.run_checks
```

The evaluation command exits nonzero on a mismatch and prints observed results for a small, labelled synthetic rule set. It includes indirect SAP ownership, conflicting creation instructions and negated instructions. These are regression cases used during development, not a held-out model benchmark.

With the real application running locally and the synthetic guide indexed, you can explicitly exercise local model/API wiring:

```bash
python -m evaluation.run_checks --live-local-url http://127.0.0.1:8000
```

This sends one invented question, creates a real pending review record and checks the response contract/source presence. It does not judge factual equivalence. The command rejects non-local URLs. Record model/version, source corpus, independent questions and human ratings before claiming model quality. The 100+ pilot questions in the author's professional experience are not manufactured or verified by this demo.
