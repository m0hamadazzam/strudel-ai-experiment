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
4. Frontend shows a diff preview (green additions / red deletions).
5. User can:
   - `Apply patch`: apply minimal operations to the editor
   - `Discard`: reject proposed edits
6. Patch apply is guarded by base-code match to prevent applying stale diffs.

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
2. Add per-hunk approve/reject (instead of apply-all/discard-all).
3. Add backend integration tests for `/api/copilot/chat` patch payload shape.
