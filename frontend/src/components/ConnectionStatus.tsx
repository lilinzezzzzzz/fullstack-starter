import { IconRefresh } from '@douyinfe/semi-icons';
import Banner from '@douyinfe/semi-ui/lib/es/banner';
import Button from '@douyinfe/semi-ui/lib/es/button';
import Tag, { type TagColor } from '@douyinfe/semi-ui/lib/es/tag';
import styles from './ConnectionStatus.module.css';

type Props = {
  pending: boolean;
  checking: boolean;
  error: Error | null;
  message?: string;
  onRetry: () => void;
};

export default function ConnectionStatus({ pending, checking, error, message, onRetry }: Props) {
  const status: { color: TagColor; text: string } =
    pending || checking
      ? { color: 'blue', text: '正在检查连接…' }
      : error
        ? { color: 'red', text: '连接检查失败' }
        : { color: 'green', text: '前后端已连通' };

  return (
    <section className={styles.connection} aria-label="服务连接">
      <div className={styles.summary} role="status" aria-live="polite">
        <Tag size="large" color={status.color}>
          {status.text}
        </Tag>
        <p>
          {error
            ? '欢迎页已准备好，后端连接需要再检查一下。'
            : (message ?? '正在向本地服务打个招呼。')}
        </p>
      </div>
      {error && (
        <Banner
          type="danger"
          fullMode={false}
          closeIcon={null}
          description={<span className={styles.errorMessage}>{error.message}</span>}
        />
      )}
      <div className={styles.actions}>
        <Button
          className={styles.retry}
          theme="solid"
          type="primary"
          size="large"
          icon={<IconRefresh aria-hidden="true" />}
          loading={checking}
          aria-busy={checking}
          onClick={checking ? undefined : onRetry}
        >
          {error ? '重试连接' : '重新检查'}
        </Button>
        <a href="/api/v1/hello" target="_blank" rel="noreferrer">
          查看 Hello API <span aria-hidden="true">↗</span>
        </a>
      </div>
    </section>
  );
}
