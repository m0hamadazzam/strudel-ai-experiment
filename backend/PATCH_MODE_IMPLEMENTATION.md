# Patch Mode Implementation

## Goal

Prevent full-buffer overwrite behavior in the REPL Copilot flow and switch to reviewable, minimal edits with explicit user approval.

## Current Architecture

1. Model generation still produces full candidate Strudel code (`code`).
2. Backend computes deterministic patch operations from `current_code -> code`.
3. API returns both:
   - `code` (full candidate, backward-compatible)
   - `patch_ops` (minimal operations with character offsets)
   - `patch_stats` (additions/deletions/operation count)
4. Frontend chat shows hunk-level diff previews (green additions / red deletions).
5. REPL editor shows inline hunk review UI:
   - red highlight on code to be replaced/deleted
   - green preview block for inserted/replacement text
   - per-hunk `Accept` / `Reject` controls inline in the editor
6. Chat interface also supports per-hunk `Accept` / `Reject`.
7. Hunk decisions from chat and editor stay synchronized.
8. Patch activation is guarded by base-code match to prevent applying stale diffs.

## API Contract

`POST /api/copilot/chat`

Response fields:
- `code: string`
- `explanation: string`
- `patch_ops: Array<{ op: "insert" | "delete" | "replace", start: number, end: number, old_text: string, new_text: string }>`
- `patch_stats: { additions: number, deletions: number, operations: number }`

## Prompt Updates

Prompt now explicitly requires:
- unchanged lines to stay unchanged
- smallest necessary edits
- additive requests to keep existing layers and add on top

## Known Limitations

- Diff generation is line-based; tiny intra-line edits still appear as line replacements.
- Model can still propose large rewrites; they are now visible/rejectable, but not yet auto-constrained.

## Suggested Next Hardening

1. Add rewrite-threshold policy:
   - if request is additive and deletion ratio is high, trigger a stricter regeneration pass.
2. Add "accept all pending hunks" and "reject all pending hunks" shortcuts on top of per-hunk controls.
3. Add backend integration tests for `/api/copilot/chat` patch payload shape.
