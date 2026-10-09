import React from 'react';
import ReactDOM from 'react-dom/client';

import { App } from './App';
import '../styles/variables.css';
import '../styles/templateselector.css';
import './styles.css';

document.documentElement.dataset.theme = 'coilem-amber';
document.documentElement.dataset.skin = 'fable';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
