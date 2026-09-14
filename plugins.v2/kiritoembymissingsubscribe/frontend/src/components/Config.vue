<script setup lang="ts">
import { computed, inject, onMounted, ref, watch } from 'vue'

interface PluginApi { get<T = unknown>(path: string, options?: Record<string, unknown>): Promise<T>; post<T = unknown>(path: string, payload?: unknown, options?: Record<string, unknown>): Promise<T> }
interface SubscriptionRecord { key?: string; name?: string; year?: string; season?: number; missing?: number[]; poster?: string; status?: string; updated_at?: string }
interface Summary {
  success?: boolean; finished_at?: string; series?: number; missing?: number; subscriptions?: number
  existing_subscriptions?: number; subscribe_failures?: number; skipped?: number; message?: string
  subscription_history?: SubscriptionRecord[]
}
interface ConfigModel {
  enabled?: boolean; onlyonce?: boolean; emby_url?: string; user_id?: string; api_key?: string
  cron?: string; aired_only?: boolean; timeout?: number; plugin_id?: string; last_summary?: Summary
  notify_enabled?: boolean; notify_on_start?: boolean; notify_on_complete?: boolean; notify_new?: boolean
  notify_existing?: boolean; notify_failure?: boolean; notify_only_changes?: boolean
  [key: string]: unknown
}
interface Toast { success(message: string): unknown; error(message: string): unknown; info(message: string): unknown }

const props = withDefaults(defineProps<{ initialConfig?: ConfigModel; api?: PluginApi }>(), { initialConfig: () => ({}) })
const emit = defineEmits<{ save: [ConfigModel]; close: []; layout: [{ maxWidth: string }] }>()
const toast = inject<Toast | null>('moviepilot:toast', null)
const form = ref({
  enabled: false, onlyonce: false, emby_url: '', user_id: '', api_key: '', cron: '0 */6 * * *', aired_only: true, timeout: 20,
  notify_enabled: true, notify_on_start: false, notify_on_complete: true, notify_new: true,
  notify_existing: false, notify_failure: true, notify_only_changes: true,
})
const saving = ref(false)
const scanning = ref(false)
const testingNotify = ref(false)
const revealKey = ref(false)
const message = ref('')
const messageType = ref<'success' | 'error' | 'info'>('info')
const summary = ref<Summary | null>(null)

emit('layout', { maxWidth: '78rem' })
watch(() => props.initialConfig, applyConfig, { immediate: true, deep: true })
const ready = computed(() => Boolean(form.value.emby_url.trim() && form.value.user_id.trim() && form.value.api_key.trim()))
const canSave = computed(() => !saving.value && !scanning.value)
const pluginId = computed(() => String(props.initialConfig?.plugin_id || '').trim())
const statusLabel = computed(() => form.value.enabled ? '自动扫描已启用' : '自动扫描已停用')
const statusColor = computed(() => form.value.enabled ? 'success' : 'default')
const history = computed(() => summary.value?.subscription_history || [])

onMounted(() => { void loadSummary() })

function applyConfig(value?: ConfigModel): void {
  const initial = value || {}
  form.value = {
    enabled: Boolean(initial.enabled), onlyonce: Boolean(initial.onlyonce), emby_url: String(initial.emby_url || ''),
    user_id: String(initial.user_id || ''), api_key: String(initial.api_key || ''), cron: String(initial.cron || '0 */6 * * *'),
    aired_only: initial.aired_only !== false, timeout: Number(initial.timeout || 20),
    notify_enabled: initial.notify_enabled !== false, notify_on_start: Boolean(initial.notify_on_start),
    notify_on_complete: initial.notify_on_complete !== false, notify_new: initial.notify_new !== false,
    notify_existing: Boolean(initial.notify_existing), notify_failure: initial.notify_failure !== false,
    notify_only_changes: initial.notify_only_changes !== false,
  }
  summary.value = initial.last_summary || null
}

async function loadSummary(): Promise<void> {
  if (!props.api || !pluginId.value) return
  try { summary.value = await props.api.get<Summary>(`plugin/${encodeURIComponent(pluginId.value)}/summary`) } catch { summary.value = null }
}

function save(): void {
  if ((form.value.enabled || form.value.onlyonce) && !ready.value) { setMessage('请先填写 Emby 地址、用户 ID 和 API Key。', 'error'); return }
  saving.value = true
  emit('save', { ...props.initialConfig, ...form.value })
  setMessage('配置已提交，MoviePilot 正在应用。', 'success')
  window.setTimeout(() => { saving.value = false }, 700)
}

function scanNow(): void {
  if (!ready.value) { setMessage('请先填写完整的 Emby 连接信息。', 'error'); return }
  scanning.value = true
  emit('save', { ...props.initialConfig, ...form.value, onlyonce: true })
  setMessage('已提交一次性扫描，完成后这里会显示订阅记录。', 'info')
  window.setTimeout(() => { scanning.value = false; void loadSummary() }, 1500)
}

async function testNotification(): Promise<void> {
  if (!props.api || testingNotify.value) return
  testingNotify.value = true
  try {
    const result = await props.api.post<{ success?: boolean; message?: string }>(`plugin/${encodeURIComponent(pluginId.value)}/test-notify`)
    setMessage(result?.message || '测试通知已提交。', result?.success === false ? 'error' : 'success')
  } catch (cause) {
    setMessage(cause instanceof Error ? cause.message : '测试通知失败。', 'error')
  } finally {
    testingNotify.value = false
  }
}

function formatMissing(missing?: number[]): string { return missing?.length ? missing.map(item => `E${String(item).padStart(2, '0')}`).join('、') : '无缺集信息' }
function formatTime(value?: string): string { return value ? value.replace('T', ' ').replace(/:[0-9]{2}$/, '') : '尚未执行' }
function setMessage(text: string, type: 'success' | 'error' | 'info'): void {
  message.value = text; messageType.value = type
  if (type === 'success') toast?.success(text)
  if (type === 'error') toast?.error(text)
  if (type === 'info') toast?.info(text)
}
</script>

<template>
  <section class="emby-config">
    <header class="topbar">
      <div class="brandline"><div class="brandmark"><VIcon icon="mdi-television-play" size="24" /></div><div class="eyebrow">EMBY / MISSING EPISODES</div></div>
      <div class="topbar__actions"><VChip :color="statusColor" variant="tonal" size="small" label>{{ statusLabel }}</VChip><VBtn icon="mdi-close" variant="text" aria-label="关闭设置" @click="emit('close')" /></div>
    </header>

    <div class="intro"><div><h1>Emby 缺集自动订阅</h1><p>扫描 Emby 媒体库，发现已播缺集后自动创建 MoviePilot 订阅。</p></div><div class="last-run"><span>最近扫描</span><strong>{{ formatTime(summary?.finished_at) }}</strong></div></div>
    <VAlert v-if="message" :type="messageType" variant="tonal" density="comfortable" closable class="notice" @click:close="message = ''">{{ message }}</VAlert>

    <div class="stats-strip" aria-label="扫描统计">
      <div class="stat"><span>媒体剧集</span><strong>{{ summary?.series ?? '--' }}</strong></div>
      <div class="stat"><span>发现缺集</span><strong>{{ summary?.missing ?? '--' }}</strong></div>
      <div class="stat"><span>新增订阅</span><strong class="positive">{{ summary?.subscriptions ?? '--' }}</strong></div>
      <div class="stat"><span>已有订阅</span><strong>{{ summary?.existing_subscriptions ?? '--' }}</strong></div>
      <div class="stat"><span>扫描跳过</span><strong>{{ summary?.skipped ?? '--' }}</strong></div>
    </div>

    <form id="missing-form" class="workspace" @submit.prevent="save">
      <section class="panel">
        <div class="section-head"><div class="section-index">01</div><div><h2>连接 Emby</h2><p>填写 Emby 服务信息，用于读取电视剧和季度的实际集数。</p></div></div>
        <div class="field-grid field-grid--connection">
          <VTextField v-model="form.emby_url" label="Emby 地址" placeholder="http://192.168.1.20:8096" prepend-inner-icon="mdi-server-network" variant="outlined" density="comfortable" hide-details="auto" />
          <VTextField v-model="form.user_id" label="用户 ID" placeholder="Emby 用户 UUID" prepend-inner-icon="mdi-account-outline" variant="outlined" density="comfortable" hide-details="auto" />
          <VTextField v-model="form.api_key" :type="revealKey ? 'text' : 'password'" label="API Key" placeholder="输入 Emby API Key" prepend-inner-icon="mdi-key-outline" :append-inner-icon="revealKey ? 'mdi-eye-off-outline' : 'mdi-eye-outline'" variant="outlined" density="comfortable" hide-details="auto" @click:append-inner="revealKey = !revealKey" />
          <VTextField v-model.number="form.timeout" type="number" min="5" max="120" suffix="秒" label="请求超时" prepend-inner-icon="mdi-timer-outline" variant="outlined" density="comfortable" hide-details="auto" />
        </div>
      </section>

      <section class="panel">
        <div class="section-head"><div class="section-index">02</div><div><h2>扫描规则</h2><p>控制自动扫描的开关、时间以及缺集判定范围。</p></div></div>
        <div class="rule-grid">
          <div class="rule-row"><div class="rule-icon"><VIcon icon="mdi-radar" size="20" /></div><div class="rule-copy"><strong>启用自动扫描</strong><span>按设定周期检查 Emby 媒体库</span></div><VSwitch v-model="form.enabled" color="primary" hide-details inset /></div>
          <div class="rule-row"><div class="rule-icon"><VIcon icon="mdi-calendar-check-outline" size="20" /></div><div class="rule-copy"><strong>只订阅已播缺集</strong><span>忽略 TMDB 中尚未播出的集数</span></div><VSwitch v-model="form.aired_only" color="primary" hide-details inset /></div>
        </div>
        <div class="field-grid field-grid--rules">
          <VTextField v-model="form.cron" label="扫描周期 Cron" placeholder="0 */6 * * *" prepend-inner-icon="mdi-clock-outline" variant="outlined" density="comfortable" hide-details="auto" />
        </div>
      </section>

      <section class="panel notification-panel">
        <div class="section-head"><div class="section-index">03</div><div><h2>通知设置</h2><p>使用 MoviePilot 已配置的全局通知渠道，不会发送 Emby API Key。</p></div><VBtn class="test-notify" color="primary" variant="tonal" size="small" prepend-icon="mdi-bell-check-outline" :loading="testingNotify" :disabled="!props.api" @click="testNotification">测试推送</VBtn></div>
        <div class="rule-grid notification-grid">
          <div class="rule-row"><div class="rule-icon"><VIcon icon="mdi-bell-outline" size="20" /></div><div class="rule-copy"><strong>启用通知</strong><span>允许扫描结果发送到全局通知渠道</span></div><VSwitch v-model="form.notify_enabled" color="primary" hide-details inset /></div>
          <div class="rule-row"><div class="rule-icon"><VIcon icon="mdi-clipboard-check-outline" size="20" /></div><div class="rule-copy"><strong>扫描完成汇总</strong><span>扫描有变化或失败时发送结果</span></div><VSwitch v-model="form.notify_on_complete" color="primary" hide-details inset :disabled="!form.notify_enabled" /></div>
          <div class="rule-row"><div class="rule-icon"><VIcon icon="mdi-plus-box-outline" size="20" /></div><div class="rule-copy"><strong>新建订阅提醒</strong><span>列出本次新创建的剧集和缺集</span></div><VSwitch v-model="form.notify_new" color="primary" hide-details inset :disabled="!form.notify_enabled" /></div>
          <div class="rule-row"><div class="rule-icon"><VIcon icon="mdi-sync-circle-outline" size="20" /></div><div class="rule-copy"><strong>复用订阅提醒</strong><span>列出已经存在的订阅</span></div><VSwitch v-model="form.notify_existing" color="primary" hide-details inset :disabled="!form.notify_enabled" /></div>
          <div class="rule-row"><div class="rule-icon"><VIcon icon="mdi-alert-circle-outline" size="20" /></div><div class="rule-copy"><strong>失败提醒</strong><span>列出创建订阅失败的剧集和原因</span></div><VSwitch v-model="form.notify_failure" color="primary" hide-details inset :disabled="!form.notify_enabled" /></div>
          <div class="rule-row"><div class="rule-icon"><VIcon icon="mdi-radar" size="20" /></div><div class="rule-copy"><strong>开始扫描提醒</strong><span>扫描开始时先发送一条提示</span></div><VSwitch v-model="form.notify_on_start" color="primary" hide-details inset :disabled="!form.notify_enabled" /></div>
        </div>
        <VSwitch v-model="form.notify_only_changes" color="primary" class="changes-switch" label="仅在有新订阅、失败或其他变化时发送汇总" hide-details inset :disabled="!form.notify_enabled || !form.notify_on_complete" />
      </section>

      <section class="action-panel"><div class="action-copy"><div class="action-icon"><VIcon icon="mdi-play-circle-outline" size="24" /></div><div><h2>立即扫描媒体库</h2><p>提交后在后台读取 Emby，全量检查缺集并创建订阅，不会重复创建已有订阅。</p></div></div><VBtn color="primary" variant="flat" prepend-icon="mdi-play" :loading="scanning" :disabled="!ready" @click="scanNow">立即扫描</VBtn></section>

      <section class="panel history-panel">
        <div class="history-head"><div class="section-head section-head--inline"><div class="section-index">04</div><div><h2>订阅历史</h2><p>展示最近实际创建或复用的订阅，包含对应媒体海报和缺集。</p></div></div><VBtn icon="mdi-refresh" variant="text" aria-label="刷新订阅历史" :loading="scanning" @click="loadSummary" /></div>
        <div v-if="!history.length" class="empty-history"><VIcon icon="mdi-filmstrip-off" size="30" /><span>扫描后，订阅记录会显示在这里</span></div>
        <div v-else class="history-list">
          <article v-for="item in history" :key="item.key || `${item.name}-${item.season}`" class="history-item">
            <VImg v-if="item.poster" :src="item.poster" class="poster" cover :alt="item.name || '媒体海报'" /><div v-else class="poster poster--empty"><VIcon icon="mdi-movie-open-outline" size="24" /></div>
            <div class="history-main"><div class="history-title"><strong>{{ item.name || '未知剧集' }}</strong><VChip size="x-small" :color="item.status === '已创建' ? 'success' : 'default'" variant="tonal" label>{{ item.status || '已处理' }}</VChip></div><span class="history-meta">{{ item.year || '年份未知' }} · 第 {{ item.season || '-' }} 季 · {{ formatMissing(item.missing) }}</span><span class="history-time">处理于 {{ formatTime(item.updated_at) }}</span></div>
          </article>
        </div>
      </section>
    </form>

    <footer class="footer-actions"><VBtn variant="text" prepend-icon="mdi-close" @click="emit('close')">取消</VBtn><VBtn color="primary" variant="flat" prepend-icon="mdi-content-save-outline" :loading="saving" :disabled="!canSave" type="submit" form="missing-form">保存配置</VBtn></footer>
  </section>
</template>

<style scoped>
:global(.v-application) { background: transparent !important; }
.emby-config { --ink: rgb(var(--v-theme-on-surface)); --muted: rgba(var(--v-theme-on-surface), .62); --line: rgba(var(--v-theme-on-surface), .11); --soft: rgba(var(--v-theme-on-surface), .035); color: var(--ink); min-height: 100%; padding: 18px 24px 24px; background: rgb(var(--v-theme-surface)); }
.topbar, .intro, .history-head, .footer-actions, .action-panel, .section-head, .history-title { display: flex; align-items: center; }.topbar { justify-content: space-between; min-height: 38px; }.brandline, .topbar__actions { display: flex; align-items: center; gap: 10px; }.brandmark { width: 38px; height: 38px; display: grid; place-items: center; border: 1px solid rgba(var(--v-theme-primary), .24); border-radius: 10px; color: rgb(var(--v-theme-primary)); background: rgba(var(--v-theme-primary), .09); }.eyebrow { color: var(--muted); font-size: 11px; font-weight: 700; letter-spacing: .08em; }
.intro { justify-content: space-between; gap: 24px; padding: 24px 0 20px; border-bottom: 1px solid var(--line); }.intro h1 { margin: 0; font-size: 25px; line-height: 1.2; letter-spacing: 0; }.intro p { margin: 7px 0 0; color: var(--muted); font-size: 13px; }.last-run { display: grid; gap: 4px; text-align: right; color: var(--muted); font-size: 11px; }.last-run strong { color: var(--ink); font-size: 13px; font-weight: 500; }.notice { margin-top: 16px; }
.stats-strip { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 1px; margin-top: 16px; border: 1px solid var(--line); background: var(--line); }.stat { min-height: 76px; padding: 14px 16px; background: rgb(var(--v-theme-surface)); }.stat span { display: block; color: var(--muted); font-size: 11px; }.stat strong { display: block; margin-top: 7px; font-size: 22px; font-weight: 600; }.stat .positive { color: rgb(var(--v-theme-success)); }
.workspace { display: grid; gap: 14px; padding-top: 16px; }.panel { padding: 20px; border: 1px solid var(--line); background: rgb(var(--v-theme-surface)); }.section-head { align-items: flex-start; gap: 12px; }.section-index { color: rgb(var(--v-theme-primary)); font-size: 12px; font-weight: 700; line-height: 1.5; }.section-head h2, .action-copy h2 { margin: 0; font-size: 16px; line-height: 1.3; letter-spacing: 0; }.section-head p, .action-copy p { margin: 4px 0 0; color: var(--muted); font-size: 12px; }.field-grid { display: grid; gap: 14px; margin-top: 20px; }.field-grid--connection, .field-grid--rules { grid-template-columns: repeat(2, minmax(0, 1fr)); }.field-grid--rules { margin-top: 16px; }.rule-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; margin-top: 20px; }.rule-row { display: flex; align-items: center; gap: 10px; min-height: 70px; padding: 12px 14px; border: 1px solid var(--line); background: var(--soft); }.rule-icon { display: grid; place-items: center; width: 34px; height: 34px; flex: 0 0 34px; color: rgb(var(--v-theme-primary)); border-radius: 8px; background: rgba(var(--v-theme-primary), .1); }.rule-copy { min-width: 0; flex: 1; }.rule-copy strong, .rule-copy span { display: block; }.rule-copy strong { font-size: 13px; }.rule-copy span { margin-top: 4px; color: var(--muted); font-size: 11px; }
.notification-panel .section-head { align-items: flex-start; }.notification-panel .section-head > div:nth-child(2) { flex: 1; }.test-notify { flex: 0 0 auto; }.notification-grid { margin-top: 20px; }.changes-switch { margin-top: 14px; }
.action-panel { justify-content: space-between; gap: 18px; padding: 18px 20px; border: 1px solid rgba(var(--v-theme-primary), .22); background: rgba(var(--v-theme-primary), .045); }.action-copy { display: flex; align-items: flex-start; gap: 12px; }.action-icon { display: grid; place-items: center; width: 38px; height: 38px; flex: 0 0 38px; color: rgb(var(--v-theme-primary)); border-radius: 9px; background: rgba(var(--v-theme-primary), .12); }
.history-head { justify-content: space-between; gap: 12px; }.section-head--inline { flex: 1; }.empty-history { display: grid; place-items: center; gap: 8px; min-height: 140px; margin-top: 18px; color: var(--muted); font-size: 12px; border: 1px dashed var(--line); background: var(--soft); }.history-list { display: grid; gap: 8px; margin-top: 18px; }.history-item { display: flex; align-items: center; gap: 12px; min-width: 0; padding: 10px; border: 1px solid var(--line); background: var(--soft); }.poster { width: 48px; height: 68px; flex: 0 0 48px; border-radius: 5px; background: rgba(var(--v-theme-on-surface), .08); }.poster--empty { display: grid; place-items: center; color: var(--muted); }.history-main { min-width: 0; flex: 1; }.history-title { gap: 8px; min-width: 0; }.history-title strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13px; }.history-meta, .history-time { display: block; color: var(--muted); font-size: 11px; }.history-meta { margin-top: 6px; }.history-time { margin-top: 4px; font-size: 10px; }.footer-actions { justify-content: flex-end; gap: 8px; padding-top: 16px; }
@media (max-width: 820px) { .emby-config { padding: 14px 12px 20px; }.topbar__actions .v-chip { max-width: 150px; }.intro { align-items: flex-start; flex-direction: column; gap: 12px; }.intro h1 { font-size: 21px; }.last-run { text-align: left; }.stats-strip { grid-template-columns: repeat(2, minmax(0, 1fr)); }.stat:last-child { grid-column: span 2; }.field-grid--connection, .field-grid--rules, .rule-grid { grid-template-columns: 1fr; }.action-panel { align-items: flex-start; flex-direction: column; }.action-panel .v-btn { width: 100%; }.footer-actions { position: sticky; bottom: 0; z-index: 2; padding: 12px 0 0; background: rgb(var(--v-theme-surface)); } }
</style>
