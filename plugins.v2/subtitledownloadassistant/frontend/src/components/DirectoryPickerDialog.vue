<script setup lang="ts">
import { ref, watch } from 'vue'

import { getErrorMessage } from '@/api/client'
import type { PluginApi } from '@/types'

interface StorageItem {
  name: string
  path: string
  type: string
}

interface DirectoryEntry {
  name: string
  path: string
}

const props = withDefaults(defineProps<{
  modelValue: boolean
  api: PluginApi
  initialPath?: string
}>(), {
  initialPath: '/',
})

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  select: [path: string]
}>()

const currentPath = ref('/')
const parentPath = ref<string | null>(null)
const pathInput = ref('/')
const entries = ref<DirectoryEntry[]>([])
const loading = ref(false)
const error = ref('')
let requestId = 0

watch(
  () => props.modelValue,
  open => {
    if (!open) {
      requestId += 1
      return
    }
    void loadDirectory(props.initialPath || '/')
  },
)

async function loadDirectory(path: string): Promise<void> {
  const currentRequest = ++requestId
  loading.value = true
  error.value = ''
  try {
    const requestedPath = normalizePath(path.trim() || '/')
    const response = await props.api.post<StorageItem[]>('storage/list', {
      path: requestedPath,
      type: 'share',
      flag: 'ROOT',
    })
    if (currentRequest !== requestId) return
    if (!Array.isArray(response)) throw new Error('MoviePilot 返回了无效目录数据')
    currentPath.value = requestedPath
    parentPath.value = parentOf(requestedPath)
    pathInput.value = requestedPath
    entries.value = response
      .filter(item => item?.type === 'dir' && typeof item.path === 'string')
      .map(item => ({ name: item.name || item.path, path: item.path }))
      .sort((left, right) => left.name.localeCompare(right.name, undefined, { numeric: true, sensitivity: 'base' }))
  } catch (requestError) {
    if (currentRequest === requestId) error.value = getErrorMessage(requestError, '目录读取失败')
  } finally {
    if (currentRequest === requestId) loading.value = false
  }
}

function normalizePath(path: string): string {
  const normalized = path.replaceAll('\\', '/')
  if (normalized === '/' || /^[A-Za-z]:\/$/.test(normalized)) return normalized
  return normalized.replace(/\/+$/, '') || '/'
}

function parentOf(path: string): string | null {
  const normalized = normalizePath(path)
  if (normalized === '/' || /^[A-Za-z]:\/$/.test(normalized)) return null
  const slash = normalized.lastIndexOf('/')
  if (slash < 0) return null
  if (slash === 0) return '/'
  const parent = normalized.slice(0, slash)
  return /^[A-Za-z]:$/.test(parent) ? `${parent}/` : parent
}

function close(): void {
  if (!loading.value) emit('update:modelValue', false)
}

function selectCurrent(): void {
  emit('select', currentPath.value)
  emit('update:modelValue', false)
}
</script>

<template>
  <VDialog
    :model-value="modelValue"
    max-width="44rem"
    :persistent="loading"
    @update:model-value="value => emit('update:modelValue', value)"
  >
    <VCard class="directory-dialog">
      <VCardTitle class="dialog-title">
        <div class="dialog-heading"><span class="dialog-icon"><VIcon icon="mdi-folder-search-outline" size="21" /></span><span>选择媒体目录</span></div>
        <VTooltip text="关闭"><template #activator="{ props: tooltipProps }"><VBtn v-bind="tooltipProps" icon="mdi-close" variant="text" aria-label="关闭目录选择" :disabled="loading" @click="close" /></template></VTooltip>
      </VCardTitle>

      <div class="path-toolbar">
        <VTooltip text="上一级">
          <template #activator="{ props: tooltipProps }">
            <VBtn v-bind="tooltipProps" icon="mdi-arrow-up" variant="tonal" aria-label="打开上一级目录" :disabled="!parentPath || loading" @click="parentPath && loadDirectory(parentPath)" />
          </template>
        </VTooltip>
        <VTextField
          v-model="pathInput"
          label="容器路径"
          hide-details
          density="compact"
          prepend-inner-icon="mdi-folder-outline"
          @keydown.enter.prevent="loadDirectory(pathInput)"
        />
        <VBtn variant="tonal" :loading="loading" @click="loadDirectory(pathInput)">前往</VBtn>
      </div>

      <VAlert v-if="error" type="error" variant="tonal" density="compact" class="mx-4 mb-3">
        <div class="inline-alert"><span>{{ error }}</span><VBtn size="small" variant="text" prepend-icon="mdi-refresh" @click="loadDirectory(pathInput)">重试</VBtn></div>
      </VAlert>

      <div class="directory-list" aria-live="polite">
        <VSkeletonLoader v-if="loading" type="list-item-avatar@6" />
        <button v-for="entry in entries" v-else :key="entry.path" type="button" @click="loadDirectory(entry.path)">
          <span class="folder-icon"><VIcon icon="mdi-folder" size="21" /></span>
          <span><strong>{{ entry.name }}</strong><small>{{ entry.path }}</small></span>
          <VIcon icon="mdi-chevron-right" size="19" />
        </button>
        <div v-if="!loading && !entries.length && !error" class="directory-empty"><VIcon icon="mdi-folder-open-outline" size="28" /><span>当前目录没有子目录</span></div>
      </div>

      <VCardActions class="dialog-actions">
        <span class="selected-path" :title="currentPath">{{ currentPath }}</span>
        <VSpacer />
        <VBtn variant="text" color="default" :disabled="loading" @click="close">取消</VBtn>
        <VBtn variant="flat" prepend-icon="mdi-check" :disabled="loading || Boolean(error)" @click="selectCurrent">选择当前目录</VBtn>
      </VCardActions>
    </VCard>
  </VDialog>
</template>

<style scoped>
.directory-dialog { overflow: hidden; border-radius: 0.5rem; }
.dialog-title { display: flex; min-height: 4rem; align-items: center; justify-content: space-between; gap: 1rem; padding: 0.75rem 1rem; border-bottom: 1px solid rgba(var(--v-border-color), var(--v-border-opacity)); font-size: 1rem; letter-spacing: 0; }
.dialog-heading { display: flex; min-width: 0; align-items: center; gap: 0.625rem; }
.dialog-icon, .folder-icon { display: grid; flex: 0 0 auto; place-items: center; border-radius: 0.375rem; color: rgb(var(--v-theme-primary)); background: rgba(var(--v-theme-primary), 0.12); }
.dialog-icon { width: 2.25rem; height: 2.25rem; }
.path-toolbar { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; align-items: center; gap: 0.625rem; padding: 1rem; }
.inline-alert { display: flex; align-items: center; justify-content: space-between; gap: 1rem; }
.directory-list { min-height: 18rem; max-height: min(48vh, 28rem); overflow-y: auto; border-block: 1px solid rgba(var(--v-border-color), var(--v-border-opacity)); }
.directory-list button { display: grid; width: 100%; min-height: 3.75rem; grid-template-columns: auto minmax(0, 1fr) auto; align-items: center; gap: 0.75rem; padding: 0.625rem 1rem; border: 0; border-bottom: 1px solid rgba(var(--v-border-color), var(--v-border-opacity)); color: inherit; text-align: start; background: rgb(var(--v-theme-surface)); cursor: pointer; font: inherit; }
.directory-list button:last-of-type { border-bottom: 0; }
.directory-list button:hover { background: rgba(var(--v-theme-primary), 0.05); }
.directory-list button:focus-visible { outline: 2px solid rgb(var(--v-theme-primary)); outline-offset: -2px; }
.folder-icon { width: 2.25rem; height: 2.25rem; }
.directory-list strong, .directory-list small { display: block; overflow: hidden; letter-spacing: 0; text-overflow: ellipsis; white-space: nowrap; }
.directory-list strong { font-size: 0.8125rem; font-weight: 600; }
.directory-list small { margin-top: 0.125rem; color: rgba(var(--v-theme-on-surface), var(--v-medium-emphasis-opacity)); font-size: 0.6875rem; }
.directory-list button > :last-child { color: rgba(var(--v-theme-on-surface), 0.34); }
.directory-empty { display: grid; min-height: 18rem; place-items: center; align-content: center; gap: 0.5rem; color: rgba(var(--v-theme-on-surface), var(--v-medium-emphasis-opacity)); font-size: 0.8125rem; }
.dialog-actions { min-height: 4.25rem; padding: 0.75rem 1rem; }
.selected-path { max-width: 20rem; overflow: hidden; color: rgba(var(--v-theme-on-surface), var(--v-medium-emphasis-opacity)); font-size: 0.75rem; text-overflow: ellipsis; white-space: nowrap; }
@media (max-width: 37.5rem) { .path-toolbar { grid-template-columns: auto minmax(0, 1fr); } .path-toolbar > :last-child { grid-column: 1 / -1; } .selected-path { display: none; } .dialog-actions { padding-inline: 0.75rem; } }
</style>
