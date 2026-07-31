<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import type { PluginApi } from '@/types'
import OverviewView from '@/views/OverviewView.vue'
import RecordsView from '@/views/RecordsView.vue'
import SearchView from '@/views/SearchView.vue'
import SourcesView from '@/views/SourcesView.vue'
import TasksView from '@/views/TasksView.vue'
import frontendPackage from '../../package.json'

const props = withDefaults(defineProps<{
  api: PluginApi
  pluginId: string
  navKey?: string
}>(), {
  navKey: 'main',
})

const emit = defineEmits<{ action: [] }>()
type WorkbenchView = 'overview' | 'tasks' | 'records' | 'search' | 'sources'
const SCROLL_MEMORY_SETTLE_MS = 600
const APP_VERSION = frontendPackage.version

const activeView = ref<WorkbenchView>('overview')
const navigation: Array<{ value: WorkbenchView; label: string; icon: string }> = [
  { value: 'overview', label: '概览', icon: 'mdi-view-dashboard-outline' },
  { value: 'tasks', label: '任务', icon: 'mdi-format-list-checks' },
  { value: 'records', label: '字幕', icon: 'mdi-closed-caption-outline' },
  { value: 'search', label: '搜索', icon: 'mdi-text-search' },
  { value: 'sources', label: '来源', icon: 'mdi-database-outline' },
]
const workbenchElement = ref<HTMLElement | null>(null)
const workbenchHeight = ref<number | null>(null)
const viewScrollTop: Record<WorkbenchView, number> = {
  overview: 0,
  tasks: 0,
  records: 0,
  search: 0,
  sources: 0,
}
let resizeFrame: number | null = null
let scrollRestoreFrame: number | null = null
let scrollRestoreRequest = 0
let scrollMemoryElement: HTMLElement | null = null
let scrollMemoryTarget: EventTarget | null = null
let scrollMemoryView: WorkbenchView | null = null
let scrollMemoryTimer: number | null = null
let pendingScrollTop = 0
let resizeObserver: ResizeObserver | null = null

const isDataView = computed(() => activeView.value === 'tasks' || activeView.value === 'records')
const activeNavigation = computed(() => navigation.find(item => item.value === activeView.value) || navigation[0])
const workbenchStyle = computed(() => ({
  '--subtitle-download-workbench-height': workbenchHeight.value === null
    ? undefined
    : `${workbenchHeight.value}px`,
}))

function updateWorkbenchHeight(): void {
  const element = workbenchElement.value
  if (!element || !window.matchMedia('(min-width: 960px)').matches) {
    workbenchHeight.value = null
    bindViewScrollTracking(activeView.value)
    return
  }

  const hostPage = element.closest<HTMLElement>('.layout-page-content')
  const hostBottomPadding = hostPage
    ? Number.parseFloat(window.getComputedStyle(hostPage).paddingBottom) || 0
    : 16
  const viewportTop = Math.max(0, element.getBoundingClientRect().top)
  const availableHeight = Math.max(0, Math.floor(window.innerHeight - viewportTop - hostBottomPadding))
  if (workbenchHeight.value !== availableHeight) workbenchHeight.value = availableHeight
  bindViewScrollTracking(activeView.value)
}

function scheduleWorkbenchHeightUpdate(): void {
  if (resizeFrame !== null) window.cancelAnimationFrame(resizeFrame)
  resizeFrame = window.requestAnimationFrame(() => {
    resizeFrame = null
    updateWorkbenchHeight()
  })
}

function resolveViewScrollElement(view: WorkbenchView): HTMLElement | null {
  if (typeof document === 'undefined') return null
  if (window.matchMedia('(min-width: 960px)').matches) {
    const viewElement = workbenchElement.value
      ?.querySelector<HTMLElement>(`[data-subtitle-download-view="${view}"]`) || null
    if (view === 'overview' || view === 'search' || view === 'sources') return viewElement
    return viewElement?.querySelector<HTMLElement>('.v-table__wrapper') || null
  }

  return document.scrollingElement instanceof HTMLElement ? document.scrollingElement : document.documentElement
}

function rememberViewScroll(view: WorkbenchView): void {
  const element = resolveViewScrollElement(view)
  if (element) viewScrollTop[view] = element.scrollTop
}

function commitPendingScroll(): void {
  if (scrollMemoryView) viewScrollTop[scrollMemoryView] = pendingScrollTop
  scrollMemoryTimer = null
}

function handleTrackedScroll(): void {
  if (!scrollMemoryElement || !scrollMemoryView) return
  pendingScrollTop = scrollMemoryElement.scrollTop
  if (pendingScrollTop > viewScrollTop[scrollMemoryView]) {
    viewScrollTop[scrollMemoryView] = pendingScrollTop
  }
  if (scrollMemoryTimer !== null) window.clearTimeout(scrollMemoryTimer)
  scrollMemoryTimer = window.setTimeout(commitPendingScroll, SCROLL_MEMORY_SETTLE_MS)
}

function stopViewScrollTracking(): void {
  scrollMemoryTarget?.removeEventListener('scroll', handleTrackedScroll)
  scrollMemoryElement = null
  scrollMemoryTarget = null
  scrollMemoryView = null
  if (scrollMemoryTimer !== null) window.clearTimeout(scrollMemoryTimer)
  scrollMemoryTimer = null
}

function bindViewScrollTracking(view: WorkbenchView): void {
  const element = resolveViewScrollElement(view)
  const target = element === document.scrollingElement ? document : element
  if (scrollMemoryElement === element && scrollMemoryView === view) return
  stopViewScrollTracking()
  scrollMemoryElement = element
  scrollMemoryTarget = target
  scrollMemoryView = element ? view : null
  pendingScrollTop = element?.scrollTop || 0
  target?.addEventListener('scroll', handleTrackedScroll, { passive: true })
}

function scheduleViewScrollRestore(view: WorkbenchView): void {
  const request = ++scrollRestoreRequest
  void nextTick(() => {
    if (request !== scrollRestoreRequest) return
    if (scrollRestoreFrame !== null) window.cancelAnimationFrame(scrollRestoreFrame)
    scrollRestoreFrame = window.requestAnimationFrame(() => {
      if (request !== scrollRestoreRequest) {
        scrollRestoreFrame = null
        return
      }
      scrollRestoreFrame = window.requestAnimationFrame(() => {
        scrollRestoreFrame = null
        if (request !== scrollRestoreRequest) return
        const element = resolveViewScrollElement(view)
        if (element) element.scrollTop = viewScrollTop[view]
        bindViewScrollTracking(view)
      })
    })
  })
}

watch(activeView, (view, previousView) => {
  const wasTrackingPreviousView = scrollMemoryView === previousView
  stopViewScrollTracking()
  if (!wasTrackingPreviousView) rememberViewScroll(previousView)
  scheduleViewScrollRestore(view)
})

onMounted(() => {
  window.addEventListener('resize', scheduleWorkbenchHeightUpdate, { passive: true })
  window.visualViewport?.addEventListener('resize', scheduleWorkbenchHeightUpdate, { passive: true })
  if (workbenchElement.value && typeof ResizeObserver !== 'undefined') {
    resizeObserver = new ResizeObserver(scheduleWorkbenchHeightUpdate)
    resizeObserver.observe(workbenchElement.value.parentElement || workbenchElement.value)
  }
  void nextTick(scheduleWorkbenchHeightUpdate)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', scheduleWorkbenchHeightUpdate)
  window.visualViewport?.removeEventListener('resize', scheduleWorkbenchHeightUpdate)
  resizeObserver?.disconnect()
  stopViewScrollTracking()
  if (resizeFrame !== null) window.cancelAnimationFrame(resizeFrame)
  scrollRestoreRequest += 1
  if (scrollRestoreFrame !== null) window.cancelAnimationFrame(scrollRestoreFrame)
})
</script>

<template>
  <main ref="workbenchElement" class="subtitle-download-workbench" :style="workbenchStyle">
    <aside class="app-sidebar">
      <div class="brand-lockup">
        <div class="brand-mark"><VIcon icon="mdi-subtitles-outline" size="24" aria-hidden="true" /></div>
        <div class="brand-copy">
          <h1 id="subtitle-download-workbench-title" tabindex="-1">字幕下载助手</h1>
          <span>MoviePilot</span>
        </div>
      </div>
      <div class="navigation-label">工作台</div>
      <nav class="desktop-navigation" aria-label="字幕下载助手工作台视图">
        <button
          v-for="item in navigation"
          :key="item.value"
          type="button"
          class="desktop-navigation__item"
          :class="{ 'desktop-navigation__item--active': activeView === item.value }"
          :aria-current="activeView === item.value ? 'page' : undefined"
          @click="activeView = item.value"
        >
          <VIcon :icon="item.icon" size="20" aria-hidden="true" />
          <span>{{ item.label }}</span>
        </button>
      </nav>
      <div class="sidebar-footer">
        <span>字幕下载助手</span>
        <strong>v{{ APP_VERSION }}</strong>
      </div>
    </aside>

    <section class="app-main">
      <header class="mobile-brandbar">
        <div class="brand-lockup">
          <div class="brand-mark"><VIcon icon="mdi-subtitles-outline" size="21" aria-hidden="true" /></div>
          <div class="brand-copy"><strong>字幕下载助手</strong><span>MoviePilot</span></div>
        </div>
        <span class="mobile-version">v{{ APP_VERSION }}</span>
      </header>

      <nav class="mobile-navigation" aria-label="字幕下载助手工作台视图">
        <button
          v-for="item in navigation"
          :key="item.value"
          type="button"
          :class="{ 'mobile-navigation__item--active': activeView === item.value }"
          :aria-current="activeView === item.value ? 'page' : undefined"
          @click="activeView = item.value"
        >
          <VIcon :icon="item.icon" size="19" aria-hidden="true" />
          <span>{{ item.label }}</span>
        </button>
      </nav>

      <header class="page-toolbar">
        <div>
          <span>字幕工作台</span>
          <h2>{{ activeNavigation.label }}</h2>
        </div>
        <div class="toolbar-status"><span class="status-dot" />服务运行中</div>
      </header>

      <section class="workbench-content">
        <VWindow
          v-model="activeView"
          :touch="false"
          class="workbench-window"
          :class="{ 'workbench-window--data-view': isDataView }"
        >
          <VWindowItem value="overview" eager class="workbench-view workbench-view--overview" data-subtitle-download-view="overview" :transition="false" :reverse-transition="false">
            <OverviewView :api="props.api" :plugin-id="props.pluginId" :active="activeView === 'overview'" @navigate="activeView = $event" @action="emit('action')" />
          </VWindowItem>
          <VWindowItem value="tasks" eager class="workbench-view workbench-view--data" data-subtitle-download-view="tasks" :transition="false" :reverse-transition="false">
            <TasksView :api="props.api" :plugin-id="props.pluginId" :active="activeView === 'tasks'" @action="emit('action')" />
          </VWindowItem>
          <VWindowItem value="records" eager class="workbench-view workbench-view--data" data-subtitle-download-view="records" :transition="false" :reverse-transition="false">
            <RecordsView :api="props.api" :plugin-id="props.pluginId" :active="activeView === 'records'" @action="emit('action')" />
          </VWindowItem>
          <VWindowItem value="search" eager class="workbench-view" data-subtitle-download-view="search" :transition="false" :reverse-transition="false">
            <SearchView :api="props.api" :plugin-id="props.pluginId" :active="activeView === 'search'" @action="emit('action')" />
          </VWindowItem>
          <VWindowItem value="sources" eager class="workbench-view" data-subtitle-download-view="sources" :transition="false" :reverse-transition="false">
            <SourcesView :api="props.api" :plugin-id="props.pluginId" :active="activeView === 'sources'" @action="emit('action')" />
          </VWindowItem>
        </VWindow>
      </section>
    </section>
  </main>
</template>

<style scoped>
.subtitle-download-workbench {
  box-sizing: border-box;
  width: 100%;
  min-width: 0;
  margin: 0;
  padding: 0;
  color: rgb(var(--v-theme-on-surface));
  background: rgb(var(--v-theme-background));
}
.app-sidebar { display: none; }
.brand-lockup { display: flex; min-width: 0; align-items: center; gap: 0.75rem; }
.brand-mark { display: grid; width: 2.5rem; height: 2.5rem; flex: 0 0 auto; place-items: center; border-radius: 0.5rem; color: rgb(var(--v-theme-on-primary)); background: rgb(var(--v-theme-primary)); box-shadow: 0 0.35rem 0.9rem rgba(var(--v-theme-primary), 0.24); }
.brand-copy { min-width: 0; }
.brand-copy h1, .brand-copy strong { display: block; margin: 0; overflow-wrap: anywhere; font-size: 0.9375rem; font-weight: 700; letter-spacing: 0; line-height: 1.25; }
.brand-copy > span { display: block; margin-top: 0.125rem; color: rgba(var(--v-theme-on-surface), var(--v-medium-emphasis-opacity)); font-size: 0.6875rem; letter-spacing: 0; }
.brand-copy h1:focus-visible { border-radius: 0.125rem; outline: 2px solid rgb(var(--v-theme-primary)); outline-offset: 3px; }
.app-main { min-width: 0; }
.mobile-brandbar { display: flex; min-height: 4rem; align-items: center; justify-content: space-between; gap: 1rem; padding: 0.625rem 1rem; border-bottom: 1px solid rgba(var(--v-border-color), var(--v-border-opacity)); background: rgb(var(--v-theme-surface)); }
.mobile-brandbar .brand-mark { width: 2.25rem; height: 2.25rem; }
.mobile-version { color: rgba(var(--v-theme-on-surface), var(--v-medium-emphasis-opacity)); font-size: 0.6875rem; font-variant-numeric: tabular-nums; }
.mobile-navigation { display: flex; min-width: 0; overflow-x: auto; border-bottom: 1px solid rgba(var(--v-border-color), var(--v-border-opacity)); background: rgb(var(--v-theme-surface)); scrollbar-width: none; }
.mobile-navigation::-webkit-scrollbar { display: none; }
.mobile-navigation button { display: flex; position: relative; min-width: 4.75rem; min-height: 3.75rem; flex: 1 0 auto; align-items: center; justify-content: center; flex-direction: column; gap: 0.2rem; padding: 0.4rem 0.625rem; border: 0; color: rgba(var(--v-theme-on-surface), var(--v-medium-emphasis-opacity)); background: transparent; cursor: pointer; font: inherit; font-size: 0.6875rem; }
.mobile-navigation button::after { position: absolute; right: 1rem; bottom: 0; left: 1rem; height: 0.125rem; border-radius: 0.125rem 0.125rem 0 0; background: transparent; content: ''; }
.mobile-navigation button:hover { color: rgb(var(--v-theme-on-surface)); background: rgba(var(--v-theme-primary), 0.04); }
.mobile-navigation .mobile-navigation__item--active { color: rgb(var(--v-theme-primary)); font-weight: 650; }
.mobile-navigation .mobile-navigation__item--active::after { background: rgb(var(--v-theme-primary)); }
.mobile-navigation button:focus-visible { z-index: 1; outline: 2px solid rgb(var(--v-theme-primary)); outline-offset: -2px; }
.page-toolbar { display: flex; min-height: 4.75rem; align-items: center; justify-content: space-between; gap: 1rem; padding: 0.75rem 1rem; }
.page-toolbar > div:first-child > span { color: rgba(var(--v-theme-on-surface), var(--v-medium-emphasis-opacity)); font-size: 0.6875rem; }
.page-toolbar h2 { margin: 0.125rem 0 0; font-size: 1.125rem; font-weight: 650; letter-spacing: 0; }
.toolbar-status { display: flex; flex: 0 0 auto; align-items: center; gap: 0.4rem; color: rgba(var(--v-theme-on-surface), var(--v-medium-emphasis-opacity)); font-size: 0.6875rem; }
.status-dot { width: 0.45rem; height: 0.45rem; border-radius: 50%; background: rgb(var(--v-theme-success)); box-shadow: 0 0 0 0.2rem rgba(var(--v-theme-success), 0.12); }
.workbench-content { min-width: 0; padding: 0 1rem 1.5rem; }
.workbench-window { min-height: 28rem; overflow: clip; }
.workbench-content :deep(.v-btn:focus-visible), .workbench-content :deep(input:focus-visible) { outline: 2px solid rgb(var(--v-theme-primary)); outline-offset: 2px; }
.workbench-view--data :deep(.view-shell) { padding: 1rem; border: 1px solid rgba(var(--v-border-color), 0.08); border-radius: 0.5rem; background: rgb(var(--v-theme-surface)); box-shadow: 0 0.25rem 1.125rem rgba(30, 26, 48, 0.07); }
.workbench-view :deep(.view-header > div:first-child) { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; clip-path: inset(50%); }
.workbench-view :deep(.view-header) { justify-content: flex-end; }

@media (min-width: 960px) {
  :global(.layout-page-content:has(.subtitle-download-workbench) + .layout-footer) {
    display: none;
  }

  .subtitle-download-workbench {
    display: grid;
    block-size: var(--subtitle-download-workbench-height, calc(100dvh - 6rem));
    grid-template-columns: 14.5rem minmax(0, 1fr);
    overflow: hidden;
    padding: 0;
  }
  .app-sidebar { display: grid; min-height: 0; grid-template-rows: auto auto minmax(0, 1fr) auto; padding: 1.25rem 0.875rem 1rem; border-right: 1px solid rgba(var(--v-border-color), var(--v-border-opacity)); background: rgb(var(--v-theme-surface)); }
  .app-sidebar .brand-lockup { min-height: 3.5rem; padding: 0 0.625rem; }
  .navigation-label { margin: 1.5rem 0.75rem 0.5rem; color: rgba(var(--v-theme-on-surface), 0.42); font-size: 0.625rem; font-weight: 700; letter-spacing: 0; }
  .desktop-navigation { display: grid; align-content: start; gap: 0.25rem; }
  .desktop-navigation__item { display: flex; width: 100%; min-height: 2.875rem; align-items: center; gap: 0.75rem; padding: 0.625rem 0.875rem; border: 0; border-radius: 0.375rem; color: rgba(var(--v-theme-on-surface), var(--v-medium-emphasis-opacity)); text-align: start; background: transparent; cursor: pointer; font: inherit; font-size: 0.8125rem; }
  .desktop-navigation__item:hover { color: rgb(var(--v-theme-on-surface)); background: rgba(var(--v-theme-on-surface), 0.035); }
  .desktop-navigation__item--active { color: rgb(var(--v-theme-primary)); background: rgba(var(--v-theme-primary), 0.12); font-weight: 650; }
  .desktop-navigation__item:focus-visible { outline: 2px solid rgb(var(--v-theme-primary)); outline-offset: 2px; }
  .sidebar-footer { display: flex; align-items: center; justify-content: space-between; gap: 0.5rem; margin: 0.75rem 0.625rem 0; padding-top: 0.875rem; border-top: 1px solid rgba(var(--v-border-color), var(--v-border-opacity)); color: rgba(var(--v-theme-on-surface), var(--v-medium-emphasis-opacity)); font-size: 0.6875rem; }
  .sidebar-footer strong { color: rgb(var(--v-theme-success)); font-weight: 600; }
  .app-main { display: grid; min-height: 0; grid-template-rows: auto minmax(0, 1fr); }
  .mobile-brandbar, .mobile-navigation { display: none; }
  .page-toolbar { min-height: 5rem; padding: 0.75rem 1.5rem; border-bottom: 1px solid rgba(var(--v-border-color), var(--v-border-opacity)); background: rgba(var(--v-theme-surface), 0.92); }
  .workbench-content { display: grid; min-height: 0; padding: 1.25rem 1.5rem 0; grid-template-rows: minmax(0, 1fr); }

  .workbench-window {
    block-size: 100%;
    min-height: 0;
  }

  .workbench-view {
    block-size: 100%;
    min-block-size: 0;
    min-inline-size: 0;
    overflow: hidden;
  }

  .workbench-window:not(.workbench-window--data-view) .workbench-view {
    overflow-y: auto;
    overscroll-behavior: contain;
    scrollbar-gutter: stable;
  }
}

@media (max-width: 959px) {
  .page-toolbar { min-height: 4.25rem; }
  .workbench-content { padding-inline: 1rem; }
}

@media (max-width: 37.5rem) {
  .mobile-brandbar, .page-toolbar { padding-inline: 0.75rem; }
  .toolbar-status { display: none; }
  .workbench-content { padding-inline: 0.75rem; }
  .workbench-view--data :deep(.view-shell) { padding: 0.75rem; }
}

@media (prefers-reduced-motion: reduce) {
  .subtitle-download-workbench *,
  .subtitle-download-workbench *::before,
  .subtitle-download-workbench *::after {
    scroll-behavior: auto !important;
    transition-duration: 0.01ms !important;
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
  }
}
</style>
