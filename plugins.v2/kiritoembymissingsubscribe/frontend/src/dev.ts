import { createApp } from 'vue'
import { createVuetify } from 'vuetify'
import * as components from 'vuetify/components'
import * as directives from 'vuetify/directives'
import 'vuetify/styles'
import '@mdi/font/css/materialdesignicons.css'

import Config from './components/Config.vue'

const app = createApp(Config, {
  initialConfig: {
    plugin_id: 'KiritoEmbyMissingSubscribe',
    enabled: true,
    emby_url: 'http://192.168.31.20:8096',
    user_id: '1472c63c9cfd1353dc8014d913fdcafa',
    api_key: 'configured-api-key',
    cron: '0 */6 * * *',
    aired_only: true,
    timeout: 20,
  },
  api: {
    get: async () => ({
      success: true,
      finished_at: '2026-09-12 23:46:08',
      series: 428,
      missing: 17,
      subscriptions: 3,
      existing_subscriptions: 6,
      subscribe_failures: 0,
      skipped: 2,
      subscription_history: [
        {
          key: '297438:S1',
          name: '朱音落语',
          year: '2026',
          season: 1,
          missing: [7, 9, 12],
          poster: 'https://image.tmdb.org/t/p/w185/placeholder.jpg',
          status: '已创建',
          updated_at: '2026-09-12 23:46:08',
        },
      ],
    }),
  },
})

app.use(createVuetify({ components, directives }))
app.mount('#app')
