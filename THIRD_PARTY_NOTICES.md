# Third-party notices

The root MIT license covers original Micros code. It does not replace upstream
licenses for bundled components or separately downloaded dependencies.

- nanopb: `src/third_party/nanopb/LICENSE.txt`.
- D3: `docs/assets/visual-storyboard/LICENSE-d3`.
- Apache ECharts: `docs/assets/visual-storyboard/echarts.LICENSE.txt` and
  `echarts.NOTICE.txt` in the same directory.
- zrender: `docs/assets/visual-storyboard/zrender.LICENSE.txt`.
- Console Sankey bundle: `src/server/web/sankey.LICENSE.txt`.

ESP-IDF, Python packages and other installed toolchains retain their upstream
licenses. Their sources and versions are selected by the checked-in bootstrap
and requirements files.

The macOS Python environment installs gnureadline (GPL-3.0-or-later), which bundles
GNU Readline and CPython's readline extension. It is a host tooling dependency,
not part of the MCU service ABI or firmware. See https://pypi.org/project/gnureadline/.
