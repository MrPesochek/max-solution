import { http, HttpResponse } from 'msw';
import { server } from '../mocks/server';
import type { Attachment } from '../api/types';

export function stubAttachmentUploads(): { slotOrder: string[] } {
  const stub = { slotOrder: [] as string[] };
  const store: Attachment[] = [];
  let counter = 0;

  server.use(
    http.post('*/requests/:id/attachments', async ({ params }) => {
      counter += 1;
      const slot = stub.slotOrder[counter - 1] ?? null;
      const attachment: Attachment = {
        id: `att_test_${counter}`,
        owner_kind: 'request',
        request_id: String(params.id),
        message_id: null,
        slot,
        visibility_class: slot === 'nameplate' ? 'request_sensitive' : 'request_private',
        processing_state: 'ready',
        publication_state: null,
        rejected_reason: null,
        mime_type: 'image/jpeg',
        byte_size: 128,
        pixel_width: null,
        pixel_height: null,
        created_at: new Date().toISOString(),
      };
      store.push(attachment);
      return HttpResponse.json(attachment, { status: 201 });
    }),
    http.get('*/requests/:id/attachments', ({ params }) =>
      HttpResponse.json(store.filter((a) => a.request_id === String(params.id))),
    ),
    http.delete('*/attachments/:id', ({ params }) => {
      const index = store.findIndex((a) => a.id === params.id);
      if (index >= 0) store.splice(index, 1);
      return new HttpResponse(null, { status: 204 });
    }),
  );

  return stub;
}

interface DemoAuthResult {
  token: string;
  memberships: { organization: { id: string; name: string }; role: string }[];
}

export async function demoLoginRaw(userKey: string): Promise<{ token: string; organizationId: string }> {
  const response = await fetch('/app-api/v1/auth/demo', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ user_key: userKey }),
  });
  const data = (await response.json()) as DemoAuthResult;
  const membership = data.memberships[0];
  if (!membership) throw new Error(`У демо-пользователя ${userKey} нет организаций`);
  return { token: data.token, organizationId: membership.organization.id };
}

const VERSIONED_PATH = /^\/requests\/([^/]+)(\/actions\/(?!preview-public-card|create-followup)[^/]+)?$/;

async function withExpectedVersion(
  path: string,
  auth: { token: string; organizationId: string },
  method: string,
  body: unknown,
): Promise<unknown> {
  const match = VERSIONED_PATH.exec(path);
  const versioned = match && (match[2] ? method === 'POST' : method === 'PATCH');
  if (!versioned || !body || typeof body !== 'object' || 'expected_version' in body) return body;
  const current = await apiCall<{ version: number }>(`/requests/${match[1]}`, auth);
  return { ...body, expected_version: current.version };
}

export async function apiCall<T>(
  path: string,
  auth: { token: string; organizationId: string },
  options: { method?: string; body?: unknown } = {},
): Promise<T> {
  const method = options.method ?? (options.body ? 'POST' : 'GET');
  const body = await withExpectedVersion(path, auth, method, options.body);
  const response = await fetch(`/app-api/v1${path}`, {
    method,
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${auth.token}`,
      'X-Organization-Id': auth.organizationId,
      'Idempotency-Key': crypto.randomUUID(),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`${method} ${path} -> ${response.status}: ${text}`);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}
