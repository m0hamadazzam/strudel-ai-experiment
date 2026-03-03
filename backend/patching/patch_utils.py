from __future__ import annotations

from difflib import SequenceMatcher

from backend.core.schemas import PatchOperation, PatchStats


def _line_count(text: str) -> int:
    if not text:
        return 0
    return text.count("\n") + (0 if text.endswith("\n") else 1)


def build_patch_operations(base_code: str, target_code: str) -> list[PatchOperation]:
    """
    Build minimal line-based patch operations from base_code -> target_code.

    Offsets are character indices into base_code.
    """
    if base_code == target_code:
        return []

    base_lines = base_code.splitlines(keepends=True)
    target_lines = target_code.splitlines(keepends=True)

    base_offsets: list[int] = [0]
    for line in base_lines:
        base_offsets.append(base_offsets[-1] + len(line))

    matcher = SequenceMatcher(None, base_lines, target_lines, autojunk=False)
    ops: list[PatchOperation] = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue

        if tag not in ("insert", "delete", "replace"):
            # SequenceMatcher currently emits only equal/insert/delete/replace.
            continue

        ops.append(
            PatchOperation(
                op=tag,
                start=base_offsets[i1],
                end=base_offsets[i2],
                old_text="".join(base_lines[i1:i2]),
                new_text="".join(target_lines[j1:j2]),
            )
        )

    return ops


def apply_patch_operations(base_code: str, patch_ops: list[PatchOperation]) -> str:
    """
    Apply patch operations against base_code and return updated text.

    Raises ValueError if operations are invalid for the provided base_code.
    """
    if not patch_ops:
        return base_code

    result: list[str] = []
    cursor = 0

    for op in sorted(patch_ops, key=lambda x: x.start):
        if op.start < cursor or op.end < op.start:
            raise ValueError("Patch operations overlap or are out of order")
        if op.end > len(base_code):
            raise ValueError("Patch operation exceeds base code bounds")
        if base_code[op.start:op.end] != op.old_text:
            raise ValueError("Patch operation old_text does not match base code")

        result.append(base_code[cursor:op.start])
        result.append(op.new_text)
        cursor = op.end

    result.append(base_code[cursor:])
    return "".join(result)


def summarize_patch_operations(patch_ops: list[PatchOperation]) -> PatchStats:
    additions = sum(_line_count(op.new_text) for op in patch_ops)
    deletions = sum(_line_count(op.old_text) for op in patch_ops)
    return PatchStats(
        additions=additions,
        deletions=deletions,
        operations=len(patch_ops),
    )
