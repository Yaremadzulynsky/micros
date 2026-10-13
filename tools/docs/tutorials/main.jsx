import React from 'react';
import {createRoot} from 'react-dom/client';
import {ToggleTutorial} from './ToggleTutorial.jsx';
import {TutorialIndex} from './TutorialNavigation.jsx';
import './docs-tutorials.css';

const root = document.getElementById('micros-tutorial');
const lesson = root.dataset.lesson;
createRoot(root).render(<React.StrictMode>{lesson === 'index'
  ? <TutorialIndex/> : <ToggleTutorial id={lesson}/>}</React.StrictMode>);
