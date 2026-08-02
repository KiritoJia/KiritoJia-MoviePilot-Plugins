<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useDisplay } from 'vuetify'

import { clearTerminalTasks, deleteTask, deleteTasksBatch, getErrorMessage, getTask, listTasks, retryTask, retryTasksBatch, scanCustomDirectories } from '@/api/client'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import CopyValue from '@/components/CopyValue.vue'
import DetailDrawer from '@/components/DetailDrawer.vue'
import DetailRow from '@/components/DetailRow.vue'
import EmptyState from '@/components/EmptyState.vue'
import StateChip from '@/components/StateChip.vue'
import { useDebouncedValue } from '@/composables/useDebouncedValue'
import type { PluginApi, SourceRun, TaskDetail, TaskListItem, TaskStatus } from '@/types'
import {
  attemptLabels,
  attributionStrategyLabels,
  displayValue,
  elapsedDuration,
  formatDate,
  formatDuration,
  friendlyKey,
  isTerminalTask,
  mediaLabel,
  mediaTypeLabels,
  packageLabels,
  sourceLabels,
  sourceRunLabels,
  stageLabels,
  taskStates,
  taskTriggerLabels,
  translationLabels,
} from '@/types/presentation'

const props = defineProps<{
  api: PluginApi
  pluginId: string
  active: boolean
}>()

const emit = defineEmits<{ action: [] }>()
const { mdAndUp } = useDisplay()

const statusOptions: Array<{ title: string; value: TaskStatus | '' }> = [
  { title: '全部状态', value: '' },
  { title: '等待中', value: 'queued' },
  { title: '处理中', value: 'processing' },
  { title: '成功', value: 'success' },
  { title: '跳过', value: 'skipped' },
  { title: '失败', value: 'failed' },
  { title: '已中断', value: 'interrupted' },
]
const retryableStatuses: TaskStatus[] = ['skipped', 'failed', 'interrupted']
const terminalStatuses: TaskStatus[] = ['success', 'skipped', 'failed', 'interrupted']
const pageSizeOptions = [25, 50, 100]

const items = ref<TaskListItem[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref<25 | 50 | 100>(25)
const searchInput = ref('')
const search = useDebouncedValue(searchInput)
const status = ref<TaskStatus | ''>('')
const statusCounts = ref<Partial<Record<TaskStatus, number>>>({})
const loading = ref(false)
const refreshing = ref(false)
const loaded = ref(false)
const error = ref('')
const staleError = ref('')
const selectedId = ref('')
const detail = ref<TaskDetail | null>(null)
const detailLoading = ref(false)
const detailError = ref('')
const openDetailPanels = ref<number[]>([0, 1])
const deleteOpen = ref(false)
const deleting = ref(false)
const deleteTarget = ref<TaskListItem | null>(null)
const retryOpen = ref(false)
const retrying = ref(false)
const retryTarget = ref<TaskListItem | null>(null)
const selectedTaskIds = ref<Set<string>>(new Set())
const batchRetryOpen = ref(false)
const batchRetrying = ref(false)
const batchRetryScope = ref<'selected' | 'group'>('selected')
const batchDeleteOpen = ref(false)
const batchDeleting = ref(false)
const batchDeleteScope = ref<'selected' | 'group'>('selected')
const clearTasksOpen = ref(false)
const clearingTasks = ref(false)
const scanOpen = ref(false)
const scanMode = ref<'incremental' | 'full'>('incremental')
const scanning = ref(false)
const scanNotice = ref('')
const scanNoticeType = ref<'success' | 'warning'>('success')
const taskNotice = ref('')
const pageVisible = ref(typeof document === 'undefined' || !document.hidden)
const tableFrame = ref<HTMLElement | null>(null)
let listRequest = 0
let detailRequest = 0
let detailRefreshInFlight = false
let pollTimer: ReturnType<typeof setInterval> | undefined

const isDesktop = computed(() => mdAndUp.value)
const hasFilters = computed(() => Boolean(search.value || status.value))
const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize.value)))
const canLoadMore = computed(() => !isDesktop.value && items.value.length < total.value)
const selectedListItem = computed(() => items.value.find(item => item.id === selectedId.value) || detail.value || deleteTarget.value || retryTarget.value)
const pageTerminalItems = computed(() => items.value.filter(item => isTerminalTask(item.status)))
const selectedItems = computed(() => items.value.filter(item => selectedTaskIds.value.has(item.id)))
const selectedRetryableItems = computed(() => selectedItems.value.filter(item => canRetryTask(item)))
const selectedTaskCount = computed(() => selectedTaskIds.value.size)
const selectedRetryableCount = computed(() => selectedRetryableItems.value.length)
const allPageTerminalSelected = computed(() => (
  pageTerminalItems.value.length > 0
  && pageTerminalItems.value.every(item => selectedTaskIds.value.has(item.id))
))
const somePageTerminalSelected = computed(() => (
  pageTerminalItems.value.some(item => selectedTaskIds.value.has(item.id))
  && !allPageTerminalSelected.value
))
const allTaskCount = computed(() => Object.values(statusCounts.value).reduce((sum, count) => sum + (count || 0), 0))
const currentGroupCount = computed(() => status.value ? (statusCounts.value[status.value] || 0) : allTaskCount.value)
const currentGroupTitle = computed(() => status.value ? taskStates[status.value].label : '全部任务')
const currentGroupRetryable = computed(() => status.value !== '' && retryableStatuses.includes(status.value))
const currentGroupTerminal = computed(() => status.value !== '' && terminalStatuses.includes(status.value))
const batchRetryMessage = computed(() => {
  if (batchRetryScope.value === 'selected') {
    return `将让选中的 ${selectedRetryableCount.value} 条可重试任务回到等待队列并重新开始。原运行轨迹会重置，媒体信息、目标路径和任务 ID 保留。`
  }
  const scope = search.value ? `搜索“${search.value}”命中的` : '当前'
  return `将重新运行${scope} ${currentGroupCount.value} 条${currentGroupTitle.value}。任务会按现有并发上限排队执行，不会同时请求全部字幕源；原运行轨迹会重置。`
})
const batchDeleteMessage = computed(() => {
  if (batchDeleteScope.value === 'selected') {
    return `将删除选中的 ${selectedTaskCount.value} 条终态任务记录。字幕文件、字幕匹配记录和媒体文件不会被删除。此操作无法撤销。`
  }
  const scope = search.value ? `搜索“${search.value}”命中的` : '当前'
  return `将删除${scope} ${currentGroupCount.value} 条${currentGroupTitle.value}记录。字幕文件、字幕匹配记录和媒体文件不会被删除。此操作无法撤销。`
})

watch(
  () => props.active,
  active => {
    if (!active) {
      stopPolling()
      return
    }
    void loadPage({ silent: loaded.value, requestedPage: isDesktop.value ? page.value : 1 })
    syncPolling()
  },
  { immediate: true },
)

watch([search, status], () => {
  clearTaskSelection()
  scrollTableToTop()
  page.value = 1
  items.value = []
  if (props.active) void loadPage({ requestedPage: 1 })
})

watch(pageSize, () => {
  if (!isDesktop.value) return
  clearTaskSelection()
  scrollTableToTop()
  page.value = 1
  if (props.active) void loadPage({ requestedPage: 1 })
})

watch(page, next => {
  if (!isDesktop.value || !props.active) return
  clearTaskSelection()
  scrollTableToTop()
  void loadPage({ requestedPage: next })
})

watch(isDesktop, () => {
  clearTaskSelection()
  page.value = 1
  items.value = []
  if (props.active) void loadPage({ requestedPage: 1 })
})

function scrollTableToTop(): void {
  const wrapper = tableFrame.value?.querySelector<HTMLElement>('.v-table__wrapper')
  if (wrapper) wrapper.scrollTop = 0
}

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
  pollTimer = window.setInterval(() => {
    void loadPage({ silent: true, requestedPage: isDesktop.value ? page.value : 1 })
  }, 3000)
}

function handleVisibilityChange(): void {
  pageVisible.value = !document.hidden
  syncPolling()
  if (props.active && pageVisible.value) {
    void loadPage({ silent: true, requestedPage: isDesktop.value ? page.value : 1 })
  }
}

async function loadPage(options: { silent?: boolean; append?: boolean; requestedPage?: number } = {}): Promise<void> {
  const requestId = ++listRequest
  const requestedPage = options.requestedPage ?? page.value
  if (!options.silent) {
    if (!loaded.value || !items.value.length) loading.value = true
    else refreshing.value = true
    error.value = ''
  }
  try {
    const response = await listTasks(props.api, props.pluginId, {
      page: requestedPage,
      pageSize: isDesktop.value ? pageSize.value : 25,
      search: search.value,
      status: status.value,
    })
    if (requestId !== listRequest) return

    if (options.append) {
      const known = new Set(items.value.map(item => item.id))
      items.value = [...items.value, ...response.items.filter(item => !known.has(item.id))]
      page.value = requestedPage
    } else if (options.silent && !isDesktop.value && page.value > 1) {
      const freshIds = new Set(response.items.map(item => item.id))
      items.value = [...response.items, ...items.value.filter(item => !freshIds.has(item.id))].slice(0, total.value || undefined)
    } else {
      items.value = response.items
      if (!isDesktop.value) page.value = requestedPage
    }
    total.value = response.total
    statusCounts.value = response.status_counts || {}
    loaded.value = true
    error.value = ''
    staleError.value = ''
    if (options.silent && selectedId.value) void refreshOpenDetail()
  } catch (requestError) {
    if (requestId !== listRequest) return
    const message = getErrorMessage(requestError, '任务列表加载失败')
    if (loaded.value && items.value.length) staleError.value = message
    else error.value = message
  } finally {
    if (requestId === listRequest) {
      loading.value = false
      refreshing.value = false
    }
  }
}

async function loadMore(): Promise<void> {
  if (!canLoadMore.value || refreshing.value) return
  refreshing.value = true
  await loadPage({ append: true, requestedPage: page.value + 1 })
  refreshing.value = false
}

async function openDetail(item: TaskListItem): Promise<void> {
  selectedId.value = item.id
  detail.value = null
  detailError.value = ''
  openDetailPanels.value = [0, 1]
  detailLoading.value = true
  const requestId = ++detailRequest
  try {
    const response = await getTask(props.api, props.pluginId, item.id)
    if (requestId === detailRequest && selectedId.value === item.id) detail.value = response
  } catch (requestError) {
    if (requestId === detailRequest) detailError.value = getErrorMessage(requestError, '任务详情加载失败')
  } finally {
    if (requestId === detailRequest) detailLoading.value = false
  }
}

async function refreshOpenDetail(): Promise<void> {
  const taskId = selectedId.value
  if (!taskId || detailLoading.value || detailRefreshInFlight) return
  detailRefreshInFlight = true
  const requestId = ++detailRequest
  try {
    const response = await getTask(props.api, props.pluginId, taskId)
    if (requestId === detailRequest && selectedId.value === taskId) detail.value = response
  } catch (requestError) {
    if (requestId === detailRequest) {
      staleError.value = `任务详情刷新失败：${getErrorMessage(requestError, '无法读取最新任务详情')}`
    }
  } finally {
    detailRefreshInFlight = false
  }
}

function closeDetail(): void {
  selectedId.value = ''
  detail.value = null
  detailError.value = ''
  detailRequest += 1
}

function updateDetailOpen(open: boolean): void {
  if (!open) closeDetail()
}

function requestDelete(item: TaskListItem): void {
  if (!isTerminalTask(item.status)) return
  deleteTarget.value = item
  deleteOpen.value = true
}

function canRetryTask(item: TaskListItem): boolean {
  return retryableStatuses.includes(item.status)
}

function requestRetry(item: TaskListItem): void {
  if (!canRetryTask(item)) return
  retryTarget.value = item
  retryOpen.value = true
}

function clearTaskSelection(): void {
  selectedTaskIds.value = new Set()
}

function setTaskSelected(taskId: string, selected: boolean): void {
  const next = new Set(selectedTaskIds.value)
  if (selected) next.add(taskId)
  else next.delete(taskId)
  selectedTaskIds.value = next
}

function togglePageTerminal(selected: boolean): void {
  const next = new Set(selectedTaskIds.value)
  for (const item of pageTerminalItems.value) {
    if (selected) next.add(item.id)
    else next.delete(item.id)
  }
  selectedTaskIds.value = next
}

function requestBatchRetry(scope: 'selected' | 'group'): void {
  if (scope === 'selected' && !selectedRetryableCount.value) return
  if (scope === 'group' && (!currentGroupRetryable.value || !currentGroupCount.value)) return
  batchRetryScope.value = scope
  batchRetryOpen.value = true
}

function requestBatchDelete(scope: 'selected' | 'group'): void {
  if (scope === 'selected' && !selectedTaskCount.value) return
  if (scope === 'group' && (!currentGroupTerminal.value || !currentGroupCount.value)) return
  batchDeleteScope.value = scope
  batchDeleteOpen.value = true
}

async function confirmBatchRetry(): Promise<void> {
  const scope = batchRetryScope.value
  const taskIds = selectedRetryableItems.value.map(item => item.id)
  if (scope === 'selected' && !taskIds.length) return
  batchRetrying.value = true
  taskNotice.value = ''
  try {
    const response = await retryTasksBatch(props.api, props.pluginId, scope === 'selected'
      ? { taskIds }
      : { allMatching: true, statuses: status.value ? [status.value] : [], search: search.value })
    batchRetryOpen.value = false
    clearTaskSelection()
    page.value = 1
    await loadPage({ silent: true, requestedPage: 1 })
    taskNotice.value = response.message
    emit('action')
  } catch (requestError) {
    batchRetryOpen.value = false
    staleError.value = getErrorMessage(requestError, '批量恢复任务失败')
  } finally {
    batchRetrying.value = false
  }
}

async function confirmBatchDelete(): Promise<void> {
  const scope = batchDeleteScope.value
  const taskIds = [...selectedTaskIds.value]
  if (scope === 'selected' && !taskIds.length) return
  batchDeleting.value = true
  taskNotice.value = ''
  try {
    const response = await deleteTasksBatch(props.api, props.pluginId, scope === 'selected'
      ? { taskIds }
      : { allMatching: true, statuses: status.value ? [status.value] : [], search: search.value })
    batchDeleteOpen.value = false
    if (
      selectedListItem.value
      && (
        (scope === 'selected' && taskIds.includes(selectedListItem.value.id))
        || (scope === 'group' && selectedListItem.value.status === status.value)
      )
    ) closeDetail()
    clearTaskSelection()
    page.value = 1
    await loadPage({ silent: true, requestedPage: 1 })
    taskNotice.value = response.message
    emit('action')
  } catch (requestError) {
    batchDeleteOpen.value = false
    staleError.value = getErrorMessage(requestError, '批量删除任务失败')
  } finally {
    batchDeleting.value = false
  }
}

async function confirmRetryTask(): Promise<void> {
  const target = retryTarget.value
  if (!target) return
  retrying.value = true
  taskNotice.value = ''
  try {
    const response = await retryTask(props.api, props.pluginId, target.id)
    retryOpen.value = false
    retryTarget.value = null
    if (selectedId.value === target.id) closeDetail()
    page.value = 1
    await loadPage({ silent: true, requestedPage: 1 })
    taskNotice.value = response.message || '任务已重新提交'
    emit('action')
  } catch (requestError) {
    retryOpen.value = false
    staleError.value = getErrorMessage(requestError, '任务重新运行失败')
  } finally {
    retrying.value = false
  }
}

async function confirmDelete(): Promise<void> {
  const target = deleteTarget.value
  if (!target) return
  deleting.value = true
  try {
    await deleteTask(props.api, props.pluginId, target.id)
    deleteOpen.value = false
    deleteTarget.value = null
    if (selectedId.value === target.id) closeDetail()
    if (isDesktop.value && items.value.length === 1 && page.value > 1) page.value -= 1
    else await loadPage({ silent: true, requestedPage: isDesktop.value ? page.value : 1 })
    emit('action')
  } catch (requestError) {
    staleError.value = getErrorMessage(requestError, '任务记录删除失败')
    deleteOpen.value = false
  } finally {
    deleting.value = false
  }
}

async function confirmClearTasks(): Promise<void> {
  clearingTasks.value = true
  taskNotice.value = ''
  try {
    const response = await clearTerminalTasks(props.api, props.pluginId)
    clearTasksOpen.value = false
    if (selectedListItem.value && isTerminalTask(selectedListItem.value.status)) closeDetail()
    page.value = 1
    items.value = []
    await loadPage({ silent: true, requestedPage: 1 })
    taskNotice.value = response.active_count
      ? `${response.message}，保留 ${response.active_count} 条运行中任务`
      : response.message
    emit('action')
  } catch (requestError) {
    clearTasksOpen.value = false
    staleError.value = getErrorMessage(requestError, '任务列表清理失败')
  } finally {
    clearingTasks.value = false
  }
}

async function confirmDirectoryScan(): Promise<void> {
  scanning.value = true
  scanNotice.value = ''
  try {
    const full = scanMode.value === 'full'
    const response = await scanCustomDirectories(props.api, props.pluginId, { full })
    scanOpen.value = false
    scanNoticeType.value = response.fallback_file_count > 0 ? 'warning' : 'success'
    scanNotice.value = [
      response.message,
      `目录文件 ${response.indexed_file_count} 个`,
      full ? `全量目标 ${response.changed_count} 个` : `未变更已跳过 ${response.unchanged_count} 个`,
      `本次处理 ${response.matched_count} 个`,
      response.retry_count ? `重试失败项 ${response.retry_count} 个` : '',
      `整理历史匹配 ${response.history_matched_count} 个`,
      `MoviePilot 识别 ${response.recognized_file_count} 个`,
      response.fallback_file_count ? `路径解析兜底 ${response.fallback_file_count} 个` : '',
    ].filter(Boolean).join('；')
    page.value = 1
    await loadPage({ silent: true, requestedPage: 1 })
    emit('action')
  } catch (requestError) {
    scanOpen.value = false
    staleError.value = getErrorMessage(requestError, '自定义目录扫描失败')
  } finally {
    scanning.value = false
  }
}

function requestDirectoryScan(mode: 'incremental' | 'full'): void {
  scanMode.value = mode
  scanOpen.value = true
}

function clearFilters(): void {
  searchInput.value = ''
  status.value = ''
}

function resultText(item: TaskListItem): string {
  if (item.status === 'success') {
    return [
      item.result_source ? sourceLabels[item.result_source] : '',
      item.result_package_scope ? packageLabels[item.result_package_scope] : '',
      item.result_format || '',
    ].filter(Boolean).join(' · ') || '字幕已落盘'
  }
  if (item.status === 'queued') return '等待处理'
  if (item.status === 'processing') return item.stage ? stageLabels[item.stage] : '正在处理'
  return item.reason_message || item.reason_code || '未记录原因'
}

function taskTime(item: TaskListItem): string {
  const start = item.started_at || item.created_at
  const duration = item.status === 'processing' ? elapsedDuration(item.started_at) : formatDuration(item.duration_ms)
  return `${formatDate(start)} · ${duration}`
}

function detailEntries(value: Record<string, unknown>): Array<[string, unknown]> {
  return Object.entries(value || {})
}

type SourceRunMetric = 'raw_count' | 'admitted_count' | 'media_matched_count' | 'rejected_count'

function sourceRunMetric(run: SourceRun, key: SourceRunMetric): number | null {
  const value = run[key]
  if (typeof value === 'number') return value
  const detailValue = run.details?.[key]
  return typeof detailValue === 'number' ? detailValue : null
}

function hasSourceRunFunnel(run: SourceRun): boolean {
  return ['raw_count', 'admitted_count', 'media_matched_count'].some(
    key => sourceRunMetric(run, key as SourceRunMetric) !== null,
  )
}

function isSkippedSourceRun(run: SourceRun): boolean {
  return run.status === 'disabled' || run.status === 'unconfigured'
}

function sourceRunFunnel(run: SourceRun): string {
  const rawCount = sourceRunMetric(run, 'raw_count') ?? 0
  const admittedCount = sourceRunMetric(run, 'admitted_count') ?? 0
  const matchedCount = sourceRunMetric(run, 'media_matched_count') ?? 0
  return `来源返回 ${rawCount} → 自动规则保留 ${admittedCount} → 当前目标匹配 ${matchedCount}`
}

function sourceRunContext(run: SourceRun): string {
  if (isSkippedSourceRun(run)) return ''
  const details = run.details || {}
  const parts: string[] = []
  if (details.cache_hit === true) {
    parts.push(details.cache_stored_at ? `复用 ${formatDate(String(details.cache_stored_at))} 的缓存` : '复用缓存')
  } else if (details.cache_hit === false) {
    parts.push('实际查询字幕源')
  }
  const pageCount = typeof details.page_count === 'number' ? details.page_count : null
  if (pageCount && pageCount > 1) parts.push(`读取 ${pageCount} 页`)
  if (details.pagination_complete === false) parts.push('分页结果不完整')
  if (typeof details.query === 'string' && details.query) parts.push(`查询“${details.query}”`)
  return parts.join(' · ')
}

function sourceRunRejectionSummary(run: SourceRun): string {
  const summary = run.rejection_summary ?? run.details?.rejection_summary
  if (!summary || typeof summary !== 'object' || Array.isArray(summary)) return ''
  return Object.entries(summary)
    .filter((entry): entry is [string, number] => typeof entry[1] === 'number' && entry[1] > 0)
    .map(([reason, count]) => `${friendlyKey(reason)} ${count}`)
    .join(' · ')
}
</script>

<template>
  <section class="view-shell" aria-labelledby="tasks-view-title">
    <div class="view-controls">
      <header class="view-header">
        <div>
          <h2 id="tasks-view-title">任务</h2>
        </div>
        <div class="header-actions">
          <VTooltip text="清理全部已结束任务">
            <template #activator="{ props: tooltipProps }">
              <VBtn
                v-bind="tooltipProps"
                icon="mdi-delete-sweep-outline"
                size="small"
                variant="text"
                color="error"
                :disabled="loading || clearingTasks"
                :loading="clearingTasks"
                aria-label="清理全部已结束任务"
                @click="clearTasksOpen = true"
              />
            </template>
          </VTooltip>
          <VMenu>
            <template #activator="{ props: menuProps }">
              <VBtn
                v-bind="menuProps"
                color="primary"
                variant="tonal"
                size="small"
                prepend-icon="mdi-folder-search-outline"
                append-icon="mdi-chevron-down"
                :loading="scanning"
              >扫描目录</VBtn>
            </template>
            <VList density="compact" min-width="250">
              <VListItem
                title="增量扫描"
                subtitle="仅处理新增、变更和失败项"
                prepend-icon="mdi-folder-search-outline"
                @click="requestDirectoryScan('incremental')"
              />
              <VListItem
                title="重新扫描全部"
                subtitle="忽略历史索引，重新处理全部文件"
                prepend-icon="mdi-database-refresh-outline"
                base-color="warning"
                @click="requestDirectoryScan('full')"
              />
            </VList>
          </VMenu>
          <VTooltip text="刷新任务">
            <template #activator="{ props: tooltipProps }">
              <VBtn
                v-bind="tooltipProps"
                icon="mdi-refresh"
                size="small"
                variant="text"
                :loading="refreshing"
                aria-label="刷新任务"
                @click="loadPage({ silent: loaded, requestedPage: isDesktop ? page : 1 })"
              />
            </template>
          </VTooltip>
        </div>
      </header>

      <div class="filter-bar">
        <VTextField
          v-model="searchInput"
          label="搜索任务"
          placeholder="媒体、目标文件或原因"
          prepend-inner-icon="mdi-magnify"
          clearable
          hide-details
          :density="isDesktop ? 'compact' : 'comfortable'"
        />
        <VSelect v-if="!isDesktop" v-model="status" label="状态分组" :items="statusOptions" hide-details density="comfortable" />
      </div>

      <div class="status-group-toolbar">
        <div v-if="isDesktop" class="status-segments" aria-label="任务状态分组">
          <VBtnToggle v-model="status" mandatory divided density="compact" color="primary" variant="outlined">
            <VBtn v-for="option in statusOptions" :key="option.value || 'all'" :value="option.value" size="small">
              <span>{{ option.title.replace('全部状态', '全部') }}</span>
              <span class="status-segment-count">{{ option.value ? (statusCounts[option.value] || 0) : allTaskCount }}</span>
            </VBtn>
          </VBtnToggle>
        </div>
        <div class="status-group-summary">
          <span>{{ currentGroupTitle }} · {{ currentGroupCount }} 条</span>
          <VBtn
            v-if="currentGroupRetryable"
            size="small"
            variant="text"
            color="primary"
            prepend-icon="mdi-restart"
            :disabled="!currentGroupCount || batchRetrying"
            :loading="batchRetrying"
            @click="requestBatchRetry('group')"
          >重启此分组</VBtn>
          <VBtn
            v-if="currentGroupTerminal"
            size="small"
            variant="text"
            color="error"
            prepend-icon="mdi-delete-outline"
            :disabled="!currentGroupCount || batchDeleting"
            :loading="batchDeleting"
            @click="requestBatchDelete('group')"
          >删除此分组</VBtn>
        </div>
      </div>
    </div>

    <div v-if="isDesktop && selectedTaskCount" class="batch-action-bar" role="status">
      <div class="batch-action-bar__summary">
        <VIcon icon="mdi-checkbox-marked-circle-outline" size="19" color="primary" />
        <span>已选择 {{ selectedTaskCount }} 条终态任务</span>
      </div>
      <div class="batch-action-bar__actions">
        <VBtn size="small" variant="text" color="default" @click="clearTaskSelection">取消选择</VBtn>
        <VBtn
          v-if="selectedRetryableCount"
          size="small"
          variant="tonal"
          color="primary"
          prepend-icon="mdi-restart"
          :loading="batchRetrying"
          @click="requestBatchRetry('selected')"
        >重启可重试（{{ selectedRetryableCount }}）</VBtn>
        <VBtn
          size="small"
          variant="flat"
          color="error"
          prepend-icon="mdi-delete-outline"
          :loading="batchDeleting"
          @click="requestBatchDelete('selected')"
        >删除选中</VBtn>
      </div>
    </div>

    <VAlert v-if="staleError" type="warning" variant="tonal" density="compact" class="notice-alert mb-3">
      <div class="inline-alert">
        <span>刷新失败，当前数据可能已过期：{{ staleError }}</span>
        <VBtn size="small" variant="text" prepend-icon="mdi-refresh" @click="loadPage({ silent: true })">重试</VBtn>
      </div>
    </VAlert>

    <VAlert
      v-if="scanNotice"
      :type="scanNoticeType"
      variant="tonal"
      density="compact"
      closable
      class="notice-alert mb-3"
      @click:close="scanNotice = ''"
    >{{ scanNotice }}</VAlert>

    <VAlert
      v-if="taskNotice"
      type="success"
      variant="tonal"
      density="compact"
      closable
      class="notice-alert mb-3"
      @click:close="taskNotice = ''"
    >{{ taskNotice }}</VAlert>

    <div v-if="loading" class="table-frame" aria-label="正在加载任务">
      <VSkeletonLoader :type="isDesktop ? 'table-heading, table-row-divider@7' : 'list-item-two-line@6'" />
    </div>

    <VAlert v-else-if="error" type="error" variant="tonal" class="mt-3" title="任务加载失败">
      <div>{{ error }}</div>
      <VBtn class="mt-2" size="small" variant="text" prepend-icon="mdi-refresh" @click="loadPage()">重试</VBtn>
    </VAlert>

    <EmptyState
      v-else-if="!items.length && !hasFilters && !selectedId"
      icon="mdi-subtitles-outline"
      title="还没有字幕任务"
      message="新整理媒体会自动生成任务，也可以扫描已配置目录中的现有视频和 STRM 文件。"
    />

    <EmptyState
      v-else-if="!items.length && !selectedId"
      icon="mdi-filter-off-outline"
      title="没有符合条件的任务"
      message="调整搜索内容或状态筛选后再试。"
    >
      <template #actions>
        <VBtn variant="tonal" prepend-icon="mdi-filter-remove-outline" @click="clearFilters">清除条件</VBtn>
      </template>
    </EmptyState>

    <div v-else class="master-detail">
      <div class="master-pane">
        <div v-if="isDesktop" ref="tableFrame" class="table-frame">
          <VTable hover fixed-header height="100%" class="data-table">
            <thead>
              <tr>
                <th class="selection-column" @click.stop>
                  <VCheckboxBtn
                    :model-value="allPageTerminalSelected"
                    :indeterminate="somePageTerminalSelected"
                    :disabled="!pageTerminalItems.length"
                    density="compact"
                    color="primary"
                    aria-label="选择本页全部终态任务"
                    @update:model-value="value => togglePageTerminal(Boolean(value))"
                  />
                </th>
                <th class="media-column">媒体</th>
                <th class="file-column">目标文件</th>
                <th class="status-column">状态</th>
                <th class="trigger-column">触发</th>
                <th class="result-column">结果</th>
                <th class="time-column">时间</th>
                <th class="actions-column">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="item in items"
                :key="item.id"
                class="selectable-row"
                :class="{ 'selectable-row--active': selectedId === item.id }"
                tabindex="0"
                role="button"
                :data-subtitle-download-detail-trigger="`task:${item.id}`"
                :aria-label="`查看任务 ${mediaLabel(item.media_title, item.year, item.season, item.episode)}`"
                @click="openDetail(item)"
                @keydown.enter.prevent="openDetail(item)"
                @keydown.space.prevent="openDetail(item)"
              >
                <td class="selection-column" @click.stop @keydown.stop>
                  <VCheckboxBtn
                    :model-value="selectedTaskIds.has(item.id)"
                    :disabled="!isTerminalTask(item.status)"
                    density="compact"
                    color="primary"
                    :aria-label="`选择任务 ${item.target_file_name}`"
                    @update:model-value="value => setTaskSelected(item.id, Boolean(value))"
                  />
                </td>
                <td class="media-column">
                  <div class="primary-cell">
                    <VIcon :icon="item.media_type === 'movie' ? 'mdi-movie-outline' : 'mdi-television-classic'" size="18" />
                    <div>
                      <strong>{{ item.media_title }}</strong>
                      <span>{{ [mediaTypeLabels[item.media_type], item.year, item.season != null ? `S${String(item.season).padStart(2, '0')}` : '', item.episode != null ? `E${String(item.episode).padStart(2, '0')}` : ''].filter(Boolean).join(' · ') }}</span>
                    </div>
                  </div>
                </td>
                <td class="file-column"><span class="file-name" :title="item.target_file_name">{{ item.target_file_name }}</span></td>
                <td class="status-column">
                  <StateChip :state="taskStates[item.status]" />
                  <div v-if="item.status === 'processing' && item.stage" class="cell-note">{{ stageLabels[item.stage] }}</div>
                </td>
                <td class="trigger-column"><span class="cell-note">{{ taskTriggerLabels[item.trigger] }}</span></td>
                <td class="result-column"><span class="result-text">{{ resultText(item) }}</span></td>
                <td class="time-column"><span class="time-text">{{ taskTime(item) }}</span></td>
                <td class="actions-column" @click.stop @keydown.stop>
                  <VTooltip text="查看详情">
                    <template #activator="{ props: tooltipProps }">
                      <VBtn v-bind="tooltipProps" icon="mdi-chevron-right" size="small" variant="text" aria-label="查看任务详情" @click="openDetail(item)" />
                    </template>
                  </VTooltip>
                  <VTooltip v-if="canRetryTask(item)" text="重新运行任务">
                    <template #activator="{ props: tooltipProps }">
                      <VBtn v-bind="tooltipProps" icon="mdi-restart" size="small" variant="text" color="primary" aria-label="重新运行任务" @click="requestRetry(item)" />
                    </template>
                  </VTooltip>
                  <VTooltip v-if="isTerminalTask(item.status)" text="删除任务记录">
                    <template #activator="{ props: tooltipProps }">
                      <VBtn v-bind="tooltipProps" icon="mdi-delete-outline" size="small" variant="text" color="error" aria-label="删除任务记录" @click="requestDelete(item)" />
                    </template>
                  </VTooltip>
                </td>
              </tr>
            </tbody>
          </VTable>
        </div>

        <VList v-else class="mobile-list" lines="three" role="list" aria-label="任务列表">
          <VListItem
            v-for="item in items"
            :key="item.id"
            class="mobile-list__item"
            role="listitem"
          >
            <template #prepend>
              <VIcon :icon="item.media_type === 'movie' ? 'mdi-movie-outline' : 'mdi-television-classic'" />
            </template>
            <button
              type="button"
              class="mobile-list__detail"
              :data-subtitle-download-detail-trigger="`task:${item.id}`"
              :aria-label="`查看任务 ${mediaLabel(item.media_title, item.year, item.season, item.episode)}`"
              @click="openDetail(item)"
            >
              <VListItemTitle>{{ mediaLabel(item.media_title, item.year, item.season, item.episode) }}</VListItemTitle>
              <VListItemSubtitle class="mobile-subtitle">{{ item.target_file_name }}</VListItemSubtitle>
              <VListItemSubtitle class="mobile-meta">
                <StateChip :state="taskStates[item.status]" size="x-small" />
                <span>{{ item.status === 'processing' && item.stage ? stageLabels[item.stage] : formatDate(item.started_at || item.created_at) }}</span>
              </VListItemSubtitle>
            </button>
            <template #append>
              <VMenu v-if="isTerminalTask(item.status)">
                <template #activator="{ props: menuProps }">
                  <VBtn v-bind="menuProps" icon="mdi-dots-vertical" size="small" variant="text" aria-label="任务操作" @click.stop />
                </template>
                <VList density="compact" role="menu" aria-label="任务操作">
                  <VListItem role="menuitem" title="查看详情" prepend-icon="mdi-text-box-search-outline" @click="openDetail(item)" />
                  <VListItem v-if="canRetryTask(item)" role="menuitem" title="重新运行" prepend-icon="mdi-restart" base-color="primary" @click="requestRetry(item)" />
                  <VListItem role="menuitem" title="删除任务记录" prepend-icon="mdi-delete-outline" base-color="error" @click="requestDelete(item)" />
                </VList>
              </VMenu>
              <VIcon v-else icon="mdi-chevron-right" aria-hidden="true" />
            </template>
          </VListItem>
        </VList>

        <div v-if="isDesktop" class="pagination-bar">
          <span>共 {{ total }} 条</span>
          <VPagination v-model="page" :length="totalPages" :total-visible="5" density="comfortable" class="table-pagination" />
          <VSelect v-model="pageSize" :items="pageSizeOptions" label="每页" density="compact" class="page-size" />
        </div>
        <div v-else-if="canLoadMore" class="load-more">
          <VBtn variant="tonal" prepend-icon="mdi-chevron-down" :loading="refreshing" @click="loadMore">加载更多</VBtn>
        </div>
      </div>

      <DetailDrawer
        :model-value="Boolean(selectedId)"
        title="任务详情"
        :subtitle="detail?.target_file_name || selectedListItem?.target_file_name"
        close-label="关闭任务详情"
        :return-focus-key="selectedId ? `task:${selectedId}` : null"
        @update:model-value="updateDetailOpen"
      >
        <template #actions>
          <VTooltip v-if="selectedListItem && canRetryTask(selectedListItem)" text="重新运行任务">
            <template #activator="{ props: tooltipProps }">
              <VBtn v-bind="tooltipProps" icon="mdi-restart" color="primary" variant="text" aria-label="重新运行任务" @click="requestRetry(selectedListItem)" />
            </template>
          </VTooltip>
          <VTooltip v-if="selectedListItem && isTerminalTask(selectedListItem.status)" text="删除任务记录">
            <template #activator="{ props: tooltipProps }">
              <VBtn v-bind="tooltipProps" icon="mdi-delete-outline" color="error" variant="text" aria-label="删除任务记录" @click="requestDelete(selectedListItem)" />
            </template>
          </VTooltip>
        </template>

        <VSkeletonLoader v-if="detailLoading" class="detail-state" type="heading, paragraph, list-item-three-line@5" />
        <VAlert v-else-if="detailError" class="detail-state" type="error" variant="tonal">
          <div>{{ detailError }}</div>
          <VBtn v-if="selectedListItem" class="mt-2" size="small" variant="text" prepend-icon="mdi-refresh" @click="openDetail(selectedListItem)">重试</VBtn>
        </VAlert>
        <VExpansionPanels v-else-if="detail" v-model="openDetailPanels" multiple variant="accordion" class="detail-sections">
          <VExpansionPanel>
            <VExpansionPanelTitle>概览</VExpansionPanelTitle>
            <VExpansionPanelText>
              <dl>
                <DetailRow label="任务 ID"><CopyValue :value="detail.id" label="任务 ID" /></DetailRow>
                <DetailRow label="媒体">{{ mediaLabel(detail.media_title, detail.year, detail.season, detail.episode) }}</DetailRow>
                <DetailRow label="状态"><StateChip :state="taskStates[detail.status]" /></DetailRow>
                <DetailRow label="触发方式">{{ taskTriggerLabels[detail.trigger] }}</DetailRow>
                <DetailRow v-if="detail.manual_source" label="人工来源">{{ sourceLabels[detail.manual_source] }}</DetailRow>
                <DetailRow v-if="detail.actual_search_query" label="实际搜索词">{{ detail.actual_search_query }}</DetailRow>
                <DetailRow v-if="detail.manual_candidate_key" label="候选键"><CopyValue :value="detail.manual_candidate_key" label="候选键" /></DetailRow>
                <DetailRow v-if="detail.stage" label="当前阶段">{{ stageLabels[detail.stage] }}</DetailRow>
                <DetailRow label="终态原因">{{ detail.reason_message || detail.reason_code || '无' }}</DetailRow>
                <DetailRow label="创建时间">{{ formatDate(detail.created_at) }}</DetailRow>
                <DetailRow label="开始时间">{{ formatDate(detail.started_at) }}</DetailRow>
                <DetailRow label="完成时间">{{ formatDate(detail.finished_at) }}</DetailRow>
                <DetailRow label="耗时">{{ detail.status === 'processing' ? elapsedDuration(detail.started_at) : formatDuration(detail.duration_ms) }}</DetailRow>
              </dl>
            </VExpansionPanelText>
          </VExpansionPanel>

          <VExpansionPanel>
            <VExpansionPanelTitle>目标</VExpansionPanelTitle>
            <VExpansionPanelText>
              <dl>
                <DetailRow label="整理历史 ID"><CopyValue :value="detail.target_history_id == null ? null : String(detail.target_history_id)" label="整理历史 ID" /></DetailRow>
                <DetailRow label="历史目标路径"><CopyValue :value="detail.history_target_path" label="历史目标路径" /></DetailRow>
                <DetailRow label="实际字幕目标"><CopyValue :value="detail.target_path" label="实际字幕目标路径" /></DetailRow>
                <DetailRow label="命中路径映射">
                  {{ detail.matched_path_mapping
                    ? `${detail.matched_path_mapping.source_prefix} → ${detail.matched_path_mapping.target_prefix}`
                    : '未命中' }}
                </DetailRow>
                <DetailRow label="目标视频存在">{{ detail.target_file_exists == null ? '未记录' : (detail.target_file_exists ? '是' : '否') }}</DetailRow>
                <DetailRow label="目标存储">{{ detail.target_storage || '未记录' }}</DetailRow>
                <DetailRow label="媒体类型">{{ mediaTypeLabels[detail.media_type] }}</DetailRow>
                <DetailRow label="TMDB ID">{{ detail.tmdb_id ?? '未记录' }}</DetailRow>
                <DetailRow label="IMDb ID">{{ detail.imdb_id || '未记录' }}</DetailRow>
              </dl>
            </VExpansionPanelText>
          </VExpansionPanel>

          <VExpansionPanel>
            <VExpansionPanelTitle>处理轨迹</VExpansionPanelTitle>
            <VExpansionPanelText>
              <div class="subsection">
                <h4>已有字幕检查</h4>
                <dl v-if="detailEntries(detail.existing_subtitle_check).length">
                  <DetailRow v-for="[key, value] in detailEntries(detail.existing_subtitle_check)" :key="key" :label="friendlyKey(key)">{{ displayValue(value) }}</DetailRow>
                </dl>
                <p v-else class="muted">未记录检查摘要</p>
              </div>
              <div class="subsection">
                <h4>字幕库存</h4>
                <dl v-if="detailEntries(detail.inventory_result).length">
                  <DetailRow v-for="[key, value] in detailEntries(detail.inventory_result)" :key="key" :label="friendlyKey(key)">{{ displayValue(value) }}</DetailRow>
                </dl>
                <p v-else class="muted">未记录库存摘要</p>
              </div>
              <VTimeline v-if="detail.stage_traces.length" density="compact" side="end" class="task-timeline">
                <VTimelineItem v-for="trace in detail.stage_traces" :key="`${trace.stage}-${trace.started_at}`" dot-color="primary" size="x-small">
                  <strong>{{ stageLabels[trace.stage] }}</strong>
                  <div class="muted">{{ trace.summary || '阶段已完成' }}</div>
                  <div class="muted">{{ formatDate(trace.started_at) }} · {{ formatDuration(trace.duration_ms) }}</div>
                </VTimelineItem>
              </VTimeline>
            </VExpansionPanelText>
          </VExpansionPanel>

          <VExpansionPanel>
            <VExpansionPanelTitle>字幕源与候选</VExpansionPanelTitle>
            <VExpansionPanelText>
              <dl class="candidate-policy">
                <DetailRow label="包内归属策略">
                  {{ detail.package_attribution_strategy
                    ? attributionStrategyLabels[detail.package_attribution_strategy]
                    : '未记录' }}
                </DetailRow>
                <DetailRow v-if="detail.candidate_attribution_snapshot" label="候选归属快照">
                  {{ displayValue(detail.candidate_attribution_snapshot) }}
                </DetailRow>
              </dl>
              <VList v-if="detail.source_runs.length" density="compact" class="audit-list">
                <VListItem v-for="run in detail.source_runs" :key="run.source" :title="sourceLabels[run.source]">
                  <template #subtitle>
                    <span class="source-run-summary">
                      <span>{{ sourceRunLabels[run.status] }}</span>
                      <span v-if="!isSkippedSourceRun(run) && hasSourceRunFunnel(run)">{{ sourceRunFunnel(run) }}</span>
                      <span v-else-if="!isSkippedSourceRun(run)">{{ run.candidate_count ?? 0 }} 个候选</span>
                      <span v-if="run.duration_ms !== null">{{ formatDuration(run.duration_ms) }}</span>
                    </span>
                    <span v-if="sourceRunContext(run)" class="source-run-context">
                      {{ sourceRunContext(run) }}
                    </span>
                    <span v-if="sourceRunRejectionSummary(run)" class="source-run-rejections">
                      自动排除：{{ sourceRunRejectionSummary(run) }}
                    </span>
                    <span v-if="run.error_summary" class="error-text">{{ run.error_summary }}</span>
                  </template>
                </VListItem>
              </VList>
              <p v-else class="muted">没有字幕源运行记录</p>

              <VAlert v-if="detail.trigger === 'manual_candidate'" type="info" variant="tonal" density="compact" class="mt-3">
                这是人工字幕搜索选定候选后的下载任务；库存查询与自动准入筛选不会在此任务中重复执行。
              </VAlert>
              <dl v-if="detail.trigger === 'manual_candidate' && detailEntries(detail.manual_candidate_summary).length" class="manual-summary">
                <DetailRow v-for="[key, value] in detailEntries(detail.manual_candidate_summary)" :key="key" :label="friendlyKey(key)">{{ displayValue(value) }}</DetailRow>
              </dl>

              <div v-if="detail.candidate_attempts.length" class="candidate-list">
                <div v-for="attempt in detail.candidate_attempts" :key="attempt.candidate_key" class="candidate-item">
                  <div class="candidate-item__heading">
                    <strong>{{ sourceLabels[attempt.source] }}</strong>
                    <span>{{ attemptLabels[attempt.result] }}</span>
                  </div>
                  <div class="muted">{{ [packageLabels[attempt.package_scope], attempt.format && attempt.format !== 'UNKNOWN' ? attempt.format : '', attempt.language, translationLabels[attempt.translation_type], attempt.hearing_impaired ? 'SDH/CC' : ''].filter(Boolean).join(' · ') }}</div>
                  <div v-if="attempt.attribution_strategy" class="muted">归属策略：{{ attributionStrategyLabels[attempt.attribution_strategy] }}</div>
                  <div v-if="attempt.candidate_snapshot" class="muted">候选快照：{{ displayValue(attempt.candidate_snapshot) }}</div>
                  <div v-if="attempt.extracted_count != null" class="candidate-funnel">
                    解包 {{ attempt.extracted_count }}
                    → 当前目标 {{ attempt.current_target_count ?? 0 }}
                    → 其他季集 {{ attempt.same_media_other_episode_count ?? 0 }}
                    / 归属不明确 {{ attempt.ambiguous_count ?? 0 }}
                    / 其他媒体 {{ attempt.other_media_count ?? 0 }}
                    → 落盘 {{ attempt.written_count ?? 0 }}
                    / 暂存 {{ attempt.staged_count ?? 0 }}
                    / 未匹配 {{ attempt.unmatched_count ?? 0 }}
                  </div>
                  <div v-if="(attempt.ai_attempt_count ?? 0) || (attempt.ai_accepted_count ?? 0) || (attempt.ai_rejected_count ?? 0) || (attempt.ai_error_count ?? 0) || (attempt.ai_over_limit_count ?? 0) || (attempt.ai_reason_summary && Object.keys(attempt.ai_reason_summary).length)" class="candidate-ai">
                    AI 智能接管：尝试 {{ attempt.ai_attempt_count }} · 采纳 {{ attempt.ai_accepted_count ?? 0 }} · 拒绝 {{ attempt.ai_rejected_count ?? 0 }} · 错误 {{ attempt.ai_error_count ?? 0 }}<span v-if="attempt.ai_over_limit_count"> · 超限/未提交 {{ attempt.ai_over_limit_count }}</span>
                  </div>
                  <div v-if="attempt.ai_reason_summary && Object.keys(attempt.ai_reason_summary).length" class="muted">AI 结果摘要：{{ displayValue(attempt.ai_reason_summary) }}</div>
                  <div v-if="attempt.error_summary" class="error-text">{{ attempt.error_summary }}</div>
                </div>
              </div>
            </VExpansionPanelText>
          </VExpansionPanel>

          <VExpansionPanel>
            <VExpansionPanelTitle>产物</VExpansionPanelTitle>
            <VExpansionPanelText>
              <dl>
                <DetailRow label="最终字幕"><CopyValue :value="detail.final_subtitle_path" label="字幕路径" /></DetailRow>
                <DetailRow label="匹配记录">{{ detail.record_ids.length ? `${detail.record_ids.length} 条` : '无' }}</DetailRow>
                <DetailRow v-for="(count, key) in detail.record_counts" :key="key" :label="friendlyKey(key)">{{ count }}</DetailRow>
                <DetailRow label="警告数量">{{ detail.warning_count }}</DetailRow>
              </dl>
              <VAlert v-if="detail.warning_summaries.length" type="warning" variant="tonal" density="compact" class="mt-3">
                <ul class="warning-list"><li v-for="warning in detail.warning_summaries" :key="warning">{{ warning }}</li></ul>
              </VAlert>
            </VExpansionPanelText>
          </VExpansionPanel>
        </VExpansionPanels>
      </DetailDrawer>
    </div>

    <ConfirmDialog
      v-model="scanOpen"
      :title="scanMode === 'full' ? '重新扫描全部媒体' : '增量扫描自定义媒体目录'"
      :message="scanMode === 'full'
        ? '将忽略已有扫描索引，把当前目录内全部视频和 STRM 文件重新加入识别与字幕检查。已有标准简中字幕的目标会在任务预检时跳过；大型目录可能产生大量任务并需要较长时间。'
        : '将递归检查当前已保存目录，未变更的历史文件会直接跳过；只有新增、变更或上次处理失败的目标会进入自动字幕队列。'"
      :confirm-text="scanMode === 'full' ? '确认全部重扫' : '开始扫描'"
      :confirm-color="scanMode === 'full' ? 'warning' : 'primary'"
      :confirm-icon="scanMode === 'full' ? 'mdi-database-refresh-outline' : 'mdi-folder-search-outline'"
      :title-icon="scanMode === 'full' ? 'mdi-database-refresh-outline' : 'mdi-folder-search-outline'"
      :loading="scanning"
      @confirm="confirmDirectoryScan"
    />

    <ConfirmDialog
      v-model="clearTasksOpen"
      title="清理已结束任务"
      message="将一次清除所有成功、跳过、失败和已中断的任务历史。排队中和处理中的任务会保留，字幕文件与匹配记录不会被删除。此操作无法撤销。"
      confirm-text="全部清理"
      confirm-icon="mdi-delete-sweep-outline"
      title-icon="mdi-delete-sweep-outline"
      :loading="clearingTasks"
      @confirm="confirmClearTasks"
    />

    <ConfirmDialog
      v-model="deleteOpen"
      title="删除任务记录"
      message="只会删除这条终态任务历史，不会删除匹配记录、插件数据文件或媒体目录中的字幕。此操作无法撤销。"
      :loading="deleting"
      @confirm="confirmDelete"
    />

    <ConfirmDialog
      v-model="retryOpen"
      title="重新运行任务"
      :message="`将保留原任务记录，并根据“${retryTarget?.target_file_name || '当前媒体'}”的媒体信息和文件路径创建一条新任务。若同路径任务已在运行，将自动合并。`"
      confirm-text="重新提交"
      confirm-icon="mdi-restart"
      title-icon="mdi-restart"
      :loading="retrying"
      @confirm="confirmRetryTask"
    />

    <ConfirmDialog
      v-model="batchRetryOpen"
      :title="batchRetryScope === 'selected' ? '重启选中任务' : `重启${currentGroupTitle}`"
      :message="batchRetryMessage"
      :confirm-text="batchRetryScope === 'selected' ? '重启选中任务' : '重启此分组'"
      confirm-color="primary"
      confirm-icon="mdi-restart"
      title-icon="mdi-restart"
      :loading="batchRetrying"
      @confirm="confirmBatchRetry"
    />

    <ConfirmDialog
      v-model="batchDeleteOpen"
      :title="batchDeleteScope === 'selected' ? '删除选中任务' : `删除${currentGroupTitle}`"
      :message="batchDeleteMessage"
      :confirm-text="batchDeleteScope === 'selected' ? '删除选中' : '删除此分组'"
      confirm-color="error"
      confirm-icon="mdi-delete-outline"
      title-icon="mdi-delete-sweep-outline"
      :loading="batchDeleting"
      @confirm="confirmBatchDelete"
    />
  </section>
</template>

<style scoped>
.view-shell { min-width: 0; }
.view-controls {
  position: sticky;
  z-index: 3;
  inset-block-start: var(--layout-navbar-block-size, var(--v-layout-top, 0px));
  margin-block-end: 1rem;
  padding-block: 0.25rem 0.75rem;
  background: rgb(var(--v-theme-surface));
  border-block-end: 0;
  box-shadow: none;
}
.view-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 1rem; margin-block-end: 0.75rem; }
.view-header h2 { margin: 0; color: rgb(var(--v-theme-on-surface)); font-size: 1rem; font-weight: 650; letter-spacing: 0; }
.view-header p { margin: 0.25rem 0 0; color: rgba(var(--v-theme-on-surface), var(--v-medium-emphasis-opacity)); font-size: 0.8125rem; }
.header-actions { display: flex; flex: 0 0 auto; align-items: center; gap: 0.25rem; }
.filter-bar { display: grid; grid-template-columns: minmax(0, 1fr); gap: 0.75rem; }
.inline-alert { display: flex; align-items: center; justify-content: space-between; gap: 1rem; }
.status-group-toolbar {
  display: flex;
  min-width: 0;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  margin-block-start: 0.625rem;
}
.status-segments { min-width: 0; overflow-x: auto; scrollbar-width: thin; }
.status-segments :deep(.v-btn-toggle) { min-width: max-content; }
.status-segments :deep(.v-btn) { min-width: 4.75rem; letter-spacing: 0; }
.status-segment-count {
  min-width: 1.25rem;
  margin-inline-start: 0.4rem;
  padding-inline: 0.25rem;
  border-radius: 0.25rem;
  color: rgba(var(--v-theme-on-surface), var(--v-medium-emphasis-opacity));
  background: rgba(var(--v-theme-on-surface), 0.07);
  font-size: 0.6875rem;
  line-height: 1.25rem;
}
.status-group-summary {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 0.25rem;
  color: rgba(var(--v-theme-on-surface), var(--v-medium-emphasis-opacity));
  font-size: 0.75rem;
  white-space: nowrap;
}
.notice-alert {
  flex: 0 0 auto;
  min-block-size: 2.5rem;
  overflow: visible;
}
.notice-alert :deep(.v-alert__content) {
  min-width: 0;
  overflow: visible;
  overflow-wrap: anywhere;
  line-height: 1.45;
  white-space: normal;
}
.batch-action-bar {
  display: flex;
  min-height: 3rem;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  margin-block-end: 0.75rem;
  padding: 0.5rem 0.75rem;
  border: 1px solid rgba(var(--v-theme-primary), 0.28);
  border-radius: 0.375rem;
  background: rgba(var(--v-theme-primary), 0.08);
}
.batch-action-bar__summary, .batch-action-bar__actions { display: flex; align-items: center; gap: 0.5rem; }
.batch-action-bar__summary { color: rgb(var(--v-theme-on-surface)); font-size: 0.8125rem; font-weight: 600; }
.master-detail, .master-pane { min-width: 0; }
.table-frame { overflow: hidden; border: 1px solid rgba(var(--v-border-color), var(--v-border-opacity)); border-radius: 0.375rem; background: rgb(var(--v-theme-surface)); }
.table-frame :deep(.v-table__wrapper) { overscroll-behavior: contain; scrollbar-gutter: stable; }
.data-table :deep(table) { width: 100%; table-layout: fixed; }
.table-frame :deep(thead th) { color: rgba(var(--v-theme-on-surface), var(--v-medium-emphasis-opacity)); background: rgb(var(--v-theme-surface)) !important; font-size: 0.75rem; font-weight: 650 !important; }
.table-frame :deep(tbody td) { border-bottom-color: rgba(var(--v-border-color), 0.08) !important; }
.selectable-row { cursor: pointer; transition: background-color 180ms ease; }
.selectable-row:hover, .selectable-row--active { background: rgba(var(--v-theme-primary), 0.08); }
.selectable-row:focus-visible { outline: 2px solid rgb(var(--v-theme-primary)); outline-offset: -2px; scroll-margin-block-start: var(--v-table-header-height, 3rem); }
.primary-cell { display: flex; min-width: 0; align-items: flex-start; gap: 0.5rem; }
.primary-cell > div { min-width: 0; }
.primary-cell strong, .primary-cell span { display: block; }
.primary-cell strong { overflow: hidden; color: rgb(var(--v-theme-on-surface)); font-size: 0.875rem; text-overflow: ellipsis; white-space: nowrap; }
.primary-cell span, .cell-note, .time-text { color: rgba(var(--v-theme-on-surface), var(--v-medium-emphasis-opacity)); font-size: 0.75rem; }
.file-name { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.result-text { display: -webkit-box; overflow: hidden; -webkit-box-orient: vertical; -webkit-line-clamp: 2; font-size: 0.8125rem; }
.time-text { display: block; line-height: 1.45; }
.selection-column { width: 2.75rem; padding-inline: 0.5rem !important; }
.media-column { width: 19%; }
.file-column { width: 18%; }
.status-column { width: 5.75rem; }
.trigger-column { width: 4.5rem; }
.result-column { width: 16%; }
.time-column { width: 8.25rem; }
.actions-column { width: 6.5rem; text-align: end !important; white-space: nowrap; }
.pagination-bar { display: grid; grid-template-columns: auto 1fr 7rem; align-items: center; gap: 1rem; padding: 0.75rem 0; color: rgba(var(--v-theme-on-surface), var(--v-medium-emphasis-opacity)); font-size: 0.8125rem; }
.table-pagination { justify-self: center; }
.page-size { min-width: 7rem; }
.detail-state { margin: 1rem; }
.detail-sections { border-radius: 0; }
.subsection + .subsection { margin-top: 1.25rem; }
.subsection h4 { margin: 0 0 0.5rem; font-size: 0.875rem; }
.task-timeline { height: auto !important; }
.muted { color: rgba(var(--v-theme-on-surface), var(--v-medium-emphasis-opacity)); font-size: 0.8125rem; line-height: 1.5; }
.error-text { display: block; margin-top: 0.25rem; color: rgb(var(--v-theme-error)); font-size: 0.8125rem; }
.audit-list { background: transparent; }
.source-run-summary { display: flex; flex-wrap: wrap; align-items: center; gap: 0.25rem 0.5rem; }
.source-run-summary > span + span::before { margin-right: 0.5rem; content: '·'; }
.source-run-context, .source-run-rejections { display: block; margin-top: 0.25rem; color: rgba(var(--v-theme-on-surface), var(--v-medium-emphasis-opacity)); }
.candidate-policy { margin: 0 0 0.75rem; }
.candidate-list { display: grid; gap: 0.625rem; margin-top: 1rem; }
.candidate-item { padding: 0.75rem; border: 1px solid rgba(var(--v-border-color), var(--v-border-opacity)); border-radius: 0.25rem; }
.candidate-item__heading { display: flex; justify-content: space-between; gap: 1rem; font-size: 0.8125rem; }
.candidate-funnel { margin-top: 0.35rem; overflow-wrap: anywhere; color: rgba(var(--v-theme-on-surface), var(--v-medium-emphasis-opacity)); font-size: 0.75rem; line-height: 1.55; }
.candidate-ai { margin-top: 0.35rem; overflow-wrap: anywhere; color: rgb(var(--v-theme-primary)); font-size: 0.75rem; line-height: 1.55; }
.warning-list { margin: 0; padding-left: 1.25rem; }
.mobile-list { padding: 0; overflow: hidden; border: 1px solid rgba(var(--v-border-color), var(--v-border-opacity)); border-radius: 0.375rem; background: rgb(var(--v-theme-surface)); }
.mobile-list__item { min-height: 6rem; border-bottom: 1px solid rgba(var(--v-border-color), var(--v-border-opacity)); }
.mobile-list__detail { display: grid; width: 100%; min-width: 0; padding: 0; border: 0; color: inherit; text-align: start; background: transparent; cursor: pointer; font: inherit; }
.mobile-list__detail:focus-visible { border-radius: 0.125rem; outline: 2px solid rgb(var(--v-theme-primary)); outline-offset: 2px; }
.mobile-subtitle { overflow-wrap: anywhere; }
.mobile-meta { display: flex !important; align-items: center; gap: 0.5rem; margin-top: 0.375rem; }
.load-more { display: flex; justify-content: center; padding: 1rem; }

@media (min-width: 960px) {
  .view-shell {
    display: flex;
    block-size: 100%;
    min-block-size: 0;
    flex-direction: column;
    overflow: hidden;
  }
  .view-controls {
    position: static;
    z-index: auto;
    flex: 0 0 auto;
    margin-block-end: 0.75rem;
    padding-block: 0;
    box-shadow: none;
  }
  .view-header { min-block-size: 2.5rem; margin-block-end: 0.5rem; }
  .master-detail {
    flex: 1 1 auto;
    min-block-size: 0;
    overflow: hidden;
  }
  .master-pane {
    display: grid;
    block-size: 100%;
    min-block-size: 0;
    grid-template-rows: minmax(0, 1fr) auto;
  }
  .table-frame { min-block-size: 0; }
  .data-table { block-size: 100%; }
  .view-shell > .table-frame {
    flex: 1 1 auto;
    min-block-size: 0;
  }
  .pagination-bar { min-block-size: 3rem; padding-block: 0.375rem 0; }
}

@media (max-width: 959px) {
  .filter-bar { grid-template-columns: minmax(0, 1fr) minmax(8rem, 10rem); }
  .status-group-toolbar { justify-content: flex-end; }
}

@media (max-width: 37.5rem) {
  .view-controls { margin-block-end: 0.75rem; padding-block-end: 0.5rem; }
  .view-header { margin-block-end: 0.5rem; }
  .view-header p { display: none; }
  .filter-bar { grid-template-columns: minmax(0, 1fr); gap: 0.5rem; }
  .status-group-summary { width: 100%; flex-wrap: wrap; justify-content: flex-end; white-space: normal; }
}

@media (prefers-reduced-motion: reduce) {
  .selectable-row { transition: none; }
}
</style>
