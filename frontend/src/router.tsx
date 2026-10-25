import { createBrowserRouter, Navigate } from 'react-router-dom';

async function loadWelcomePage() {
  return { Component: (await import('./pages/WelcomePage')).default };
}

export const router = createBrowserRouter([
  {
    path: '/',
    hydrateFallbackElement: (
      <main className="page-loading">
        <p role="status">正在加载欢迎页…</p>
      </main>
    ),
    children: [
      { index: true, lazy: loadWelcomePage },
      { path: 'welcome', lazy: loadWelcomePage },
      { path: '*', element: <Navigate to="/" replace /> },
    ],
  },
]);
