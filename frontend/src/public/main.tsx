import React from 'react';
import ReactDOM from 'react-dom/client';

import { App } from './App';
import '../styles/variables.css';
import '../styles/templateselector.css';
import './styles.css';

document.documentElement.dataset.theme = 'coilem-amber';
document.documentElement.dataset.skin = 'fable';

// A shareable New Design shortcut avoids constructing the landing WebGL scene.
// Consume the action so later reloads follow normal startup.
const entryUrl = new URL(window.location.href);
const initialNewDesign = entryUrl.pathname === '/' && entryUrl.searchParams.get('new') === '1';
if (initialNewDesign) {
  entryUrl.searchParams.delete('new');
  window.history.replaceState(window.history.state, '', entryUrl.pathname + entryUrl.search + entryUrl.hash);
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App initialNewDesign={initialNewDesign} />
  </React.StrictMode>,
);
