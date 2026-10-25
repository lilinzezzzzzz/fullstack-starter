import type { components } from './types/api.generated';

declare const __CLIENT_CONFIG__: components['schemas']['ClientSettings'];
declare const __APPLICATION_INFO__: { title: string; version: string };

// These are injected only after the TOML file passes the backend's complete validation.
export const clientConfig = __CLIENT_CONFIG__;
export const applicationInfo = __APPLICATION_INFO__;
