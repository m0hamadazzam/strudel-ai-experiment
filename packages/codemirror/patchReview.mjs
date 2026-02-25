import { StateEffect, StateField } from '@codemirror/state';
import { Decoration, EditorView, WidgetType } from '@codemirror/view';

const PENDING = 'pending';
const ACCEPTED = 'accepted';
const REJECTED = 'rejected';

export const setPatchReviewHunksEffect = StateEffect.define();
export const clearPatchReviewHunksEffect = StateEffect.define();
export const setPatchHunkStatusEffect = StateEffect.define();

function normalizeHunk(hunk) {
  return {
    id: String(hunk.id),
    op: hunk.op || 'replace',
    start: Number(hunk.start) || 0,
    end: Number(hunk.end) || 0,
    oldText: hunk.oldText || '',
    newText: hunk.newText || '',
    status: hunk.status || PENDING,
  };
}

function mapHunk(hunk, changes) {
  return {
    ...hunk,
    start: changes.mapPos(hunk.start, 1),
    end: changes.mapPos(hunk.end, -1),
  };
}

function emitPatchHunkAction(hunkId, action, applied) {
  if (typeof window === 'undefined') {
    return;
  }
  window.dispatchEvent(
    new CustomEvent('strudel-ai-patch-hunk-action', {
      detail: {
        hunkId,
        action,
        applied,
        source: 'editor',
      },
    }),
  );
}

class PatchHunkWidget extends WidgetType {
  constructor(hunk) {
    super();
    this.hunk = hunk;
  }

  eq(other) {
    return (
      this.hunk.id === other.hunk.id &&
      this.hunk.status === other.hunk.status &&
      this.hunk.newText === other.hunk.newText
    );
  }

  toDOM(view) {
    const container = document.createElement('div');
    container.className = 'cm-aiPatchWidget';

    const header = document.createElement('div');
    header.className = 'cm-aiPatchWidgetHeader';
    header.textContent = `Copilot ${this.hunk.op}`;
    container.appendChild(header);

    if (this.hunk.newText) {
      const preview = document.createElement('pre');
      preview.className = 'cm-aiPatchAddPreview';
      preview.textContent = this.hunk.newText;
      container.appendChild(preview);
    } else {
      const deleted = document.createElement('div');
      deleted.className = 'cm-aiPatchDeletePreview';
      deleted.textContent = 'Deletes highlighted code';
      container.appendChild(deleted);
    }

    const controls = document.createElement('div');
    controls.className = 'cm-aiPatchControls';

    const acceptBtn = document.createElement('button');
    acceptBtn.className = 'cm-aiPatchButton cm-aiPatchButtonAccept';
    acceptBtn.textContent = 'Accept';
    acceptBtn.onclick = (e) => {
      e.preventDefault();
      e.stopPropagation();
      const applied = acceptPatchReviewHunk(view, this.hunk.id);
      emitPatchHunkAction(this.hunk.id, 'accept', applied);
    };
    controls.appendChild(acceptBtn);

    const rejectBtn = document.createElement('button');
    rejectBtn.className = 'cm-aiPatchButton cm-aiPatchButtonReject';
    rejectBtn.textContent = 'Reject';
    rejectBtn.onclick = (e) => {
      e.preventDefault();
      e.stopPropagation();
      const applied = rejectPatchReviewHunk(view, this.hunk.id);
      emitPatchHunkAction(this.hunk.id, 'reject', applied);
    };
    controls.appendChild(rejectBtn);

    container.appendChild(controls);
    return container;
  }

  ignoreEvent() {
    return false;
  }
}

class PatchReviewToolbarWidget extends WidgetType {
  eq() {
    return true;
  }

  toDOM(view) {
    const container = document.createElement('div');
    container.className = 'cm-aiPatchWidget cm-aiPatchToolbar';

    const controls = document.createElement('div');
    controls.className = 'cm-aiPatchControls';

    const acceptAllBtn = document.createElement('button');
    acceptAllBtn.className = 'cm-aiPatchButton cm-aiPatchButtonAccept';
    acceptAllBtn.textContent = 'Accept all';
    acceptAllBtn.onclick = (e) => {
      e.preventDefault();
      e.stopPropagation();
      const pending = getPatchReviewHunks(view)
        .filter((h) => h.status === PENDING)
        .sort((a, b) => a.start - b.start);
      for (const h of pending) {
        const applied = acceptPatchReviewHunk(view, h.id);
        emitPatchHunkAction(h.id, 'accept', applied);
      }
    };
    controls.appendChild(acceptAllBtn);

    const rejectAllBtn = document.createElement('button');
    rejectAllBtn.className = 'cm-aiPatchButton cm-aiPatchButtonReject';
    rejectAllBtn.textContent = 'Reject all';
    rejectAllBtn.onclick = (e) => {
      e.preventDefault();
      e.stopPropagation();
      const pending = getPatchReviewHunks(view).filter((h) => h.status === PENDING);
      for (const h of pending) {
        const applied = rejectPatchReviewHunk(view, h.id);
        emitPatchHunkAction(h.id, 'reject', applied);
      }
    };
    controls.appendChild(rejectAllBtn);

    container.appendChild(controls);
    return container;
  }

  ignoreEvent() {
    return false;
  }
}

function buildPatchReviewDecorations(hunks) {
  const marks = [];
  const ordered = hunks
    .filter((hunk) => hunk.status === PENDING)
    .slice()
    .sort((a, b) => (a.start === b.start ? a.end - b.end : a.start - b.start));

  if (ordered.length > 0) {
    marks.push(
      Decoration.widget({
        widget: new PatchReviewToolbarWidget(),
        side: -1,
        block: true,
      }).range(0),
    );
  }

  for (const hunk of ordered) {

    if (hunk.end > hunk.start) {
      marks.push(
        Decoration.mark({
          class: 'cm-aiPatchRemove',
        }).range(hunk.start, hunk.end),
      );
    }

    marks.push(
      Decoration.widget({
        widget: new PatchHunkWidget(hunk),
        side: 1,
        block: true,
      }).range(hunk.end),
    );
  }
  return Decoration.set(marks, true);
}

const patchReviewField = StateField.define({
  create() {
    return {
      hunks: [],
      decorations: Decoration.none,
    };
  },
  update(value, tr) {
    let hunks = value.hunks;
    if (tr.docChanged) {
      hunks = hunks.map((hunk) => mapHunk(hunk, tr.changes));
    }

    for (const effect of tr.effects) {
      if (effect.is(setPatchReviewHunksEffect)) {
        hunks = (effect.value || []).map(normalizeHunk);
      } else if (effect.is(clearPatchReviewHunksEffect)) {
        hunks = [];
      } else if (effect.is(setPatchHunkStatusEffect)) {
        const { id, status } = effect.value || {};
        if (!id) {
          continue;
        }
        hunks = hunks.map((hunk) => (hunk.id === id ? { ...hunk, status } : hunk));
      }
    }

    return {
      hunks,
      decorations: buildPatchReviewDecorations(hunks),
    };
  },
  provide: (field) => EditorView.decorations.from(field, (value) => value.decorations),
});

export const patchReviewExtension = [patchReviewField];

export function setPatchReviewHunks(view, hunks) {
  view.dispatch({
    effects: setPatchReviewHunksEffect.of(hunks || []),
  });
}

export function clearPatchReviewHunks(view) {
  view.dispatch({
    effects: clearPatchReviewHunksEffect.of(true),
  });
}

export function getPatchReviewHunks(view) {
  const field = view.state.field(patchReviewField, false);
  return field?.hunks || [];
}

/**
 * Returns the document with all PENDING hunks applied (preview code), or null if none.
 * Used so Play/Update can run the proposed changes before the user accepts.
 */
export function getPreviewCodeWithPendingHunks(view) {
  const field = view.state.field(patchReviewField, false);
  const pending = (field?.hunks || []).filter((h) => h.status === PENDING);
  if (pending.length === 0) {
    return null;
  }
  let s = view.state.doc.toString();
  const byStartDesc = pending.slice().sort((a, b) => b.start - a.start);
  for (const hunk of byStartDesc) {
    s = s.slice(0, hunk.start) + (hunk.newText || '') + s.slice(hunk.end);
  }
  return s;
}

export function acceptPatchReviewHunk(view, hunkId) {
  const field = view.state.field(patchReviewField, false);
  const hunk = field?.hunks?.find((item) => item.id === hunkId && item.status === PENDING);
  if (!hunk) {
    return false;
  }

  const oldText = view.state.doc.sliceString(hunk.start, hunk.end);
  if (oldText !== hunk.oldText) {
    return false;
  }

  view.dispatch({
    changes: {
      from: hunk.start,
      to: hunk.end,
      insert: hunk.newText || '',
    },
    effects: setPatchHunkStatusEffect.of({ id: hunkId, status: ACCEPTED }),
  });
  return true;
}

export function rejectPatchReviewHunk(view, hunkId) {
  const field = view.state.field(patchReviewField, false);
  const hunk = field?.hunks?.find((item) => item.id === hunkId && item.status === PENDING);
  if (!hunk) {
    return false;
  }

  view.dispatch({
    effects: setPatchHunkStatusEffect.of({ id: hunkId, status: REJECTED }),
  });
  return true;
}
