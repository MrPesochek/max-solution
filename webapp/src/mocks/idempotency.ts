import type { JsonBodyType } from 'msw';
import { tracked } from './mockState';

interface CachedResponse {
  status: number;
  body: JsonBodyType;
}

const cache = tracked(new Map<string, CachedResponse>());

export function getCached(tag: string, key: string | null): CachedResponse | undefined {
  if (!key) return undefined;
  return cache.get(`${tag}:${key}`);
}

export function setCached(tag: string, key: string | null, status: number, body: JsonBodyType): void {
  if (!key) return;
  cache.set(`${tag}:${key}`, { status, body });
}
