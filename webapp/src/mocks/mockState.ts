type Store = Map<unknown, unknown> | Set<unknown>;
type Saved = { kind: 'map'; entries: [unknown, unknown, unknown][] } | { kind: 'set'; values: unknown[] };

const stores: Store[] = [];
const snapshots = new Map<Store, Saved>();

export function tracked<T extends Store>(store: T): T {
  stores.push(store);
  return store;
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && Object.getPrototypeOf(value) === Object.prototype;
}

function clone<T>(value: T): T {
  if (Array.isArray(value)) return value.map(clone) as T;
  if (value instanceof Map) return new Map(Array.from(value, ([k, v]) => [k, clone(v)])) as T;
  if (value instanceof Set) return new Set(Array.from(value, clone)) as T;
  if (isPlainObject(value)) {
    return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, clone(v)])) as T;
  }
  return value;
}

export function snapshotMockState(): void {
  for (const store of stores) {
    snapshots.set(
      store,
      store instanceof Map
        ? { kind: 'map', entries: Array.from(store, ([key, value]) => [key, value, clone(value)]) }
        : { kind: 'set', values: Array.from(store) },
    );
  }
}

export function resetMockState(): void {
  for (const store of stores) {
    const saved = snapshots.get(store);
    if (!saved) continue;
    store.clear();
    if (saved.kind === 'set') {
      for (const value of saved.values) (store as Set<unknown>).add(value);
      continue;
    }
    for (const [key, original, copy] of saved.entries) {
      if (isPlainObject(original)) {
        for (const field of Object.keys(original)) delete original[field];
        Object.assign(original, clone(copy));
        (store as Map<unknown, unknown>).set(key, original);
      } else {
        (store as Map<unknown, unknown>).set(key, clone(copy));
      }
    }
  }
}
