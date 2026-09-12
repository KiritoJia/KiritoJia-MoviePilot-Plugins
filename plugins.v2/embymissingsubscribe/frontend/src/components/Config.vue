<script setup lang="ts">
import { computed, inject, onMounted, ref, watch } from 'vue'

interface PluginApi {
  get<T = unknown>(path: string, options?: Record<string, unknown>): Promise<T>
}
interface ConfigModel {
  enabled?: boolean
  onlyonce?: boolean
  emby_url?: string
  user_id?: string
  api_key?: string
  cron?: string
  aired_only?: boolean
  timeout?: number
  plugin_id?: string
  [key: string]: unknown
}
interface Summary {
  success?: boolean
  finished_at?: string
  series?: number
  missing?: number
  subscriptions?: number
  existing_subscriptions?: number
  subscribe_failures?: number
  skipped?: number
  message?: string
}
interface Toast { success(message: string): unknown; error(message: string): unknown; info(message: string): unknown }

const props = withDefaults(defineProps<{ initialConfig?: ConfigModel; api?: PluginApi }>(), { initialConfig: () => ({}) })
const emit = defineEmits<{ save: [ConfigModel]; close: []; layout: [{ maxWidth: string }] }>()
const toast = inject<Toast | null>('moviepilot:toast', null)

const form = ref<Required<Pick<ConfigModel, 'enabled' | 'onlyonce' | 'emby_url' | 'user_id' | 'api_key' | 'cron' | 'aired_only' | 'timeout'>>>({
  enabled: false, onlyonce: false, emby_url: '', user_id: '', api_key: '', cron: '0 */6 * * *', aired_only: true, timeout: 20,
})
const saving = ref(false)
const scanning = ref(false)
const revealKey = ref(false)
const message = ref('')
const messageType = ref<'success' | 'error' | 'info'>('info')
const summary = ref<Summary | null>(null)

emit('layout', { maxWidth: '74rem' })
watch(() => props.initialConfig, applyConfig, { immediate: true, deep: true })

const ready = computed(() => Boolean(form.value.emby_url.trim() && form.value.user_id.trim() && form.value.api_key.trim()))
const canSave = computed(() => !saving.value && !scanning.value)
const pluginId = computed(() => String(props.initialConfig?.plugin_id || '').trim())
const statusLabel = computed(() => form.value.enabled ? '运行中' : '已停用')
const statusColor = computed(() => form.value.enabled ? 'success' : 'default')

onMounted(() => { void loadSummary() })

function applyConfig(value?: ConfigModel): void {
  const initial = value || {}
  form.value = {
    enabled: Boolean(initial.enabled),
    onlyonce: Boolean(initial.onlyonce),
    emby_url: String(initial.emby_url || ''),
    user_id: String(initial.user_id || ''),
    api_key: String(initial.api_key || ''),
    cron: String(initial.cron || '0 */6 * * *'),
    aired_only: initial.aired_only !== false,
    timeout: Number(initial.timeout || 20),
  }
  summary.value = (initial.last_summary as Summary | undefined) || null
}

async function loadSummary(): Promise<void> {
  if (!props.api || !pluginId.value) return
  try {
    summary.value = await props.api.get<Summary>(`plugin/${encodeURIComponent(pluginId.value)}/summary`)
  } catch {
    summary.value = null
  }
}

function save(): void {
  if ((form.value.enabled || form.value.onlyonce) && !ready.value) {
    setMessage('请先填写 Emby 地址、用户 ID 和 API Key。', 'error')
    return
  }
  saving.value = true
  emit('save', { ...props.initialConfig, ...form.value })
  setMessage('配置已提交，MoviePilot 正在应用。', 'success')
  window.setTimeout(() => { saving.value = false }, 700)
}

async function scanNow(): Promise<void> {
  if (!ready.value) {
    setMessage('请先填写完整的 Emby 连接信息。', 'error')
    return
  }
  emit('save', { ...props.initialConfig, ...form.value, onlyonce: true })
  setMessage('已提交一次性扫描，MoviePilot 将在后台执行。', 'info')
}

function setMessage(text: string, type: 'success' | 'error' | 'info'): void {
  message.value = text
  messageType.value = type
  if (type === 'success') toast?.success(text)
  if (type === 'error') toast?.error(text)
  if (type === 'info') toast?.info(text)
}
</script>

<template>
  <section class="emby-config">
    <header class="hero">
      <div class="hero__identity">
        <div class="hero__icon"><VIcon icon="mdi-television-play" size="26" /></div>
        <div>
          <div class="hero__crumb">MoviePilot <VIcon icon="mdi-chevron-right" size="14" /> 媒体自动化</div>
          <h1>Emby 缺集自动订阅</h1>
          <p>读取 Emby 媒体库，发现已播缺集后自动交给 MoviePilot 订阅。</p>
        </div>
      </div>
      <div class="hero__actions">
        <VChip :color="statusColor" variant="tonal" size="small" label>{{ statusLabel }}</VChip>
        <VBtn icon="mdi-close" variant="text" aria-label="关闭设置" @click="emit('close')" />
      </div>
    </header>

    <VAlert v-if="message" :type="messageType" variant="tonal" density="comfortable" closable class="notice" @click:close="message = ''">{{ message }}</VAlert>

    <form id="missing-form" class="workspace" @submit.prevent="save">
      <main class="content">
        <section class="panel">
          <div class="panel__heading"><div class="heading-icon blue"><VIcon icon="mdi-link-variant" /></div><div><h2>连接 Emby</h2><p>使用 Emby API 读取电视剧、季度和已存在的集数。</p></div></div>
          <div class="field-grid">
            <VTextField v-model="form.emby_url" label="Emby 地址" placeholder="http://192.168.1.20:8096" prepend-inner-icon="mdi-server-network" variant="outlined" density="comfortable" hide-details="auto" />
            <VTextField v-model="form.user_id" label="用户 ID" placeholder="Emby 用户 UUID" prepend-inner-icon="mdi-account-outline" variant="outlined" density="comfortable" hide-details="auto" />
            <VTextField v-model="form.api_key" :type="revealKey ? 'text' : 'password'" label="API Key" placeholder="输入 Emby API Key" prepend-inner-icon="mdi-key-outline" :append-inner-icon="revealKey ? 'mdi-eye-off-outline' : 'mdi-eye-outline'" variant="outlined" density="comfortable" hide-details="auto" @click:append-inner="revealKey = !revealKey" />
            <VTextField v-model.number="form.timeout" type="number" min="5" max="120" suffix="秒" label="请求超时" prepend-inner-icon="mdi-timer-outline" variant="outlined" density="comfortable" hide-details="auto" />
          </div>
        </section>

        <section class="panel">
          <div class="panel__heading"><div class="heading-icon green"><VIcon icon="mdi-radar" /></div><div><h2>扫描策略</h2><p>控制扫描周期以及哪些缺集可以进入订阅。</p></div></div>
          <div class="setting-list">
            <div class="setting-row"><div><strong>启用自动扫描</strong><span>按设定周期检查 Emby 媒体库</span></div><VSwitch v-model="form.enabled" color="primary" hide-details inset /></div>
            <div class="setting-row"><div><strong>只订阅已播缺集</strong><span>忽略 TMDB 中尚未播出的集数</span></div><VSwitch v-model="form.aired_only" color="primary" hide-details inset /></div>
            <div class="setting-row"><div><strong>扫描周期</strong><span>使用标准 Cron 表达式，默认每 6 小时</span></div><VTextField v-model="form.cron" class="compact-field" label="Cron" placeholder="0 */6 * * *" variant="outlined" density="compact" hide-details /></div>
          </div>
        </section>

        <section class="panel panel--command">
          <div class="panel__heading"><div class="heading-icon amber"><VIcon icon="mdi-lightning-bolt-outline" /></div><div><h2>立即执行</h2><p>保存配置后，可以立即扫描一次整个 Emby 媒体库。</p></div></div>
          <div class="command-row"><div class="command-state"><VIcon icon="mdi-database-search-outline" color="primary" size="24" /><span>扫描完成后只会为缺集季度创建订阅，不会重复创建。</span></div><VBtn color="primary" variant="tonal" prepend-icon="mdi-play" :loading="scanning" @click="scanNow">立即扫描</VBtn></div>
        </section>
      </main>

      <aside class="summary">
        <div class="summary__title"><VIcon icon="mdi-chart-box-outline" color="primary" /><h2>运行概览</h2></div>
        <div class="metric-grid">
          <div class="metric"><span>剧集</span><strong>{{ summary?.series ?? '--' }}</strong></div>
          <div class="metric"><span>缺集</span><strong>{{ summary?.missing ?? '--' }}</strong></div>
          <div class="metric"><span>新增订阅</span><strong>{{ summary?.subscriptions ?? '--' }}</strong></div>
          <div class="metric"><span>已有订阅</span><strong>{{ summary?.existing_subscriptions ?? '--' }}</strong></div>
        </div>
        <div class="summary__divider" />
        <div class="summary__item"><VIcon icon="mdi-clock-outline" /><span>上次扫描</span><strong>{{ summary?.finished_at || '尚未执行' }}</strong></div>
        <div class="summary__item"><VIcon icon="mdi-alert-circle-outline" /><span>扫描跳过</span><strong>{{ summary?.skipped ?? '--' }}</strong></div>
        <div class="summary__item"><VIcon icon="mdi-close-circle-outline" /><span>订阅失败</span><strong>{{ summary?.subscribe_failures ?? '--' }}</strong></div>
        <VAlert v-if="!ready" type="warning" variant="tonal" density="compact" class="summary__alert">填写完整连接信息后才能开始扫描。</VAlert>
        <div class="summary__tip"><VIcon icon="mdi-information-outline" size="18" /><span>插件只负责识别缺集和创建订阅，后续搜索、下载、整理由 MoviePilot 原生流程完成。</span></div>
      </aside>
    </form>

    <footer class="footer-actions"><VBtn variant="text" prepend-icon="mdi-close" @click="emit('close')">取消</VBtn><VBtn color="primary" variant="flat" prepend-icon="mdi-content-save-outline" :loading="saving" :disabled="!canSave" type="submit" form="missing-form">保存配置</VBtn></footer>
  </section>
</template>

<style scoped>
:global(.v-application) { background: transparent !important; }
.emby-config { --ink: rgb(var(--v-theme-on-surface)); --muted: rgba(var(--v-theme-on-surface), .62); --line: rgba(var(--v-theme-on-surface), .1); color: var(--ink); min-height: 100%; padding: 18px 22px 24px; background: rgb(var(--v-theme-surface)); }
.hero { display: flex; justify-content: space-between; align-items: flex-start; gap: 20px; padding: 8px 2px 24px; border-bottom: 1px solid var(--line); }
.hero__identity { display: flex; gap: 14px; align-items: flex-start; }.hero__icon { width: 48px; height: 48px; display: grid; place-items: center; border-radius: 14px; color: rgb(var(--v-theme-primary)); background: rgba(var(--v-theme-primary), .12); }.hero__crumb { display: flex; align-items: center; gap: 3px; color: var(--muted); font-size: 12px; margin: 2px 0 4px; }.hero h1 { font-size: 24px; line-height: 1.2; margin: 0; letter-spacing: 0; }.hero p { color: var(--muted); margin: 7px 0 0; font-size: 13px; }.hero__actions { display: flex; align-items: center; gap: 8px; }
.notice { margin: 18px 0 0; }.workspace { display: grid; grid-template-columns: minmax(0, 1fr) 290px; gap: 18px; padding-top: 18px; }.content { display: grid; gap: 14px; min-width: 0; }.panel, .summary { border: 1px solid var(--line); border-radius: 10px; background: rgba(var(--v-theme-surface), .72); }.panel { padding: 20px; }.panel__heading { display: flex; gap: 12px; align-items: flex-start; margin-bottom: 20px; }.panel__heading h2, .summary h2 { font-size: 16px; line-height: 1.3; margin: 0; letter-spacing: 0; }.panel__heading p { color: var(--muted); font-size: 12px; margin: 4px 0 0; }.heading-icon { width: 34px; height: 34px; flex: 0 0 34px; display: grid; place-items: center; border-radius: 9px; }.heading-icon.blue { color: #3b82f6; background: rgba(59,130,246,.12); }.heading-icon.green { color: #22a06b; background: rgba(34,160,107,.12); }.heading-icon.amber { color: #d99000; background: rgba(217,144,0,.13); }.field-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }.setting-list { display: grid; }.setting-row { display: flex; justify-content: space-between; align-items: center; gap: 18px; min-height: 62px; padding: 12px 0; border-top: 1px solid var(--line); }.setting-row:first-child { border-top: 0; padding-top: 0; }.setting-row:last-child { padding-bottom: 0; }.setting-row strong, .setting-row span { display: block; }.setting-row strong { font-size: 13px; }.setting-row span { color: var(--muted); font-size: 12px; margin-top: 4px; }.compact-field { max-width: 210px; min-width: 160px; }.panel--command { padding-bottom: 16px; }.command-row { display: flex; justify-content: space-between; align-items: center; gap: 14px; padding: 13px 14px; border: 1px dashed rgba(var(--v-theme-primary), .3); border-radius: 8px; background: rgba(var(--v-theme-primary), .04); }.command-state { display: flex; align-items: center; gap: 10px; color: var(--muted); font-size: 12px; }
.summary { align-self: start; padding: 18px; position: sticky; top: 12px; }.summary__title { display: flex; align-items: center; gap: 8px; padding-bottom: 16px; border-bottom: 1px solid var(--line); }.metric-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; padding: 16px 0; }.metric { padding: 12px; border-radius: 8px; background: rgba(var(--v-theme-on-surface), .04); }.metric span { color: var(--muted); font-size: 11px; display: block; }.metric strong { display: block; font-size: 22px; font-weight: 600; margin-top: 5px; }.summary__divider { border-top: 1px solid var(--line); }.summary__item { display: grid; grid-template-columns: 20px 1fr; gap: 7px; padding: 12px 0; border-bottom: 1px solid var(--line); font-size: 12px; }.summary__item span { color: var(--muted); }.summary__item strong { grid-column: 2; font-weight: 500; overflow-wrap: anywhere; }.summary__alert { margin-top: 16px; }.summary__tip { display: flex; gap: 8px; color: var(--muted); font-size: 11px; line-height: 1.55; margin-top: 16px; }.footer-actions { display: flex; justify-content: flex-end; gap: 8px; padding-top: 18px; }
@media (max-width: 820px) { .emby-config { padding: 14px 12px 20px; }.hero { padding-bottom: 18px; }.hero h1 { font-size: 20px; }.hero p { max-width: 390px; }.workspace { grid-template-columns: 1fr; }.summary { position: static; }.field-grid { grid-template-columns: 1fr; }.command-row { align-items: flex-start; flex-direction: column; }.compact-field { max-width: none; width: 100%; }.setting-row { align-items: flex-start; }.setting-row :deep(.v-input) { flex: 0 0 auto; }.footer-actions { position: sticky; bottom: 0; padding: 12px 0 0; background: rgb(var(--v-theme-surface)); } }
</style>
