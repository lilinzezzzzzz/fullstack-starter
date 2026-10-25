import ConnectionStatus from '../components/ConnectionStatus';
import { useWelcome } from '../hooks/useWelcome';
import styles from './WelcomePage.module.css';
import { applicationInfo } from '../config';

export default function WelcomePage() {
  const connection = useWelcome();
  return (
    <div className={styles.pageShell}>
      <header className={styles.brand}>
        <span className={styles.brandMark} aria-hidden="true">
          ›_
        </span>
        <span>{applicationInfo.title}</span>
        <span className={styles.version}>v{applicationInfo.version}</span>
      </header>
      <main className={styles.main}>
        <section className={styles.welcome} aria-labelledby="welcome-heading">
          <p className={styles.eyebrow}>A SMALL START. YOUR NEXT IDEA.</p>
          <h1 id="welcome-heading" className={styles.heading}>
            Hello, world<span>.</span>
          </h1>
          <p className={styles.intro}>一个简洁的起点，开始构建你的下一个应用。</p>
          <ul className={styles.stack} aria-label="技术栈">
            <li>FastAPI</li>
            <li>React</li>
            <li>SQLite</li>
          </ul>
          <ConnectionStatus
            pending={connection.isPending}
            checking={connection.isFetching}
            error={connection.error}
            message={connection.data?.hello.message}
            onRetry={() => {
              void connection.refetch();
            }}
          />
        </section>
      </main>
      <footer className={styles.footer}>从 Hello 开始，把空间留给你的想法。</footer>
    </div>
  );
}
