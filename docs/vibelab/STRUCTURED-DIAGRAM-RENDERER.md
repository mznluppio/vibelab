# Structured diagram renderer audit

The VibeLab renderer stays on the existing `vibelab-diagram` JSON contract, Dagre layout, and React Flow canvas.

## Root causes addressed

- Inline canvas height was estimated from node and group counts, rather than from the laid-out content bounds. A short graph could therefore have a disproportionately tall surface.
- React Flow's automatic `fitView` ran before custom node dimensions were guaranteed to be measured and capped small graphs at `1.1x`, making them appear undersized.
- Group dimensions were calculated correctly from children, but their visual stacking and content bounds were not explicit. This made grouped layouts harder to frame predictably.
- Edges already target real child nodes; the renderer now preserves that invariant explicitly, keeps group backgrounds below both child nodes and edges, and gives labelled edges an opaque pill background.

## Renderer rules

- Dagre lays out only business nodes. Group rectangles are derived afterwards from their children's absolute bounds with reserved heading space.
- Inline height is `content bounds + orientation-aware viewport margin`, clamped to `280–560px`. Expanded mode fills its dialog.
- The viewport fits only after `useNodesInitialized` reports measured nodes. Inline and expanded modes use different fit padding and zoom caps.
- Group backgrounds use z-index 0, labelled edges use 1, and content nodes use 2. Group children retain positions relative to their group.
