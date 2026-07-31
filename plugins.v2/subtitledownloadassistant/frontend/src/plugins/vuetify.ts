import { createVuetify } from 'vuetify'
import * as components from 'vuetify/components'
import * as directives from 'vuetify/directives'
import '@mdi/font/css/materialdesignicons.css'
import 'vuetify/styles'

const themes = {
  light: {
    dark: false,
    colors: {
      background: '#f4f5fa',
      surface: '#ffffff',
      'surface-variant': '#f2f0f7',
      primary: '#7367f0',
      secondary: '#6d6b77',
      success: '#28c76f',
      info: '#00a8c6',
      warning: '#e68a2e',
      error: '#ea5455',
    },
  },
  dark: {
    dark: true,
    colors: {
      background: '#242229',
      surface: '#2e2b34',
      'surface-variant': '#3a3642',
      primary: '#9d95f8',
      secondary: '#b8b4c0',
      success: '#54d98c',
      info: '#51c8dc',
      warning: '#f0ad68',
      error: '#ff7f80',
    },
  },
  purple: {
    dark: true,
    colors: {
      background: '#25222c',
      surface: '#302c38',
      'surface-variant': '#3c3746',
      primary: '#a79ff9',
      secondary: '#bbb6c5',
      success: '#61d695',
      info: '#62c9dc',
      warning: '#efb06f',
      error: '#ff8586',
    },
  },
  transparent: {
    dark: true,
    colors: {
      background: '#1f1d24',
      surface: '#29262f',
      'surface-variant': '#37333e',
      primary: '#a79ff9',
      secondary: '#bcb7c5',
      success: '#61d695',
      info: '#62c9dc',
      warning: '#efb06f',
      error: '#ff8586',
    },
  },
}

export const vuetify = createVuetify({
  components,
  directives,
  theme: {
    defaultTheme: 'light',
    themes,
  },
  defaults: {
    VBtn: { color: 'primary', elevation: 0 },
    VTextField: { variant: 'outlined', density: 'comfortable', hideDetails: 'auto' },
    VSelect: { variant: 'outlined', density: 'comfortable', hideDetails: 'auto' },
    VTextarea: { variant: 'outlined', density: 'comfortable', hideDetails: 'auto' },
    VTable: { density: 'comfortable' },
  },
})
