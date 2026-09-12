import { defineConfig, type Plugin } from 'vite'
import vue from '@vitejs/plugin-vue'
import federation from '@originjs/vite-plugin-federation'

function cleanFederationAssets(): Plugin {
  return {
    name: 'clean-federation-assets',
    enforce: 'post',
    generateBundle(_options, bundle) {
      for (const fileName of Object.keys(bundle)) {
        if (fileName.startsWith('assets/__federation_shared_vuetify/')) {
          delete bundle[fileName]
        }
      }
    },
  }
}

export default defineConfig({
  server: {
    fs: { allow: ['../..'] },
  },
  plugins: [
    vue(),
    federation({
      name: 'EmbyMissingSubscribe',
      filename: 'remoteEntry.js',
      exposes: {'./Config': './src/components/Config.vue'},
      shared: {
        vue: { requiredVersion: false, generate: false, singleton: true },
        vuetify: { requiredVersion: false, generate: false, singleton: true },
        'vuetify/styles': { requiredVersion: false, generate: false, singleton: true },
      },
      format: 'esm',
    }),
    cleanFederationAssets(),
  ],
  build: {
    target: 'esnext',
    minify: false,
    cssCodeSplit: true,
    outDir: 'dist',
    emptyOutDir: true,
    rollupOptions: { input: 'src/main.ts' },
  },
})
