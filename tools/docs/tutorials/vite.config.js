import {defineConfig} from 'vite';
import react from '@vitejs/plugin-react';
import {fileURLToPath} from 'node:url';
export default defineConfig({
  plugins:[react()],
  define:{'process.env.NODE_ENV':JSON.stringify('production')},
  build:{outDir:fileURLToPath(new URL('../../../build/docs-tutorials',import.meta.url)),emptyOutDir:true,
    lib:{entry:fileURLToPath(new URL('main.jsx',import.meta.url)),formats:['es'],fileName:()=> 'tutorial.js',cssFileName:'tutorial'}}
});
