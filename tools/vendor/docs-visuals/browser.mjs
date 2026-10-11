import * as echarts from 'echarts/core';
import { CustomChart } from 'echarts/charts';
import { GridComponent, GraphicComponent } from 'echarts/components';
import { SVGRenderer } from 'echarts/renderers';
import { systemOption, communicationOption, updateOption } from './charts.mjs';
echarts.use([CustomChart, GridComponent, GraphicComponent, SVGRenderer]);

function mount() {
  const page = document.querySelector('.visual-storyboard');
  if (!page || page.dataset.ready) return;
  page.dataset.ready = 'true';
  const charts = [];
  for (const figure of page.querySelectorAll('[data-chart]')) {
    const element = figure.querySelector('.story-chart');
    const canvas = document.createElement('div');
    canvas.className = 'story-chart-renderer';
    canvas.setAttribute('aria-hidden', 'true');
    element.append(canvas);
    const chart = echarts.init(canvas, null, { renderer: 'svg' });
    let selected = 'success';
    function draw() {
      const width = canvas.clientWidth;
      const options = figure.dataset.chart === 'system' ? systemOption(width, canvas.clientHeight)
        : figure.dataset.chart === 'update' ? updateOption(width, selected === 'failure')
        : communicationOption(width, canvas.clientHeight);
      chart.resize();
      chart.setOption(options, { notMerge: true });
    }
    draw();
    figure.dataset.enhanced = 'true';
    figure.querySelectorAll('[data-choice]').forEach(button => {
      button.addEventListener('click', () => {
        selected = button.dataset.choice;
        figure.querySelectorAll('[data-choice]').forEach(other => other.setAttribute('aria-pressed', String(other === button)));
        const description = figure.querySelector('.story-reading');
        description.textContent = selected === 'failure'
            ? 'After the candidate exhausts its two boot attempts, the device falls back to the prior good greenhouse application and its 28°C setting. Management reconnects across resets. This path requires a recorded good graph.'
            : 'All three greenhouse workers pause for staging, then the candidate runs as a trial. The new selection becomes recorded good after confirmation. Resident management remains available during a normal service update.';
        element.setAttribute('aria-label', selected === 'failure'
            ? 'Failed startup: application pauses, candidate trials fail, management reconnects across resets, and the prior good application returns.'
            : 'Successful deployment: management stays available; the application pauses, runs a candidate, then confirms the new graph.');
        const verification = page.querySelector('.story-finish');
        verification.hidden = selected === 'failure';
        draw();
      });
    });
    const observer = new ResizeObserver(draw);
    observer.observe(element);
    charts.push({ chart, observer });
  }
  window.addEventListener('pagehide', event => {
    if (event.persisted) return; // Preserve rendered charts in the back/forward cache.
    charts.forEach(({chart, observer}) => { observer.disconnect(); chart.dispose(); });
  });
}
if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount, { once: true });
else mount();
