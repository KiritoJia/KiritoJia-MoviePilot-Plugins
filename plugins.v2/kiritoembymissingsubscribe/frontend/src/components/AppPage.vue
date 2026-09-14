<script setup lang="ts">
import { onMounted, ref } from 'vue'

import Config from './Config.vue'

interface PluginApi {
  get<T = unknown>(path: string, options?: Record<string, unknown>): Promise<T>
  post<T = unknown>(path: string, payload?: unknown, options?: Record<string, unknown>): Promise<T>
}

interface ConfigModel {
  plugin_id?: string
  [key: string]: unknown
}

const props = withDefaults(defineProps<{
  api: PluginApi
  pluginId?: string
  initialConfig?: ConfigModel
  config?: ConfigModel
  navKey?: string
}>(), {
  pluginId: 'KiritoEmbyMissingSubscribe',
  initialConfig: undefined,
  config: undefined,
  navKey: 'main',
})

const config = ref<ConfigModel | null>(props.initialConfig || props.config || null)
const loading = ref(!config.value)
const error = ref('')

const pluginPath = (path: string): string => `plugin/${encodeURIComponent(props.pluginId)}/${path.replace(/^\//, '')}`

async function loadConfig(): Promise<void> {
  if (config.value) return
  loading.value = true
  error.value = ''
  try {
    config.value = await props.api.get<ConfigModel>(pluginPath('config'))
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '无法读取插件配置'
  } finally {
    loading.value = false
  }
}

async function saveConfig(value: ConfigModel): Promise<void> {
  const saved = await props.api.post<ConfigModel>(pluginPath('config'), value)
  config.value = saved || value
}

onMounted(() => { void loadConfig() })
</script>

<template>
  <section class="emby-app-page">
    <VProgressLinear v-if="loading" indeterminate color="primary" />
    <VAlert v-if="error" type="error" variant="tonal" class="ma-4">{{ error }}</VAlert>
    <Config
      v-if="config"
      :initial-config="config"
      :api="props.api"
      @save="saveConfig"
    />
  </section>
</template>

<style scoped>
.emby-app-page { min-width: 0; min-height: 100%; background: rgb(var(--v-theme-surface)); }
</style>
