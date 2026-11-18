declare const __APPLICATION_INFO__: { title: string; version: string };

// 浏览器请求与查询策略，时间单位为秒。
export const clientConfig = {
  request_timeout_seconds: 10,
  query_stale_seconds: 30,
  query_cache_seconds: 300,
  query_retry_attempts: 1,
  query_retry_delay_seconds: 1,
  retry_min_status: 500,
  retry_network_errors: true,
  refetch_on_window_focus: false,
  refetch_on_mount: true,
  refetch_on_reconnect: true,
  // 写操作需要先建立幂等契约，当前固定禁用重试。
  mutation_retry_attempts: 0,
} as const;

// Vite 从已校验的 TOML 注入应用标识。
export const applicationInfo = __APPLICATION_INFO__;
