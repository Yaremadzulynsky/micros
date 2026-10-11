import { mkdir, writeFile, copyFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import * as esbuild from 'esbuild';
import * as echarts from 'echarts';
import { systemOption, communicationOption, updateOption } from './charts.mjs';
const root = fileURLToPath(new URL('../../..', import.meta.url));
const assets = `${root}docs/assets/visual-storyboard`;
await mkdir(assets, { recursive: true });
await mkdir(`${root}docs/javascripts`, { recursive: true });
await esbuild.build({ entryPoints: [fileURLToPath(new URL('browser.mjs', import.meta.url))], bundle: true,
  minify: true, format: 'iife', target: 'es2020', legalComments: 'eof',
  outfile: `${root}docs/javascripts/storyboard.bundle.js` });
for (const [name, option, desktopHeight, mobileHeight] of [
  ['system', systemOption, 420, 482], ['communication', communicationOption, 430, 540], ['update', updateOption, 286, 276],
]) {
  for (const [suffix, width, height] of [['', 960, desktopHeight], ['-mobile', 300, mobileHeight]]) {
    const chart = echarts.init(null, null, { renderer: 'svg', ssr: true, width, height });
    chart.setOption(option(width));
    await writeFile(`${assets}/${name}${suffix}.svg`, chart.renderToSVGString());
    chart.dispose();
  }
}
await copyFile(new URL('node_modules/echarts/LICENSE', import.meta.url), `${assets}/echarts.LICENSE.txt`);
await copyFile(new URL('node_modules/echarts/NOTICE', import.meta.url), `${assets}/echarts.NOTICE.txt`);
await copyFile(new URL('node_modules/zrender/LICENSE', import.meta.url), `${assets}/zrender.LICENSE.txt`);
await copyFile(new URL('node_modules/echarts/licenses/LICENSE-d3', import.meta.url), `${assets}/LICENSE-d3`);
