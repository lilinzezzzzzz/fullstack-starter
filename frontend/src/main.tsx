import '@douyinfe/semi-ui/react19-adapter';
import '@douyinfe/semi-ui/lib/es/_base/base.css';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import { applicationInfo, clientConfig } from './config';
import './styles/global.css';

document.title = applicationInfo.title;

const theme = document.documentElement.style;
theme.setProperty('--app-component-primary', clientConfig.theme_primary_color);
theme.setProperty('--app-component-radius', `${clientConfig.theme_border_radius}px`);
theme.setProperty('--app-component-font-size', `${clientConfig.theme_font_size}px`);
theme.setProperty('--app-component-font-family', clientConfig.theme_font_family);

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
