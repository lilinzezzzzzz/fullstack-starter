import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import { RouterProvider } from 'react-router-dom';
import { ApiError } from './api/client';
import { router } from './router';
import { clientConfig } from './config';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: clientConfig.query_stale_seconds * 1000,
      gcTime: clientConfig.query_cache_seconds * 1000,
      refetchOnWindowFocus: clientConfig.refetch_on_window_focus,
      refetchOnMount: clientConfig.refetch_on_mount,
      refetchOnReconnect: clientConfig.refetch_on_reconnect,
      retryDelay: clientConfig.query_retry_delay_seconds * 1000,
      retry: (count, error) =>
        count < clientConfig.query_retry_attempts &&
        error instanceof ApiError &&
        ((error.status === 0 && clientConfig.retry_network_errors) ||
          error.status >= clientConfig.retry_min_status),
    },
    mutations: { retry: clientConfig.mutation_retry_attempts },
  },
});

export default function App() {
  return (
    <ConfigProvider
      locale={zhCN}
      theme={{
        token: {
          colorPrimary: clientConfig.theme_primary_color,
          borderRadius: clientConfig.theme_border_radius,
          fontSize: clientConfig.theme_font_size,
          fontFamily: clientConfig.theme_font_family,
        },
      }}
    >
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </ConfigProvider>
  );
}
