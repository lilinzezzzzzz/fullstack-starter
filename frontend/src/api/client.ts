import { clientConfig } from '../config';

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId?: string;

  constructor(message: string, status: number, code: string, requestId?: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.requestId = requestId;
  }
}

export async function getJSON<T>(path: string, signal?: AbortSignal): Promise<T> {
  if (signal?.aborted) throw signal.reason;
  const controller = new AbortController();
  const cancel = () => controller.abort(signal?.reason);
  signal?.addEventListener('abort', cancel, { once: true });
  const timeout = setTimeout(() => controller.abort(), clientConfig.request_timeout_seconds * 1000);
  try {
    const response = await fetch(path, {
      headers: { Accept: 'application/json' },
      signal: controller.signal,
    });
    const body = await response.json().catch(() => null);
    if (!response.ok) {
      throw new ApiError(
        typeof body?.message === 'string' ? body.message : `请求失败（HTTP ${response.status}）`,
        response.status,
        typeof body?.code === 'string' ? body.code : 'HTTP_ERROR',
        typeof body?.request_id === 'string' ? body.request_id : undefined,
      );
    }
    if (body === null) throw new ApiError('接口未返回有效 JSON', response.status, 'INVALID_JSON');
    return body as T;
  } catch (error) {
    if (signal?.aborted) throw error;
    if (error instanceof ApiError) throw error;
    throw new ApiError(
      controller.signal.aborted ? '请求超时，请稍后重试' : '无法连接后端，请确认服务已启动',
      0,
      controller.signal.aborted ? 'TIMEOUT' : 'NETWORK_ERROR',
    );
  } finally {
    clearTimeout(timeout);
    signal?.removeEventListener('abort', cancel);
  }
}
