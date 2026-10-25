import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import { applicationInfo } from './config';
import 'antd/dist/reset.css';
import './styles/global.css';

document.title = applicationInfo.title;

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
