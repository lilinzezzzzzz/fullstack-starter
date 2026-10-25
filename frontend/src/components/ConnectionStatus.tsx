import { Alert, Badge, Button } from 'antd';
import styles from './ConnectionStatus.module.css';

type Props = {
  pending: boolean;
  checking: boolean;
  error: Error | null;
  message?: string;
  onRetry: () => void;
};

export default function ConnectionStatus({ pending, checking, error, message, onRetry }: Props) {
  return (
    <section className={styles.connection} aria-label="服务连接" aria-busy={checking}>
      <div className={styles.summary} role="status" aria-live="polite">
        <Badge status={checking ? 'processing' : error ? 'error' : 'success'} />
        <div>
          <strong>
            {checking || pending ? '正在检查连接…' : error ? '连接检查失败' : '前后端已连通'}
          </strong>
          <p>
            {error
              ? '欢迎页已准备好，后端连接需要再检查一下。'
              : (message ?? '正在向本地服务打个招呼。')}
          </p>
        </div>
      </div>
      {error && <Alert title={error.message} type="error" showIcon />}
      <div className={styles.actions}>
        <Button type="primary" size="large" loading={checking} onClick={onRetry}>
          {error ? '重试连接' : '重新检查'}
        </Button>
        <a href="/api/v1/hello" target="_blank" rel="noreferrer">
          查看 Hello API <span aria-hidden="true">↗</span>
        </a>
      </div>
    </section>
  );
}
