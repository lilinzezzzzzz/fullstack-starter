import type { paths } from '../types/api.generated';
import { getJSON } from './client';

type HelloResponse = paths['/api/v1/hello']['get']['responses'][200]['content']['application/json'];
type HealthResponse = paths['/api/health']['get']['responses'][200]['content']['application/json'];

export const getHello = (signal?: AbortSignal) => getJSON<HelloResponse>('/api/v1/hello', signal);
export const getHealth = (signal?: AbortSignal) => getJSON<HealthResponse>('/api/health', signal);
