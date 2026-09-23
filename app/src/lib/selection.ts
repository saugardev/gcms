export type Selection = { ids: string[]; active: string; anchor: string };
export type SelectionOptions = { toggle?: boolean; range?: boolean };
export const emptySelection: Selection = { ids: [], active: "", anchor: "" };

export function selectAll(current: Selection, ids: string[]): Selection {
  const active = ids.includes(current.active) ? current.active : (ids[0] ?? "");
  return { ids, active, anchor: active };
}

export function selectRange(
  current: Selection,
  ids: string[],
  additive = false,
): Selection {
  const next = additive ? [...new Set([...current.ids, ...ids])] : ids;
  return {
    ids: next,
    active: ids.at(-1) ?? (additive ? current.active : ""),
    anchor: ids[0] ?? (additive ? current.anchor : ""),
  };
}

export function selectComponent(
  current: Selection,
  id: string,
  order: string[],
  options: SelectionOptions = {},
): Selection {
  const index = order.indexOf(id);
  if (index < 0) return current;
  const anchor = order.indexOf(current.anchor);
  if (options.range && anchor >= 0) {
    const ids = order.slice(
      Math.min(anchor, index),
      Math.max(anchor, index) + 1,
    );
    return {
      ...selectRange(current, ids, options.toggle),
      active: id,
      anchor: current.anchor,
    };
  }
  if (options.toggle) {
    const ids = current.ids.includes(id)
      ? current.ids.filter((value) => value !== id)
      : [...current.ids, id];
    const active = ids.includes(id)
      ? id
      : ids.includes(current.active)
        ? current.active
        : (ids.at(-1) ?? "");
    return { ids, active, anchor: id };
  }
  return { ids: [id], active: id, anchor: id };
}
