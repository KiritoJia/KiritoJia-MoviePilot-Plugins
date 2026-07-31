<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import {
  clearTerminalTasks,
  getErrorMessage,
  listRecords,
  listSourceStatus,
  listTasks,
  scanCustomDirectories,
} from '@/api/client'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import StateChip from '@/components/StateChip.vue'
import type { PluginApi, SourceStatusItem, TaskListItem } from '@/types'
import {
  formatDate,
  mediaLabel,
  sourceHealthStates,
  sourceLabels,
  taskStates,
} from '@/types/presentation'

type OverviewTarget = 'tasks' | 'records' | 'search' | 'sources'

const props = defineProps<{
  api: PluginApi
  pluginId: string
  active: boolean
}>()

const emit = defineEmits<{
  action: []
  navigate: [view: OverviewTarget]
}>()

const runningCount = ref(0)
const queuedCount = ref(0)
const recordCount = ref(0)
const recentTasks = ref<TaskListItem[]>([])
const sources = ref<SourceStatusItem[]>([])
const loading = ref(false)
const refreshing = ref(false)
const loaded = ref(false)
const error = ref('')
const notice = ref('')
const noticeType = ref<'success' | 'warning'>('success')
const scanning = ref(false)
const clearing = ref(false)
const clearOpen = ref(false)
const pageVisible = ref(typeof document === 'undefined' || !document.hidden)
let pollTimer: ReturnType<typeof setInterval> | undefined
let requestId = 0

const enabledSources = computed(() => sources.value.filter(item => item.enabled))
const healthySources = computed(() => enabledSources.value.filter(item => item.health === 'healthy').length)
const metrics = computed(() => [
  { label: '处理中', value: String(runningCount.value), icon: 'mdi-progress-clock', tone: 'primary', target: 'tasks' as const },
  { label: '等待任务', value: String(queuedCount.value), icon: 'mdi-clock-outline', tone: 'info', target: 'tasks' as const },
  { label: '字幕记录', value: String(recordCount.value), icon: 'mdi-closed-caption-outline', tone: 'success', target: 'records' as const },
  { label: '可用来源', value: `${healthySources.value}/${enabledSources.value.length}`, icon: 'mdi-database-check-outline', tone: 'warning', target: 'sources' as const },
])

watch(
  () => props.active,
  active => {
    if (!active) {
      stopPolling()
      return
    }
    void loadOverview({ silent: loaded.value })
    syncPolling()
  },
  { immediate: true },
)

onMounted(() => {
  pageVisible.value = !document.hidden
  document.addEventListener('visibilitychange', handleVisibilityChange)
  syncPolling()
})

onBeforeUnmount(() => {
  document.removeEventListener('visibilitychange', handleVisibilityChange)
  stopPolling()
})

function stopPolling(): void {
  if (pollTimer) clearInterval(pollTimer)
  pollTimer = undefined
}

function syncPolling(): void {
  stopPolling()
  if (!props.active || !pageVisible.value) return
  pollTimer = window.setInterval(() => void loadOverview({ silent: true }), 10000)
}

function handleVisibilityChange(): void {
  pageVisible.value = !document.hidden
  syncPolling()
  if (props.active && pageVisible.value) void loadOverview({ silent: true })
}

async function loadOverview(options: { silent?: boolean } = {}): Promise<void> {
  const currentRequest = ++requestId
  if (options.silent) refreshing.value = true
  else loading.value = true
  if (!options.silent) error.value = ''

  const results = await Promise.allSettled([
    listTasks(props.api, props.pluginId, { page: 1, pageSize: 25, status: 'processing' }),
    listTasks(props.api, props.pluginId, { page: 1, pageSize: 25, status: 'queued' }),
    listTasks(props.api, props.pluginId, { page: 1, pageSize: 25 }),
    listRecords(props.api, props.pluginId, { page: 1, pageSize: 25 }),
    listSourceStatus(props.api, props.pluginId),
  ])

  if (currentRequest !== requestId) return
  const failures = results.filter(result => result.status === 'rejected')
  if (results[0].status === 'fulfilled') runningCount.value = results[0].value.total
  if (results[1].status === 'fulfilled') queuedCount.value = results[1].value.total
  if (results[2].status === 'fulfilled') recentTasks.value = results[2].value.items.slice(0, 6)
  if (results[3].status === 'fulfilled') recordCount.value = results[3].value.total
  if (results[4].status === 'fulfilled') sources.value = results[4].value

  loaded.value = true
  error.value = failures.length
    ? getErrorMessage((failures[0] as PromiseRejectedResult).reason, `有 ${failures.length} 项数据未能刷新`)
    : ''
  loading.value = false
  refreshing.value = false
}

async function scanDirectories(): Promise<void> {
  scanning.value = true
  notice.value = ''
  try {
    const response = await scanCustomDirectories(props.api, props.pluginId)
    noticeType.value = response.success ? 'success' : 'warning'
    notice.value = response.message || `已提交 ${response.submitted_count} 个任务`
    await loadOverview({ silent: true })
    emit('action')
  } catch (requestError) {
    noticeType.value = 'warning'
    notice.value = getErrorMessage(requestError, '目录扫描启动失败')
  } finally {
    scanning.value = false
  }
}

async function clearTasks(): Promise<void> {
  clearing.value = true
  notice.value = ''
  try {
    const response = await clearTerminalTasks(props.api, props.pluginId)
    clearOpen.value = false
    noticeType.value = 'success'
    notice.value = response.message || `已清理 ${response.deleted_count} 条任务`
    await loadOverview({ silent: true })
    emit('action')
  } catch (requestError) {
    clearOpen.value = false
    noticeType.value = 'warning'
    notice.value = getErrorMessage(requestError, '已结束任务清理失败')
  } finally {
    clearing.value = false
  }
}
</script>

<template>
  <section class="overview" aria-label="字幕下载概览">
    <VAlert
      v-if="notice"
      :type="noticeType"
      variant="tonal"
      density="compact"
      closable
      class="overview-alert"
      @click:close="notice = ''"
    >{{ notice }}</VAlert>

    <VAlert v-if="error && loaded" type="warning" variant="tonal" density="compact" class="overview-alert">
      <div class="inline-alert">
        <span>部分数据未能刷新：{{ error }}</span>
        <VBtn size="small" variant="text" prepend-icon="mdi-refresh" @click="loadOverview({ silent: true })">重试</VBtn>
      </div>
    </VAlert>

    <div v-if="loading" class="metric-grid" aria-label="正在加载概览">
      <VSkeletonLoader v-for="index in 4" :key="index" type="list-item-avatar-two-line" class="metric-card" />
    </div>
    <div v-else class="metric-grid">
      <button
        v-for="metric in metrics"
        :key="metric.label"
        type="button"
        class="metric-card"
        @click="emit('navigate', metric.target)"
      >
        <span class="metric-icon" :class="`metric-icon--${metric.tone}`"><VIcon :icon="metric.icon" size="23" /></span>
        <span class="metric-copy"><strong>{{ metric.value }}</strong><small>{{ metric.label }}</small></span>
        <VIcon icon="mdi-chevron-right" size="18" class="metric-chevron" />
      </button>
    </div>

    <div class="overview-layout">
      <section class="dashboard-panel recent-panel" aria-labelledby="recent-task-title">
        <header class="panel-header">
          <div><h2 id="recent-task-title">最近任务</h2><span>{{ recentTasks.length ? `显示最近 ${recentTasks.length} 条` : '暂无任务' }}</span></div>
          <VTooltip text="刷新概览"><template #activator="{ props: tooltipProps }"><VBtn v-bind="tooltipProps" icon="mdi-refresh" size="small" variant="text" :loading="refreshing" aria-label="刷新概览" @click="loadOverview({ silent: true })" /></template></VTooltip>
        </header>
        <div v-if="recentTasks.length" class="recent-list">
          <button v-for="task in recentTasks" :key="task.id" type="button" class="recent-item" @click="emit('navigate', 'tasks')">
            <span class="recent-media-icon"><VIcon :icon="task.media_type === 'movie' ? 'mdi-movie-outline' : 'mdi-television-classic'" size="19" /></span>
            <span class="recent-copy"><strong>{{ mediaLabel(task.media_title, task.year, task.season, task.episode) }}</strong><small>{{ task.target_file_name }}</small></span>
            <span class="recent-status"><StateChip :state="taskStates[task.status]" size="x-small" /><small>{{ formatDate(task.started_at || task.created_at) }}</small></span>
          </button>
        </div>
        <div v-else class="panel-empty"><VIcon icon="mdi-format-list-checks" size="28" /><span>暂无任务</span></div>
        <footer class="panel-footer"><VBtn variant="text" append-icon="mdi-arrow-right" @click="emit('navigate', 'tasks')">查看全部任务</VBtn></footer>
      </section>

      <div class="overview-side">
        <section class="dashboard-panel quick-panel" aria-labelledby="quick-action-title">
          <header class="panel-header"><div><h2 id="quick-action-title">快捷操作</h2></div></header>
          <div class="quick-actions">
            <button type="button" :disabled="scanning" @click="scanDirectories">
              <span class="quick-icon quick-icon--primary"><VIcon :icon="scanning ? 'mdi-loading mdi-spin' : 'mdi-folder-search-outline'" size="20" /></span>
              <span><strong>扫描媒体目录</strong><small>增量检查本地媒体</small></span><VIcon icon="mdi-chevron-right" size="18" />
            </button>
            <button type="button" @click="emit('navigate', 'search')">
              <span class="quick-icon quick-icon--info"><VIcon icon="mdi-text-search" size="20" /></span>
              <span><strong>手动搜索字幕</strong><small>选择媒体并检索来源</small></span><VIcon icon="mdi-chevron-right" size="18" />
            </button>
            <button type="button" :disabled="clearing" @click="clearOpen = true">
              <span class="quick-icon quick-icon--error"><VIcon icon="mdi-delete-sweep-outline" size="20" /></span>
              <span><strong>清理结束任务</strong><small>保留等待与处理中任务</small></span><VIcon icon="mdi-chevron-right" size="18" />
            </button>
          </div>
        </section>

        <section class="dashboard-panel source-panel" aria-labelledby="source-summary-title">
          <header class="panel-header">
            <div><h2 id="source-summary-title">字幕源</h2><span>{{ healthySources }} 个来源正常</span></div>
            <VBtn size="small" variant="text" icon="mdi-arrow-right" aria-label="查看字幕源" @click="emit('navigate', 'sources')" />
          </header>
          <div v-if="sources.length" class="source-mini-list">
            <button v-for="source in sources" :key="source.source" type="button" @click="emit('navigate', 'sources')">
              <span class="source-dot" :class="`source-dot--${source.health}`" />
              <strong>{{ sourceLabels[source.source] }}</strong>
              <span>{{ sourceHealthStates[source.health].label }}</span>
            </button>
          </div>
          <div v-else class="panel-empty panel-empty--compact"><span>暂无来源状态</span></div>
        </section>
      </div>
    </div>

    <ConfirmDialog
      v-model="clearOpen"
      title="清理已结束任务"
      message="将删除成功、跳过、失败和已中断的任务记录；等待中与处理中的任务会保留。字幕文件和字幕记录不会被删除。"
      confirm-text="清理任务"
      confirm-icon="mdi-delete-sweep-outline"
      :loading="clearing"
      @confirm="clearTasks"
    />
  </section>
</template>

<style scoped>
.overview { min-width: 0; }
.overview-alert { margin-bottom: 1rem; }
.inline-alert { display: flex; align-items: center; justify-content: space-between; gap: 1rem; }
.metric-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 1rem; }
.metric-card { display: grid; min-width: 0; min-height: 6.75rem; grid-template-columns: auto minmax(0, 1fr) auto; align-items: center; gap: 0.875rem; padding: 1rem; border: 1px solid rgba(var(--v-border-color), 0.08); border-radius: 0.5rem; color: rgb(var(--v-theme-on-surface)); text-align: start; background: rgb(var(--v-theme-surface)); box-shadow: 0 0.25rem 1.125rem rgba(30, 26, 48, 0.07); cursor: pointer; font: inherit; transition: box-shadow 160ms ease, transform 160ms ease; }
.metric-card:hover { box-shadow: 0 0.5rem 1.5rem rgba(30, 26, 48, 0.11); transform: translateY(-1px); }
.metric-card:focus-visible, .recent-item:focus-visible, .quick-actions button:focus-visible, .source-mini-list button:focus-visible { outline: 2px solid rgb(var(--v-theme-primary)); outline-offset: 2px; }
.metric-icon, .quick-icon, .recent-media-icon { display: grid; flex: 0 0 auto; place-items: center; border-radius: 0.5rem; }
.metric-icon { width: 2.75rem; height: 2.75rem; }
.metric-icon--primary, .quick-icon--primary { color: rgb(var(--v-theme-primary)); background: rgba(var(--v-theme-primary), 0.13); }
.metric-icon--info, .quick-icon--info { color: rgb(var(--v-theme-info)); background: rgba(var(--v-theme-info), 0.13); }
.metric-icon--success { color: rgb(var(--v-theme-success)); background: rgba(var(--v-theme-success), 0.13); }
.metric-icon--warning { color: rgb(var(--v-theme-warning)); background: rgba(var(--v-theme-warning), 0.14); }
.quick-icon--error { color: rgb(var(--v-theme-error)); background: rgba(var(--v-theme-error), 0.12); }
.metric-copy { min-width: 0; }
.metric-copy strong, .metric-copy small { display: block; letter-spacing: 0; }
.metric-copy strong { font-size: 1.5rem; font-weight: 700; line-height: 1.2; }
.metric-copy small { margin-top: 0.25rem; color: rgba(var(--v-theme-on-surface), var(--v-medium-emphasis-opacity)); font-size: 0.75rem; }
.metric-chevron { color: rgba(var(--v-theme-on-surface), 0.28); }
.overview-layout { display: grid; grid-template-columns: minmax(0, 1.55fr) minmax(18rem, 0.85fr); align-items: start; gap: 1rem; margin-top: 1rem; }
.overview-side { display: grid; min-width: 0; gap: 1rem; }
.dashboard-panel { min-width: 0; overflow: hidden; border: 1px solid rgba(var(--v-border-color), 0.08); border-radius: 0.5rem; background: rgb(var(--v-theme-surface)); box-shadow: 0 0.25rem 1.125rem rgba(30, 26, 48, 0.07); }
.panel-header { display: flex; min-height: 4.25rem; align-items: center; justify-content: space-between; gap: 1rem; padding: 0.875rem 1rem; border-bottom: 1px solid rgba(var(--v-border-color), var(--v-border-opacity)); }
.panel-header h2 { margin: 0; font-size: 0.9375rem; font-weight: 650; letter-spacing: 0; }
.panel-header span { display: block; margin-top: 0.125rem; color: rgba(var(--v-theme-on-surface), var(--v-medium-emphasis-opacity)); font-size: 0.7rem; }
.recent-list { display: grid; }
.recent-item { display: grid; min-width: 0; min-height: 4.75rem; grid-template-columns: auto minmax(0, 1fr) auto; align-items: center; gap: 0.75rem; padding: 0.625rem 1rem; border: 0; border-bottom: 1px solid rgba(var(--v-border-color), var(--v-border-opacity)); color: inherit; text-align: start; background: transparent; cursor: pointer; font: inherit; }
.recent-item:hover, .quick-actions button:hover, .source-mini-list button:hover { background: rgba(var(--v-theme-primary), 0.045); }
.recent-media-icon { width: 2.25rem; height: 2.25rem; color: rgb(var(--v-theme-primary)); background: rgba(var(--v-theme-primary), 0.1); }
.recent-copy, .recent-status { min-width: 0; }
.recent-copy strong, .recent-copy small, .recent-status small { display: block; letter-spacing: 0; }
.recent-copy strong { overflow: hidden; font-size: 0.8125rem; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
.recent-copy small, .recent-status small { margin-top: 0.25rem; overflow: hidden; color: rgba(var(--v-theme-on-surface), var(--v-medium-emphasis-opacity)); font-size: 0.6875rem; text-overflow: ellipsis; white-space: nowrap; }
.recent-status { min-width: 7.5rem; text-align: end; }
.recent-status :deep(.v-chip) { margin-inline-start: auto; }
.panel-footer { display: flex; min-height: 3.25rem; align-items: center; justify-content: center; }
.panel-empty { display: grid; min-height: 15rem; place-items: center; align-content: center; gap: 0.5rem; color: rgba(var(--v-theme-on-surface), var(--v-medium-emphasis-opacity)); font-size: 0.8125rem; }
.panel-empty--compact { min-height: 7rem; }
.quick-actions, .source-mini-list { display: grid; }
.quick-actions button { display: grid; min-width: 0; min-height: 4.5rem; grid-template-columns: auto minmax(0, 1fr) auto; align-items: center; gap: 0.75rem; padding: 0.625rem 1rem; border: 0; border-bottom: 1px solid rgba(var(--v-border-color), var(--v-border-opacity)); color: inherit; text-align: start; background: transparent; cursor: pointer; font: inherit; }
.quick-actions button:last-child { border-bottom: 0; }
.quick-actions button:disabled { cursor: wait; opacity: 0.62; }
.quick-icon { width: 2.25rem; height: 2.25rem; }
.quick-actions strong, .quick-actions small { display: block; letter-spacing: 0; }
.quick-actions strong { font-size: 0.8125rem; font-weight: 600; }
.quick-actions small { margin-top: 0.125rem; color: rgba(var(--v-theme-on-surface), var(--v-medium-emphasis-opacity)); font-size: 0.6875rem; }
.quick-actions button > :last-child { color: rgba(var(--v-theme-on-surface), 0.3); }
.source-mini-list button { display: grid; min-height: 2.75rem; grid-template-columns: auto minmax(0, 1fr) auto; align-items: center; gap: 0.625rem; padding: 0.5rem 1rem; border: 0; color: inherit; text-align: start; background: transparent; cursor: pointer; font: inherit; }
.source-mini-list strong { overflow: hidden; font-size: 0.75rem; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
.source-mini-list button > span:last-child { color: rgba(var(--v-theme-on-surface), var(--v-medium-emphasis-opacity)); font-size: 0.6875rem; }
.source-dot { width: 0.5rem; height: 0.5rem; border-radius: 50%; background: rgba(var(--v-theme-on-surface), 0.24); }
.source-dot--healthy { background: rgb(var(--v-theme-success)); }
.source-dot--limited { background: rgb(var(--v-theme-warning)); }
.source-dot--error { background: rgb(var(--v-theme-error)); }
.source-dot--pending { background: rgb(var(--v-theme-info)); }
@media (max-width: 74rem) { .metric-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } .overview-layout { grid-template-columns: minmax(0, 1.35fr) minmax(17rem, 0.8fr); } }
@media (max-width: 959px) { .overview-layout { grid-template-columns: 1fr; } .overview-side { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 40rem) { .metric-grid, .overview-side { grid-template-columns: 1fr; } .metric-card { min-height: 5.75rem; } .recent-status { min-width: 0; } .recent-status small { display: none; } }
@media (max-width: 30rem) { .recent-item { grid-template-columns: auto minmax(0, 1fr); } .recent-status { display: flex; grid-column: 2; justify-content: flex-start; } .recent-status :deep(.v-chip) { margin-inline-start: 0; } .inline-alert { align-items: flex-start; flex-direction: column; } }
@media (prefers-reduced-motion: reduce) { .metric-card { transition: none; } }
</style>
