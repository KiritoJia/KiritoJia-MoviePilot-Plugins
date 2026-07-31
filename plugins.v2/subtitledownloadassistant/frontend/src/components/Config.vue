<script setup lang="ts">
import { computed, inject, onMounted, reactive, ref, watch } from 'vue'

import { clearCredentials, getErrorMessage, scanCustomDirectories, updateCredentials } from '@/api/client'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import DirectoryPickerDialog from '@/components/DirectoryPickerDialog.vue'
import type {
  ConfigModel,
  HostToast,
  NonSensitiveConfig,
  PackageAttributionStrategy,
  PathMapping,
  PluginApi,
  SubtitleSource,
} from '@/types'
import { sourceLabels } from '@/types/presentation'

const props = withDefaults(defineProps<{
  initialConfig?: Partial<ConfigModel>
  api: PluginApi
}>(), {
  initialConfig: () => ({}),
})

const emit = defineEmits<{
  save: [config: NonSensitiveConfig]
  close: []
  layout: [layout: { maxWidth: string }]
}>()
const toast = inject<HostToast | null>('moviepilot:toast', null)

type ExternalSource = 'opensubtitles' | 'assrt'
type SourceMeta = { source: SubtitleSource; icon: string }

const sourceMeta: SourceMeta[] = [
  { source: 'moviepilot', icon: 'mdi-server-network' },
  { source: 'opensubtitles', icon: 'mdi-closed-caption-outline' },
  { source: 'assrt', icon: 'mdi-subtitles-outline' },
  { source: 'shooter', icon: 'mdi-target' },
  { source: 'thunder', icon: 'mdi-flash-outline' },
]
const defaultSources: SubtitleSource[] = ['shooter', 'thunder', 'moviepilot', 'assrt', 'opensubtitles']
const defaultFormats = ['ASS', 'SSA', 'SRT', 'SUP']
const attributionOptions: Array<{ title: string; value: PackageAttributionStrategy }> = [
  { title: '信任候选包', value: 'trust_package' },
  { title: 'MoviePilot 文件识别', value: 'host_recognition' },
]

const form = reactive<{
  enabled: boolean
  moviepilot_enabled: boolean
  opensubtitles_enabled: boolean
  assrt_enabled: boolean
  shooter_enabled: boolean
  thunder_enabled: boolean
  allow_machine_translation: boolean
  ai_attribution_takeover_enabled: boolean
  directory_monitor_enabled: boolean
  directory_monitor_interval: number
  max_concurrent_tasks: number
  max_candidate_attempts: number
  package_attribution_strategy: PackageAttributionStrategy
}>({
  enabled: false,
  moviepilot_enabled: true,
  opensubtitles_enabled: false,
  assrt_enabled: false,
  shooter_enabled: false,
  thunder_enabled: false,
  allow_machine_translation: false,
  ai_attribution_takeover_enabled: false,
  directory_monitor_enabled: true,
  directory_monitor_interval: 60,
  max_concurrent_tasks: 2,
  max_candidate_attempts: 3,
  package_attribution_strategy: 'trust_package',
})
const pathMappings = ref<PathMapping[]>([])
const customMediaDirectories = ref<string[]>([])
const savedCustomMediaDirectories = ref<string[]>([])
const sourcePriority = ref<SubtitleSource[]>([...defaultSources])
const formatPriority = ref<string[]>([...defaultFormats])
const allowedFormats = ref<string[]>([...defaultFormats])
const opensubtitlesConfigured = ref(false)
const assrtConfigured = ref(false)
const credentials = reactive({
  opensubtitles: { api_key: '', username: '', password: '' },
  assrt: { token: '' },
})
const openSource = ref<SubtitleSource | null>(null)
const advancedOpen = ref<string | null>(null)
const directoryPickerOpen = ref(false)
const directoryPickerIndex = ref<number | null>(null)
const saving = ref(false)
const saveError = ref('')
const showApiKey = ref(false)
const showPassword = ref(false)
const showAssrtToken = ref(false)
const clearOpen = ref(false)
const clearSource = ref<ExternalSource | null>(null)
const clearing = ref(false)
const scanningDirectories = ref(false)
const directoryScanMessage = ref('')
const directoryScanType = ref<'success' | 'warning'>('success')

const pluginId = computed(() => typeof props.initialConfig?.plugin_id === 'string' ? props.initialConfig.plugin_id.trim() : '')
const hostAiEnabled = computed(() => Boolean(
  props.initialConfig?.ai_agent_enabled
  ?? props.initialConfig?.ai_agent_available
  ?? props.initialConfig?.host_ai_enabled
  ?? props.initialConfig?.moviepilot_ai_enabled,
))
const osDraftValues = computed(() => Object.values(credentials.opensubtitles).map(value => value.trim()))
const hasOsUpdate = computed(() => osDraftValues.value.some(Boolean))
const hasAssrtUpdate = computed(() => Boolean(credentials.assrt.token.trim()))
const osComplete = computed(() => opensubtitlesConfigured.value || osDraftValues.value.every(Boolean))
const assrtComplete = computed(() => assrtConfigured.value || hasAssrtUpdate.value)
const osError = computed(() => form.opensubtitles_enabled && !osComplete.value ? '启用前需提供 API Key、用户名和密码。' : '')
const assrtError = computed(() => form.assrt_enabled && !assrtComplete.value ? '启用前需提供 ASSRT Token。' : '')
const attemptsError = computed(() => {
  const value = Number(form.max_candidate_attempts)
  return Number.isInteger(value) && value >= 1 && value <= 10 ? '' : '最大尝试数必须是 1 到 10 的整数。'
})
const concurrentTasksError = computed(() => {
  const value = Number(form.max_concurrent_tasks)
  return Number.isInteger(value) && value >= 1 && value <= 4 ? '' : '同时任务数必须是 1 到 4 的整数。'
})
const monitorIntervalError = computed(() => {
  const value = Number(form.directory_monitor_interval)
  return Number.isInteger(value) && value >= 30 && value <= 3600 ? '' : '巡检间隔必须是 30 到 3600 秒的整数。'
})
const pathMappingsError = computed(() => {
  for (let index = 0; index < pathMappings.value.length; index += 1) {
    const sourceError = pathMappingFieldError(index, 'source_prefix')
    if (sourceError) return sourceError
    const targetError = pathMappingFieldError(index, 'target_prefix')
    if (targetError) return targetError
  }
  return ''
})
const customDirectoriesError = computed(() => {
  const seen = new Set<string>()
  for (let index = 0; index < customMediaDirectories.value.length; index += 1) {
    const value = customMediaDirectories.value[index].trim()
    if (!value) return `第 ${index + 1} 个自定义媒体目录不能为空。`
    if (!isAbsolutePath(value)) return `第 ${index + 1} 个自定义媒体目录必须是绝对路径。`
    if (/[*?]/.test(value)) return `第 ${index + 1} 个自定义媒体目录不能包含通配符。`
    const normalized = comparablePath(value).toLowerCase()
    if (seen.has(normalized)) return `第 ${index + 1} 个自定义媒体目录重复。`
    seen.add(normalized)
  }
  return ''
})
const customDirectoriesDirty = computed(() => {
  const current = customMediaDirectories.value.map(item => comparablePath(item).toLowerCase())
  const saved = savedCustomMediaDirectories.value.map(item => comparablePath(item).toLowerCase())
  return JSON.stringify(current) !== JSON.stringify(saved)
})
const canScanDirectories = computed(() => Boolean(
  pluginId.value
  && props.initialConfig?.enabled
  && savedCustomMediaDirectories.value.length
  && !customDirectoriesDirty.value
  && !customDirectoriesError.value
  && !saving.value
  && !clearing.value
  && !scanningDirectories.value,
))
const directoryScanTooltip = computed(() => {
  if (!customMediaDirectories.value.length) return '请先添加媒体目录并保存配置'
  if (customDirectoriesDirty.value) return '目录有未保存修改，请先保存配置'
  if (!props.initialConfig?.enabled) return '请先启用插件并保存配置'
  return '只处理新增、变更或上次处理失败的媒体'
})
const directoryPickerInitialPath = computed(() => {
  const index = directoryPickerIndex.value
  const value = index === null
    ? customMediaDirectories.value.find(item => isAbsolutePath(item.trim()))
    : customMediaDirectories.value[index]
  return value && isAbsolutePath(value.trim()) ? value.trim() : '/'
})
const canSave = computed(() => !saving.value && !clearing.value && !osError.value && !assrtError.value && !concurrentTasksError.value && !attemptsError.value && !monitorIntervalError.value && !pathMappingsError.value && !customDirectoriesError.value)
const clearTitle = computed(() => clearSource.value === 'opensubtitles' ? '清除 OpenSubtitles 凭据' : '清除 ASSRT 凭据')
const clearMessage = computed(() => clearSource.value === 'opensubtitles'
  ? '将永久删除 API Key、用户名、密码和当前登录会话，并立即关闭 OpenSubtitles 来源。旧凭据无法恢复。'
  : '将永久删除 ASSRT Token，并立即关闭 ASSRT 来源。旧 Token 无法恢复。')

watch(() => props.initialConfig, applyInitialConfig, { immediate: true, deep: true })
onMounted(() => emit('layout', { maxWidth: '72rem' }))

function applyInitialConfig(): void {
  const initial = props.initialConfig || {}
  form.enabled = Boolean(initial.enabled)
  form.moviepilot_enabled = initial.moviepilot_enabled !== false
  form.opensubtitles_enabled = Boolean(initial.opensubtitles_enabled)
  form.assrt_enabled = Boolean(initial.assrt_enabled)
  form.shooter_enabled = Boolean(initial.shooter_enabled)
  form.thunder_enabled = Boolean(initial.thunder_enabled)
  form.allow_machine_translation = Boolean(initial.allow_machine_translation)
  form.ai_attribution_takeover_enabled = Boolean(initial.ai_attribution_takeover_enabled)
  form.directory_monitor_enabled = initial.directory_monitor_enabled !== false
  form.directory_monitor_interval = validMonitorInterval(initial.directory_monitor_interval) ? Number(initial.directory_monitor_interval) : 60
  form.max_concurrent_tasks = validConcurrentTasks(initial.max_concurrent_tasks) ? Number(initial.max_concurrent_tasks) : 2
  form.max_candidate_attempts = validAttemptCount(initial.max_candidate_attempts) ? Number(initial.max_candidate_attempts) : 3
  form.package_attribution_strategy = initial.package_attribution_strategy === 'host_recognition'
    ? 'host_recognition'
    : 'trust_package'
  pathMappings.value = normalizePathMappings(initial.path_mappings)
  customMediaDirectories.value = normalizeCustomMediaDirectories(initial.custom_media_directories)
  savedCustomMediaDirectories.value = [...customMediaDirectories.value]
  opensubtitlesConfigured.value = Boolean(initial.opensubtitles_configured)
  assrtConfigured.value = Boolean(initial.assrt_configured)

  const normalizedAllowed = normalizeFormats(initial.allowed_formats)
  allowedFormats.value = normalizedAllowed.length ? normalizedAllowed : [...defaultFormats]
  formatPriority.value = mergeOrder(normalizeFormats(initial.format_priority), allowedFormats.value)
  sourcePriority.value = mergeSourceOrder(initial.source_priority)
  clearCredentialDrafts()
  saveError.value = ''
}

function validAttemptCount(value: unknown): boolean {
  const number = Number(value)
  return Number.isInteger(number) && number >= 1 && number <= 10
}

function validConcurrentTasks(value: unknown): boolean {
  const number = Number(value)
  return Number.isInteger(number) && number >= 1 && number <= 4
}

function validMonitorInterval(value: unknown): boolean {
  const number = Number(value)
  return Number.isInteger(number) && number >= 30 && number <= 3600
}

function normalizeFormats(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return [...new Set(value
    .filter((item): item is string => typeof item === 'string')
    .map(item => item.trim().replace(/^\./, '').toUpperCase())
    .filter(Boolean))]
}

function mergeOrder(saved: string[], allowed: string[]): string[] {
  const allowedSet = new Set(allowed)
  return [...saved.filter(item => allowedSet.has(item)), ...allowed.filter(item => !saved.includes(item))]
}

function mergeSourceOrder(value: unknown): SubtitleSource[] {
  const valid = Array.isArray(value)
    ? value.filter((item): item is SubtitleSource => defaultSources.includes(item as SubtitleSource))
    : []
  return [...new Set([...valid, ...defaultSources])]
}

function normalizePathMappings(value: unknown): PathMapping[] {
  if (!Array.isArray(value)) return []
  return value.flatMap(item => {
    if (!item || typeof item !== 'object') return []
    const record = item as Record<string, unknown>
    return [{
      source_prefix: typeof record.source_prefix === 'string' ? record.source_prefix : '',
      target_prefix: typeof record.target_prefix === 'string' ? record.target_prefix : '',
    }]
  })
}

function normalizeCustomMediaDirectories(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return [...new Set(value.filter((item): item is string => typeof item === 'string').map(item => item.trim()).filter(Boolean))]
}

function addPathMapping(): void {
  pathMappings.value.push({ source_prefix: '', target_prefix: '' })
}

function removePathMapping(index: number): void {
  pathMappings.value.splice(index, 1)
}

function addCustomMediaDirectory(): void {
  customMediaDirectories.value.push('')
}

function removeCustomMediaDirectory(index: number): void {
  customMediaDirectories.value.splice(index, 1)
}

function openDirectoryPicker(index: number | null = null): void {
  directoryPickerIndex.value = index
  directoryPickerOpen.value = true
}

function selectDirectory(path: string): void {
  const normalized = path.trim()
  const index = directoryPickerIndex.value
  if (index !== null && customMediaDirectories.value[index] !== undefined) {
    customMediaDirectories.value[index] = normalized
    return
  }
  const comparable = comparablePath(normalized).toLowerCase()
  if (!customMediaDirectories.value.some(item => comparablePath(item).toLowerCase() === comparable)) {
    customMediaDirectories.value.push(normalized)
  }
}

function toggleSource(source: SubtitleSource): void {
  openSource.value = openSource.value === source ? null : source
}

function isAbsolutePath(value: string): boolean {
  return value.startsWith('/') || /^[A-Za-z]:[\\/]/.test(value) || /^\\\\[^\\]+/.test(value)
}

function comparablePath(value: string): string {
  const normalized = value.trim().replaceAll('\\', '/').replace(/\/+$/, '') || '/'
  return /^[A-Za-z]:\//.test(normalized) ? normalized.toLowerCase() : normalized
}

function pathMappingFieldError(index: number, field: keyof PathMapping): string {
  const row = pathMappings.value[index]
  if (!row) return ''
  const value = row[field].trim()
  const fieldLabel = field === 'source_prefix' ? '历史目录前缀' : '当前目录前缀'
  if (!value) return `第 ${index + 1} 行${fieldLabel}不能为空。`
  if (!isAbsolutePath(value)) return `第 ${index + 1} 行${fieldLabel}必须是绝对路径。`
  if (/[*?]/.test(value)) return `第 ${index + 1} 行${fieldLabel}不能包含通配符或正则表达式。`

  const source = comparablePath(row.source_prefix)
  const target = comparablePath(row.target_prefix)
  if (field === 'target_prefix' && source === target) return `第 ${index + 1} 行的历史目录与当前目录不能相同。`
  if (field === 'source_prefix') {
    const duplicate = pathMappings.value.some((item, itemIndex) => (
      itemIndex !== index && comparablePath(item.source_prefix) === source
    ))
    if (duplicate) return `第 ${index + 1} 行的历史目录前缀重复。`
  }
  const chained = pathMappings.value.some((item, itemIndex) => (
    itemIndex !== index && comparablePath(item.source_prefix) === target
  ))
  if (field === 'target_prefix' && chained) return `第 ${index + 1} 行会形成链式映射，请直接填写最终目录。`
  return ''
}

function enabledKey(source: SubtitleSource): 'moviepilot_enabled' | 'opensubtitles_enabled' | 'assrt_enabled' | 'shooter_enabled' | 'thunder_enabled' {
  return `${source}_enabled` as 'moviepilot_enabled' | 'opensubtitles_enabled' | 'assrt_enabled' | 'shooter_enabled' | 'thunder_enabled'
}

function configured(source: SubtitleSource): boolean {
  if (source === 'moviepilot' || source === 'shooter' || source === 'thunder') return true
  return source === 'opensubtitles' ? opensubtitlesConfigured.value : assrtConfigured.value
}

function sourceValidation(source: SubtitleSource): string {
  if (source === 'opensubtitles') return osError.value
  if (source === 'assrt') return assrtError.value
  return ''
}

function move<T>(items: T[], index: number, direction: -1 | 1): void {
  const next = index + direction
  if (next < 0 || next >= items.length) return
  const [item] = items.splice(index, 1)
  items.splice(next, 0, item)
}

function nonSensitiveConfig(): NonSensitiveConfig {
  return {
    enabled: form.enabled,
    moviepilot_enabled: form.moviepilot_enabled,
    opensubtitles_enabled: form.opensubtitles_enabled,
    assrt_enabled: form.assrt_enabled,
    shooter_enabled: form.shooter_enabled,
    thunder_enabled: form.thunder_enabled,
    allow_machine_translation: form.allow_machine_translation,
    ai_attribution_takeover_enabled: form.ai_attribution_takeover_enabled,
    directory_monitor_enabled: form.directory_monitor_enabled,
    directory_monitor_interval: Number(form.directory_monitor_interval),
    max_concurrent_tasks: Number(form.max_concurrent_tasks),
    max_candidate_attempts: Number(form.max_candidate_attempts),
    source_priority: [...sourcePriority.value],
    format_priority: [...formatPriority.value],
    path_mappings: pathMappings.value.map(item => ({
      source_prefix: item.source_prefix.trim(),
      target_prefix: item.target_prefix.trim(),
    })),
    custom_media_directories: customMediaDirectories.value.map(item => item.trim()),
    package_attribution_strategy: form.package_attribution_strategy,
  }
}

async function saveConfig(): Promise<void> {
  saveError.value = ''
  if (!canSave.value) {
    saveError.value = osError.value || assrtError.value || concurrentTasksError.value || attemptsError.value || monitorIntervalError.value || pathMappingsError.value || customDirectoriesError.value || '请修正配置后再保存。'
    return
  }
  if (!hasOsUpdate.value && !hasAssrtUpdate.value) {
    emit('save', nonSensitiveConfig())
    return
  }
  if (!pluginId.value) {
    saveError.value = '缺少插件实例 ID，无法安全写入凭据。'
    return
  }

  saving.value = true
  try {
    if (hasOsUpdate.value) {
      const payload = Object.fromEntries(
        Object.entries(credentials.opensubtitles)
          .map(([key, value]) => [key, value.trim()])
          .filter(([, value]) => Boolean(value)),
      )
      const response = await updateCredentials(props.api, pluginId.value, 'opensubtitles', payload)
      opensubtitlesConfigured.value = Boolean(response.data?.configured)
    }
    if (hasAssrtUpdate.value) {
      const response = await updateCredentials(props.api, pluginId.value, 'assrt', { token: credentials.assrt.token.trim() })
      assrtConfigured.value = Boolean(response.data?.configured)
    }
    clearCredentialDrafts()
    showNotice('凭据已更新', 'success')
    emit('save', nonSensitiveConfig())
  } catch (requestError) {
    saveError.value = getErrorMessage(requestError, '凭据更新失败，普通配置尚未保存。')
  } finally {
    saving.value = false
  }
}

async function scanDirectoriesNow(): Promise<void> {
  if (!canScanDirectories.value) return
  directoryScanMessage.value = ''
  saveError.value = ''
  scanningDirectories.value = true
  try {
    const response = await scanCustomDirectories(props.api, pluginId.value)
    directoryScanType.value = response.fallback_file_count > 0 ? 'warning' : 'success'
    directoryScanMessage.value = [
      response.message,
      `目录文件 ${response.indexed_file_count} 个`,
      `未变更已跳过 ${response.unchanged_count} 个`,
      `本次处理 ${response.matched_count} 个`,
      response.retry_count ? `重试失败项 ${response.retry_count} 个` : '',
      response.fallback_file_count ? `路径解析兜底 ${response.fallback_file_count} 个` : '',
    ].filter(Boolean).join('；')
    showNotice(response.message, directoryScanType.value)
  } catch (requestError) {
    saveError.value = getErrorMessage(requestError, '自定义目录扫描失败')
  } finally {
    scanningDirectories.value = false
  }
}

function clearCredentialDrafts(): void {
  credentials.opensubtitles.api_key = ''
  credentials.opensubtitles.username = ''
  credentials.opensubtitles.password = ''
  credentials.assrt.token = ''
  showApiKey.value = false
  showPassword.value = false
  showAssrtToken.value = false
}

function requestClear(source: ExternalSource): void {
  clearSource.value = source
  clearOpen.value = true
}

async function confirmClear(): Promise<void> {
  const source = clearSource.value
  if (!source) return
  if (!pluginId.value) {
    clearOpen.value = false
    saveError.value = '缺少插件实例 ID，无法安全清除凭据。'
    return
  }
  clearing.value = true
  try {
    const response = await clearCredentials(props.api, pluginId.value, source)
    if (source === 'opensubtitles') {
      opensubtitlesConfigured.value = false
      form.opensubtitles_enabled = false
      credentials.opensubtitles.api_key = ''
      credentials.opensubtitles.username = ''
      credentials.opensubtitles.password = ''
    } else {
      assrtConfigured.value = false
      form.assrt_enabled = false
      credentials.assrt.token = ''
    }
    clearOpen.value = false
    clearSource.value = null
    if (response.success) {
      showNotice('凭据已清除，字幕源已关闭', 'success')
    } else {
      saveError.value = response.message || '凭据已清除且来源已关闭，但开关保存失败，请重试保存普通配置。'
      showNotice('凭据已清除，来源开关需要重新保存', 'warning')
    }
  } catch (requestError) {
    clearOpen.value = false
    saveError.value = getErrorMessage(requestError, '凭据清除失败')
  } finally {
    clearing.value = false
  }
}

function showNotice(text: string, color: 'success' | 'error' | 'warning'): void {
  toast?.[color](text)
}

</script>

<template>
  <div class="config-shell">
    <header class="config-header">
      <div class="config-brand">
        <div class="config-brand-mark"><VIcon icon="mdi-subtitles-outline" size="22" /></div>
        <div>
          <span>MoviePilot</span>
          <h2>字幕下载助手</h2>
        </div>
      </div>
      <div class="config-header-actions">
        <VChip :color="form.enabled ? 'success' : 'default'" variant="tonal" size="small" label>{{ form.enabled ? '已启用' : '未启用' }}</VChip>
        <VTooltip text="关闭设置">
          <template #activator="{ props: tooltipProps }"><VBtn v-bind="tooltipProps" icon="mdi-close" variant="text" aria-label="关闭设置" :disabled="saving || clearing" @click="emit('close')" /></template>
        </VTooltip>
      </div>
    </header>

    <VAlert v-if="saveError" type="error" variant="tonal" density="compact" class="mx-5 mt-4" closable @click:close="saveError = ''">{{ saveError }}</VAlert>

    <form class="config-form" @submit.prevent="saveConfig">
      <section id="basic-settings" class="config-section runtime-section" aria-labelledby="basic-settings-title">
        <div class="section-heading"><VIcon icon="mdi-power-settings" /><div><h3 id="basic-settings-title">运行方式</h3></div></div>
        <div class="section-content runtime-settings">
          <div class="setting-row">
            <div><strong>自动处理</strong><span>接收整理事件并创建字幕任务</span></div>
            <VSwitch v-model="form.enabled" aria-label="启用自动处理" inset hide-details />
          </div>
          <div class="setting-row">
            <div><strong>目录监控</strong><span>定时检查新增或变更媒体</span></div>
            <VSwitch v-model="form.directory_monitor_enabled" aria-label="定时监控新增媒体" inset hide-details />
          </div>
          <div class="setting-row">
            <div><strong>同时处理任务</strong><span>默认 2 个；同一目标串行，各字幕源独立限流</span></div>
            <VTextField v-model.number="form.max_concurrent_tasks" type="number" min="1" max="4" step="1" suffix="个" label="并发数" :error-messages="concurrentTasksError ? [concurrentTasksError] : []" class="attempt-field" />
          </div>
          <VTextField
            v-model.number="form.directory_monitor_interval"
            type="number"
            min="30"
            max="3600"
            step="30"
            suffix="秒"
            label="巡检间隔"
            :disabled="!form.directory_monitor_enabled"
            :error-messages="monitorIntervalError ? [monitorIntervalError] : []"
          />
        </div>
      </section>

      <section id="custom-directory" class="config-section media-section" aria-labelledby="custom-directory-title">
        <div class="section-heading">
          <VIcon icon="mdi-folder-search-outline" />
          <div>
            <h3 id="custom-directory-title">自定义媒体目录</h3>
          </div>
        </div>
        <div class="section-content custom-directory-settings">
          <div v-if="customMediaDirectories.length" class="custom-directory-list">
            <div v-for="(directory, index) in customMediaDirectories" :key="index" class="custom-directory-row">
              <VTextField
                v-model="customMediaDirectories[index]"
                label="本地媒体目录"
                placeholder="/media/strm"
                prepend-inner-icon="mdi-folder-outline"
                append-inner-icon="mdi-folder-open-outline"
                :error-messages="customDirectoriesError ? [customDirectoriesError] : []"
                @click:append-inner="openDirectoryPicker(index)"
              />
              <VTooltip text="删除此目录">
                <template #activator="{ props: tooltipProps }">
                  <VBtn v-bind="tooltipProps" icon="mdi-delete-outline" variant="text" color="error" :aria-label="`删除第 ${index + 1} 个自定义媒体目录`" @click="removeCustomMediaDirectory(index)" />
                </template>
              </VTooltip>
            </div>
          </div>
          <div v-else class="mapping-empty">
            <VIcon icon="mdi-folder-off-outline" size="20" />
            <span>未配置时继续使用整理事件提供的原始目标路径。</span>
          </div>
          <div class="custom-directory-actions">
            <VBtn variant="tonal" prepend-icon="mdi-folder-search-outline" @click="openDirectoryPicker()">浏览目录</VBtn>
            <VBtn variant="text" prepend-icon="mdi-plus" @click="addCustomMediaDirectory">手动添加</VBtn>
            <VTooltip :text="directoryScanTooltip">
              <template #activator="{ props: tooltipProps }">
                <span v-bind="tooltipProps">
                  <VBtn
                    color="primary"
                    variant="flat"
                    prepend-icon="mdi-folder-search-outline"
                    :loading="scanningDirectories"
                    :disabled="!canScanDirectories"
                    @click="scanDirectoriesNow"
                  >立即扫描并刮削</VBtn>
                </span>
              </template>
            </VTooltip>
          </div>
          <VAlert
            v-if="directoryScanMessage"
            :type="directoryScanType"
            variant="tonal"
            density="compact"
            closable
            @click:close="directoryScanMessage = ''"
          >{{ directoryScanMessage }}</VAlert>
        </div>
      </section>

      <VExpansionPanels v-model="advancedOpen" class="advanced-panel" variant="accordion">
        <VExpansionPanel value="path-mapping">
          <VExpansionPanelTitle>
            <div class="advanced-title"><span class="section-icon"><VIcon icon="mdi-map-marker-path" size="19" /></span><div><strong>高级兼容</strong><small>整理历史路径映射 · {{ pathMappings.length }} 条</small></div></div>
          </VExpansionPanelTitle>
          <VExpansionPanelText>
            <div class="mapping-settings">
          <div v-if="pathMappings.length" class="mapping-list">
            <div v-for="(mapping, index) in pathMappings" :key="index" class="mapping-row">
              <VTextField
                v-model="mapping.source_prefix"
                label="历史目录前缀"
                placeholder="/旧挂载/媒体"
                prepend-inner-icon="mdi-history"
                :error-messages="pathMappingFieldError(index, 'source_prefix') ? [pathMappingFieldError(index, 'source_prefix')] : []"
              />
              <VIcon icon="mdi-arrow-right" class="mapping-arrow" aria-hidden="true" />
              <VTextField
                v-model="mapping.target_prefix"
                label="当前目录前缀"
                placeholder="/当前挂载/媒体"
                prepend-inner-icon="mdi-folder-outline"
                :error-messages="pathMappingFieldError(index, 'target_prefix') ? [pathMappingFieldError(index, 'target_prefix')] : []"
              />
              <VTooltip text="删除此路径映射">
                <template #activator="{ props: tooltipProps }">
                  <VBtn
                    v-bind="tooltipProps"
                    icon="mdi-delete-outline"
                    variant="text"
                    color="error"
                    :aria-label="`删除第 ${index + 1} 条路径映射`"
                    @click="removePathMapping(index)"
                  />
                </template>
              </VTooltip>
            </div>
          </div>
          <div v-else class="mapping-empty">
            <VIcon icon="mdi-map-marker-off-outline" size="20" />
            <span>未配置映射时直接使用整理历史中的原始目标路径。</span>
          </div>
          <VBtn variant="tonal" prepend-icon="mdi-plus" class="mapping-add" @click="addPathMapping">添加路径映射</VBtn>
            </div>
          </VExpansionPanelText>
        </VExpansionPanel>
      </VExpansionPanels>

      <section id="source-settings" class="config-section source-section" aria-labelledby="source-settings-title">
        <div class="section-heading"><VIcon icon="mdi-database-outline" /><div><h3 id="source-settings-title">字幕源</h3></div></div>
        <div class="section-content">
          <VAlert v-if="osError || assrtError" type="error" variant="tonal" density="compact" class="mb-3">
            {{ [osError, assrtError].filter(Boolean).join(' ') }}
          </VAlert>
          <div class="source-config-list">
            <div v-for="meta in sourceMeta" :key="meta.source" class="source-config-row" :class="{ 'source-config-row--open': openSource === meta.source }">
              <div class="source-config-main">
                <span class="source-config-icon"><VIcon :icon="meta.icon" size="20" /></span>
                <div class="source-config-name"><strong>{{ sourceLabels[meta.source] }}</strong><span>{{ form[enabledKey(meta.source)] ? '已启用' : '未启用' }}</span></div>
                <VChip :color="configured(meta.source) ? 'success' : 'warning'" variant="tonal" size="small" label>{{ configured(meta.source) ? '可用' : '待配置' }}</VChip>
                <VSwitch v-model="form[enabledKey(meta.source)]" :aria-label="`启用 ${sourceLabels[meta.source]}`" hide-details inset density="compact" />
                <VTooltip :text="openSource === meta.source ? '收起设置' : '展开设置'">
                  <template #activator="{ props: tooltipProps }"><VBtn v-bind="tooltipProps" :icon="openSource === meta.source ? 'mdi-chevron-up' : 'mdi-tune-variant'" size="small" variant="text" :aria-label="`${openSource === meta.source ? '收起' : '展开'} ${sourceLabels[meta.source]} 设置`" @click="toggleSource(meta.source)" /></template>
                </VTooltip>
              </div>
              <VExpandTransition>
                <div v-if="openSource === meta.source" class="source-config-detail">
                <VAlert v-if="sourceValidation(meta.source)" type="error" variant="tonal" density="compact" class="mb-3">{{ sourceValidation(meta.source) }}</VAlert>

                <div v-if="meta.source === 'moviepilot'" class="source-body-note">
                  <VIcon icon="mdi-shield-lock-outline" size="20" />
                  <span>站点身份信息由 MoviePilot 在下载前重新读取，本插件不保存或展示 Cookie。</span>
                </div>

                <div v-else-if="meta.source === 'opensubtitles'" class="credential-fields">
                  <VTextField
                    v-model="credentials.opensubtitles.api_key"
                    label="API Key"
                    :type="showApiKey ? 'text' : 'password'"
                    autocomplete="new-password"
                    placeholder="留空则保留现有值"
                  >
                    <template #append-inner>
                      <VBtn
                        :icon="showApiKey ? 'mdi-eye-off-outline' : 'mdi-eye-outline'"
                        size="small"
                        variant="text"
                        :aria-label="showApiKey ? '隐藏 API Key' : '显示 API Key'"
                        @click="showApiKey = !showApiKey"
                      />
                    </template>
                  </VTextField>
                  <VTextField v-model="credentials.opensubtitles.username" label="用户名" autocomplete="off" placeholder="留空则保留现有值" />
                  <VTextField
                    v-model="credentials.opensubtitles.password"
                    label="密码"
                    :type="showPassword ? 'text' : 'password'"
                    autocomplete="new-password"
                    placeholder="留空则保留现有值"
                  >
                    <template #append-inner>
                      <VBtn
                        :icon="showPassword ? 'mdi-eye-off-outline' : 'mdi-eye-outline'"
                        size="small"
                        variant="text"
                        :aria-label="showPassword ? '隐藏密码' : '显示密码'"
                        @click="showPassword = !showPassword"
                      />
                    </template>
                  </VTextField>
                  <div class="credential-actions"><VBtn variant="text" color="error" prepend-icon="mdi-key-remove" :disabled="!opensubtitlesConfigured || clearing" @click="requestClear('opensubtitles')">清除凭据</VBtn></div>
                </div>

                <div v-else-if="meta.source === 'assrt'" class="credential-fields credential-fields--single">
                  <VTextField
                    v-model="credentials.assrt.token"
                    label="Token"
                    :type="showAssrtToken ? 'text' : 'password'"
                    autocomplete="new-password"
                    placeholder="留空则保留现有值"
                  >
                    <template #append-inner>
                      <VBtn
                        :icon="showAssrtToken ? 'mdi-eye-off-outline' : 'mdi-eye-outline'"
                        size="small"
                        variant="text"
                        :aria-label="showAssrtToken ? '隐藏 Token' : '显示 Token'"
                        @click="showAssrtToken = !showAssrtToken"
                      />
                    </template>
                  </VTextField>
                  <div class="credential-actions"><VBtn variant="text" color="error" prepend-icon="mdi-key-remove" :disabled="!assrtConfigured || clearing" @click="requestClear('assrt')">清除凭据</VBtn></div>
                </div>

                <div v-else class="source-body-note">
                  <VIcon :icon="meta.source === 'shooter' ? 'mdi-target' : 'mdi-flash-outline'" size="20" />
                  <span v-if="meta.source === 'shooter'">无需账号。射手必须使用视频内容指纹；STRM 会对内部媒体地址顺序读取四个 Range 小片段。</span>
                  <span v-else>无需账号。STRM 直接使用文件名查询且不读取内部地址；真实视频会额外计算 CID 标记精确匹配。</span>
                </div>
                </div>
              </VExpandTransition>
            </div>
          </div>
        </div>
      </section>

      <section id="candidate-settings" class="config-section rule-section" aria-labelledby="candidate-settings-title">
        <div class="section-heading"><VIcon icon="mdi-sort-variant" /><div><h3 id="candidate-settings-title">候选策略</h3></div></div>
        <div class="section-content candidate-settings">
          <div class="policy-list">
            <div class="policy-row">
              <span class="policy-icon"><VIcon icon="mdi-package-variant-closed-check" size="19" /></span>
              <div><strong>压缩包字幕归属</strong><span>{{ form.package_attribution_strategy === 'trust_package' ? '继承候选媒体身份' : '逐个调用 MoviePilot 识别' }}</span></div>
              <VSelect
              v-model="form.package_attribution_strategy"
                :items="attributionOptions"
                label="归属方式"
                density="compact"
                class="policy-select"
              />
            </div>
            <div class="policy-row">
              <span class="policy-icon"><VIcon icon="mdi-translate" size="19" /></span>
              <div><strong>机器翻译字幕</strong><span>允许机器或 AI 翻译候选</span></div>
              <VSwitch v-model="form.allow_machine_translation" aria-label="允许机器或 AI 翻译字幕" inset hide-details />
            </div>
            <div class="policy-row">
              <span class="policy-icon"><VIcon icon="mdi-creation-outline" size="19" /></span>
              <div><strong>AI 归属接管</strong><span>{{ hostAiEnabled ? '仅在常规归属失败时启用' : 'MoviePilot 智能助手未启用' }}</span></div>
              <VSwitch v-model="form.ai_attribution_takeover_enabled" aria-label="字幕归属失败时允许 AI 智能接管" inset hide-details :disabled="!hostAiEnabled" />
            </div>
            <div class="policy-row">
              <span class="policy-icon"><VIcon icon="mdi-counter" size="19" /></span>
              <div><strong>候选尝试数</strong><span>单个媒体最多下载候选数量</span></div>
              <VTextField v-model.number="form.max_candidate_attempts" type="number" min="1" max="10" step="1" label="次数" :error-messages="attemptsError ? [attemptsError] : []" class="attempt-field" />
            </div>
          </div>

          <div class="priority-board">
            <div class="priority-group">
              <h4>格式顺序</h4>
              <div class="priority-lane">
                <div v-for="(format, index) in formatPriority" :key="format" class="priority-token">
                  <span class="priority-index">{{ index + 1 }}</span><strong>{{ format }}</strong>
                  <VTooltip text="向前"><template #activator="{ props: tooltipProps }"><VBtn v-bind="tooltipProps" icon="mdi-chevron-left" size="x-small" variant="text" :disabled="index === 0" :aria-label="`前移 ${format}`" @click="move(formatPriority, index, -1)" /></template></VTooltip>
                  <VTooltip text="向后"><template #activator="{ props: tooltipProps }"><VBtn v-bind="tooltipProps" icon="mdi-chevron-right" size="x-small" variant="text" :disabled="index === formatPriority.length - 1" :aria-label="`后移 ${format}`" @click="move(formatPriority, index, 1)" /></template></VTooltip>
                </div>
              </div>
            </div>
            <div class="priority-group">
              <h4>来源顺序</h4>
              <div class="priority-lane priority-lane--sources">
                <div v-for="(source, index) in sourcePriority" :key="source" class="priority-token">
                  <span class="priority-index">{{ index + 1 }}</span><strong>{{ sourceLabels[source] }}</strong>
                  <VTooltip text="向前"><template #activator="{ props: tooltipProps }"><VBtn v-bind="tooltipProps" icon="mdi-chevron-left" size="x-small" variant="text" :disabled="index === 0" :aria-label="`前移 ${sourceLabels[source]}`" @click="move(sourcePriority, index, -1)" /></template></VTooltip>
                  <VTooltip text="向后"><template #activator="{ props: tooltipProps }"><VBtn v-bind="tooltipProps" icon="mdi-chevron-right" size="x-small" variant="text" :disabled="index === sourcePriority.length - 1" :aria-label="`后移 ${sourceLabels[source]}`" @click="move(sourcePriority, index, 1)" /></template></VTooltip>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <footer class="config-actions">
        <VBtn type="button" variant="text" color="default" :disabled="saving || clearing" @click="emit('close')">取消</VBtn>
        <VBtn type="submit" color="primary" variant="flat" prepend-icon="mdi-content-save" :loading="saving" :disabled="!canSave">保存配置</VBtn>
      </footer>
    </form>

    <ConfirmDialog v-model="clearOpen" :title="clearTitle" :message="clearMessage" confirm-text="确认清除" :loading="clearing" @confirm="confirmClear" />
    <DirectoryPickerDialog v-model="directoryPickerOpen" :api="props.api" :initial-path="directoryPickerInitialPath" @select="selectDirectory" />
  </div>
</template>

<style scoped>
.config-shell { width: 100%; min-width: 0; color: rgb(var(--v-theme-on-surface)); background: rgb(var(--v-theme-background)); }
.config-header { display: flex; min-height: 4.5rem; align-items: center; justify-content: space-between; gap: 1rem; padding: 0.75rem 1.25rem; border-bottom: 1px solid rgba(var(--v-border-color), var(--v-border-opacity)); background: rgb(var(--v-theme-surface)); box-shadow: 0 0.25rem 1.125rem rgba(30, 26, 48, 0.06); }
.config-brand { display: flex; min-width: 0; align-items: center; gap: 0.625rem; }
.config-brand-mark { display: grid; width: 2.25rem; height: 2.25rem; flex: 0 0 auto; place-items: center; border-radius: 0.5rem; color: rgb(var(--v-theme-on-primary)); background: rgb(var(--v-theme-primary)); box-shadow: 0 0.35rem 0.9rem rgba(var(--v-theme-primary), 0.24); }
.config-brand span { display: block; color: rgba(var(--v-theme-on-surface), var(--v-medium-emphasis-opacity)); font-size: 0.625rem; font-weight: 700; letter-spacing: 0; text-transform: uppercase; }
.config-header h2 { margin: 0.125rem 0 0; font-size: 1rem; font-weight: 700; letter-spacing: 0; }
.config-header-actions { display: flex; flex: 0 0 auto; align-items: center; gap: 0.375rem; }
.section-heading { display: flex; align-items: flex-start; gap: 0.625rem; }
.section-heading > :deep(.v-icon) { display: grid; width: 2rem; height: 2rem; flex: 0 0 auto; place-items: center; border: 0; border-radius: 0.375rem; color: rgb(var(--v-theme-primary)); background: rgba(var(--v-theme-primary), 0.12); }
.section-heading h3 { margin: 0; font-size: 0.9375rem; font-weight: 650; letter-spacing: 0; }
.section-content { min-width: 0; }
.mapping-settings { display: grid; gap: 0.75rem; }
.custom-directory-settings { display: grid; gap: 0.75rem; }
.custom-directory-list { overflow: hidden; border: 1px solid rgba(var(--v-border-color), var(--v-border-opacity)); border-radius: 0.375rem; }
.custom-directory-row { display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: start; gap: 0.625rem; padding: 0.875rem; }
.custom-directory-row + .custom-directory-row { border-top: 1px solid rgba(var(--v-border-color), var(--v-border-opacity)); }
.custom-directory-row > :last-child { margin-top: 0.375rem; }
.custom-directory-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 0.625rem; }
.mapping-list { overflow: hidden; border: 1px solid rgba(var(--v-border-color), var(--v-border-opacity)); border-radius: 0.375rem; }
.mapping-row { display: grid; grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr) auto; align-items: start; gap: 0.625rem; padding: 0.875rem; }
.mapping-row + .mapping-row { border-top: 1px solid rgba(var(--v-border-color), var(--v-border-opacity)); }
.mapping-arrow { margin-top: 1rem; color: rgba(var(--v-theme-on-surface), var(--v-medium-emphasis-opacity)); }
.mapping-row > :last-child { margin-top: 0.375rem; }
.mapping-empty { display: flex; min-height: 3.25rem; align-items: center; gap: 0.625rem; padding: 0.75rem; border: 1px dashed rgba(var(--v-border-color), var(--v-border-opacity)); border-radius: 0.375rem; color: rgba(var(--v-theme-on-surface), var(--v-medium-emphasis-opacity)); font-size: 0.8125rem; }
.mapping-add { justify-self: start; }
.source-config-list { overflow: hidden; border: 1px solid rgba(var(--v-border-color), var(--v-border-opacity)); border-radius: 0.375rem; }
.source-body-note { display: flex; align-items: flex-start; gap: 0.625rem; color: rgba(var(--v-theme-on-surface), var(--v-medium-emphasis-opacity)); font-size: 0.8125rem; line-height: 1.55; }
.credential-fields { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 0.75rem; }
.credential-fields--single { grid-template-columns: minmax(0, 1fr); }
.credential-actions { grid-column: 1 / -1; display: flex; justify-content: flex-end; }
.candidate-settings { display: grid; gap: 1rem; }
.priority-group h4 { margin: 0 0 0.5rem; font-size: 0.8125rem; font-weight: 650; }
.priority-index { display: grid; width: 1.5rem; height: 1.5rem; place-items: center; border-radius: 50%; background: rgba(var(--v-theme-on-surface), 0.08); color: rgba(var(--v-theme-on-surface), var(--v-medium-emphasis-opacity)); font-size: 0.75rem; }
.config-actions { display: flex; position: sticky; z-index: 2; bottom: 0; align-items: center; justify-content: flex-end; gap: 0.75rem; padding: 0.75rem 1.25rem; border-top: 1px solid rgba(var(--v-border-color), var(--v-border-opacity)); background: rgba(var(--v-theme-surface), 0.96); box-shadow: 0 -0.25rem 1rem rgba(30, 26, 48, 0.05); }
.config-shell :deep(.v-btn:focus-visible), .config-shell :deep(.v-expansion-panel-title:focus-visible), .config-shell :deep(input:focus-visible) { outline: 2px solid rgb(var(--v-theme-primary)); outline-offset: 2px; }
@media (max-width: 47.5rem) { .mapping-row { grid-template-columns: minmax(0, 1fr) auto; } .mapping-row > :nth-child(1), .mapping-row > :nth-child(3) { grid-column: 1; } .mapping-row > :nth-child(2) { grid-column: 1; margin: -0.5rem 0 -0.25rem 1rem; transform: rotate(90deg); } .mapping-row > :nth-child(4) { grid-row: 1 / span 3; grid-column: 2; align-self: center; margin-top: 0; } }
.config-form {
  display: grid;
  grid-template-areas:
    'runtime media'
    'sources rules'
    'advanced advanced'
    'actions actions';
  grid-template-columns: minmax(18rem, 0.78fr) minmax(0, 1.22fr);
  align-items: start;
  gap: 1rem;
  padding: 1rem;
}
.config-section { display: block; min-width: 0; max-width: none; padding: 1.25rem; border: 1px solid rgba(var(--v-border-color), 0.08); border-radius: 0.5rem; background: rgb(var(--v-theme-surface)); box-shadow: 0 0.25rem 1.125rem rgba(30, 26, 48, 0.07); }
.runtime-section { grid-area: runtime; }
.media-section { grid-area: media; }
.source-section { grid-area: sources; }
.rule-section { grid-area: rules; }
.advanced-panel { grid-area: advanced; overflow: hidden; border: 1px solid rgba(var(--v-border-color), 0.08); border-radius: 0.5rem; background: rgb(var(--v-theme-surface)); box-shadow: 0 0.25rem 1.125rem rgba(30, 26, 48, 0.07); }
.advanced-panel :deep(.v-expansion-panel) { background: rgb(var(--v-theme-surface)); }
.advanced-panel :deep(.v-expansion-panel-title) { min-height: 4.25rem; padding-inline: 1.25rem; }
.advanced-title { display: flex; min-width: 0; align-items: center; gap: 0.75rem; }
.advanced-title strong, .advanced-title small { display: block; letter-spacing: 0; }
.advanced-title strong { font-size: 0.875rem; }
.advanced-title small { margin-top: 0.125rem; color: rgba(var(--v-theme-on-surface), var(--v-medium-emphasis-opacity)); font-size: 0.6875rem; }
.section-icon, .section-heading > :deep(.v-icon), .source-config-icon, .policy-icon { display: grid; flex: 0 0 auto; place-items: center; border: 0; border-radius: 0.375rem; color: rgb(var(--v-theme-primary)); background: rgba(var(--v-theme-primary), 0.12); }
.section-icon, .section-heading > :deep(.v-icon), .source-config-icon { width: 2.25rem; height: 2.25rem; }
.section-heading { align-items: center; margin-bottom: 1rem; }
.section-heading h3 { font-size: 0.9375rem; }
.runtime-settings { display: grid; gap: 0.75rem; }
.setting-row { display: grid; min-height: 3.75rem; grid-template-columns: minmax(0, 1fr) auto; align-items: center; gap: 0.75rem; padding: 0.5rem 0; border-bottom: 1px solid rgba(var(--v-border-color), var(--v-border-opacity)); }
.setting-row strong, .setting-row span { display: block; letter-spacing: 0; }
.setting-row strong { font-size: 0.8125rem; font-weight: 600; }
.setting-row span { margin-top: 0.125rem; color: rgba(var(--v-theme-on-surface), var(--v-medium-emphasis-opacity)); font-size: 0.6875rem; }
.custom-directory-list { background: rgb(var(--v-theme-surface)); }
.custom-directory-row { padding: 0.75rem; }
.source-config-list { display: grid; overflow: hidden; }
.source-config-row + .source-config-row { border-top: 1px solid rgba(var(--v-border-color), var(--v-border-opacity)); }
.source-config-row--open { background: rgba(var(--v-theme-surface-variant), 0.18); }
.source-config-main { display: grid; min-height: 4rem; grid-template-columns: auto minmax(0, 1fr) auto auto auto; align-items: center; gap: 0.625rem; padding: 0.5rem 0.625rem; }
.source-config-name { min-width: 0; }
.source-config-name strong, .source-config-name span { display: block; overflow: hidden; letter-spacing: 0; text-overflow: ellipsis; white-space: nowrap; }
.source-config-name strong { font-size: 0.8125rem; font-weight: 600; }
.source-config-name span { margin-top: 0.125rem; color: rgba(var(--v-theme-on-surface), var(--v-medium-emphasis-opacity)); font-size: 0.6875rem; }
.source-config-detail { padding: 1rem; border-top: 1px solid rgba(var(--v-border-color), var(--v-border-opacity)); background: rgb(var(--v-theme-surface)); }
.credential-fields { grid-template-columns: 1fr; }
.policy-list { overflow: hidden; border: 1px solid rgba(var(--v-border-color), var(--v-border-opacity)); border-radius: 0.375rem; }
.policy-row { display: grid; min-height: 4.25rem; grid-template-columns: auto minmax(0, 1fr) auto; align-items: center; gap: 0.75rem; padding: 0.625rem 0.75rem; }
.policy-row + .policy-row { border-top: 1px solid rgba(var(--v-border-color), var(--v-border-opacity)); }
.policy-icon { width: 2rem; height: 2rem; }
.policy-row > div { min-width: 0; }
.policy-row strong, .policy-row span { display: block; letter-spacing: 0; }
.policy-row strong { font-size: 0.8125rem; font-weight: 600; }
.policy-row span { margin-top: 0.125rem; color: rgba(var(--v-theme-on-surface), var(--v-medium-emphasis-opacity)); font-size: 0.6875rem; }
.policy-select { width: 12rem; }
.attempt-field { width: 6.5rem; max-width: 6.5rem; }
.priority-board { display: grid; gap: 1rem; }
.priority-group h4 { margin-bottom: 0.5rem; }
.priority-lane { display: flex; flex-wrap: wrap; gap: 0.5rem; }
.priority-token { display: grid; min-height: 2.5rem; grid-template-columns: auto minmax(2.25rem, auto) auto auto; align-items: center; gap: 0.25rem; padding: 0.25rem 0.25rem 0.25rem 0.5rem; border: 1px solid rgba(var(--v-border-color), var(--v-border-opacity)); border-radius: 0.375rem; background: rgb(var(--v-theme-surface)); }
.priority-token strong { overflow: hidden; font-size: 0.75rem; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
.priority-index { border-radius: 0.25rem; color: rgb(var(--v-theme-primary)); background: rgba(var(--v-theme-primary), 0.12); font-size: 0.6875rem; }
.config-actions { grid-area: actions; margin: 0 -1rem -1rem; }
@media (max-width: 959px) {
  .config-form { grid-template-areas: 'runtime' 'media' 'sources' 'rules' 'advanced' 'actions'; grid-template-columns: minmax(0, 1fr); }
  .config-section { padding: 1.25rem; }
  .credential-fields { grid-template-columns: 1fr; }
  .config-actions { margin-top: 0; }
}
@media (max-width: 37.5rem) {
  .config-header { gap: 0.5rem; padding-inline: 0.75rem; }
  .config-brand { gap: 0.5rem; }
  .config-brand-mark { width: 2rem; height: 2rem; }
  .config-header-actions :deep(.v-chip) { display: none; }
  .config-form { gap: 0.75rem; padding: 0.75rem; }
  .config-section { padding: 1rem; }
  .custom-directory-row { gap: 0.25rem; padding: 0.625rem; }
  .custom-directory-actions { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .custom-directory-actions > :deep(.v-btn), .custom-directory-actions > :last-child, .custom-directory-actions > :last-child :deep(.v-btn) { width: 100%; min-width: 0; }
  .custom-directory-actions > :last-child { grid-column: 1 / -1; }
  .source-config-main { grid-template-columns: auto minmax(0, 1fr) auto auto; }
  .source-config-main :deep(.v-chip) { display: none; }
  .policy-row { grid-template-columns: auto minmax(0, 1fr); }
  .policy-row > :last-child { grid-column: 2; justify-self: start; }
  .policy-select { width: 100%; max-width: 15rem; }
  .attempt-field { width: 7rem; max-width: 7rem; }
  .priority-token { max-width: 100%; }
  .advanced-panel :deep(.v-expansion-panel-title) { padding-inline: 1rem; }
  .advanced-title { gap: 0.625rem; }
  .config-actions { margin-inline: -0.75rem; margin-bottom: -0.75rem; padding-inline: 0.75rem; }
}
@media (prefers-reduced-motion: reduce) { .config-shell *, .config-shell *::before, .config-shell *::after { transition-duration: 0.01ms !important; animation-duration: 0.01ms !important; animation-iteration-count: 1 !important; } }
</style>
