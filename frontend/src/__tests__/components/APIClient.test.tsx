import { describe, it, expect, vi, beforeEach } from 'vitest';

describe('API Client Error Handling', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('throws meaningful error on 429 rate limit', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValueOnce({
      ok: false,
      status: 429,
      statusText: 'Too Many Requests',
      headers: new Headers({ 'Retry-After': '30' }),
      json: async () => ({}),
    } as Response);

    const { api } = await import('../../api/client');
    await expect(api.getHealth()).rejects.toThrow('Rate limited');
  });

  it('throws meaningful error on 403 unauthorized', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValueOnce({
      ok: false,
      status: 403,
      statusText: 'Forbidden',
      headers: new Headers(),
      json: async () => ({ detail: 'Invalid API key' }),
    } as Response);

    const { api } = await import('../../api/client');
    await expect(api.getHealth()).rejects.toThrow('Unauthorized');
  });

  it('throws meaningful error on 503 service unavailable', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValueOnce({
      ok: false,
      status: 503,
      statusText: 'Service Unavailable',
      headers: new Headers(),
      json: async () => ({}),
    } as Response);

    const { api } = await import('../../api/client');
    await expect(api.getHealth()).rejects.toThrow('Service temporarily unavailable');
  });

  it('extracts detail from error response body', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValueOnce({
      ok: false,
      status: 404,
      statusText: 'Not Found',
      headers: new Headers(),
      json: async () => ({ detail: 'Run abc123 not found' }),
    } as Response);

    const { api } = await import('../../api/client');
    await expect(api.getHealth()).rejects.toThrow('Run abc123 not found');
  });
});
