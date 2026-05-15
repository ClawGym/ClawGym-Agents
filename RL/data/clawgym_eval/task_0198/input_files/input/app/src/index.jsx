import React from 'react';
import ReactDOM from 'react-dom';
import OldClassComponent from './components/OldClassComponent';
import { NewHookComponent } from './components/NewHookComponent';

const items = ['alpha', 'beta', 'gamma'];

ReactDOM.render(
  <div>
    <OldClassComponent />
    <NewHookComponent items={items} />
  </div>,
  document.getElementById('root')
);
