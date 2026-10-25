export const projectRoot: string;
export const configFile: string;
export function readProjectSettings(path: string): {
  frontend_dir: string;
  frontend_clean_output: boolean;
  allowed_hosts: string[];
  application: { title: string; version: string };
  client: Record<string, unknown>;
  vite: {
    host: string;
    port: number;
    proxy_target: string;
    strict_port: boolean;
    change_origin: boolean;
  };
  testing: {
    temporary_directory: string;
    host: string;
    termination_grace_seconds: number;
    command_timeout_seconds: number;
    keep_artifacts: boolean;
    browser: 'chromium' | 'firefox' | 'webkit';
    viewport_width: number;
    viewport_height: number;
    mobile_width: number;
    mobile_height: number;
    workers: number;
    retries: number;
    test_timeout_seconds: number;
    expect_timeout_seconds: number;
    action_timeout_seconds: number;
    navigation_timeout_seconds: number;
    trace: 'off' | 'on' | 'retain-on-failure' | 'on-first-retry';
    screenshot: 'off' | 'on' | 'only-on-failure';
    fully_parallel: boolean;
    reporter: 'list' | 'dot' | 'line';
  };
};
export function browserDefinitions(
  settings: ReturnType<typeof readProjectSettings>,
): Record<string, string>;
