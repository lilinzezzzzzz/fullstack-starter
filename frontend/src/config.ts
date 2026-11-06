import type { components } from './types/api.generated';

declare const __CLIENT_CONFIG__: components['schemas']['ClientSettings'];
declare const __APPLICATION_INFO__: { title: string; version: string };

// 仅在 TOML 文件通过后端完整校验后注入这些配置。
export const clientConfig = __CLIENT_CONFIG__;
export const applicationInfo = __APPLICATION_INFO__;
