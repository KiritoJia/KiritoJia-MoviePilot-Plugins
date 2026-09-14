import { importShared } from './__federation_fn_import-JrT3xvdd.js';

const {defineComponent:_defineComponent} = await importShared('vue');

const {resolveComponent:_resolveComponent,createVNode:_createVNode,createElementVNode:_createElementVNode,toDisplayString:_toDisplayString,createTextVNode:_createTextVNode,withCtx:_withCtx,openBlock:_openBlock,createBlock:_createBlock,createCommentVNode:_createCommentVNode,createElementBlock:_createElementBlock,renderList:_renderList,Fragment:_Fragment,withModifiers:_withModifiers} = await importShared('vue');

const _hoisted_1 = { class: "emby-config" };
const _hoisted_2 = { class: "topbar" };
const _hoisted_3 = { class: "brandline" };
const _hoisted_4 = { class: "brandmark" };
const _hoisted_5 = { class: "topbar__actions" };
const _hoisted_6 = { class: "intro" };
const _hoisted_7 = { class: "last-run" };
const _hoisted_8 = {
  class: "stats-strip",
  "aria-label": "扫描统计"
};
const _hoisted_9 = { class: "stat" };
const _hoisted_10 = { class: "stat" };
const _hoisted_11 = { class: "stat" };
const _hoisted_12 = { class: "positive" };
const _hoisted_13 = { class: "stat" };
const _hoisted_14 = { class: "stat" };
const _hoisted_15 = { class: "panel" };
const _hoisted_16 = { class: "field-grid field-grid--connection" };
const _hoisted_17 = { class: "panel" };
const _hoisted_18 = { class: "rule-grid" };
const _hoisted_19 = { class: "rule-row" };
const _hoisted_20 = { class: "rule-icon" };
const _hoisted_21 = { class: "rule-row" };
const _hoisted_22 = { class: "rule-icon" };
const _hoisted_23 = { class: "field-grid field-grid--rules" };
const _hoisted_24 = { class: "panel notification-panel" };
const _hoisted_25 = { class: "section-head" };
const _hoisted_26 = { class: "rule-grid notification-grid" };
const _hoisted_27 = { class: "rule-row" };
const _hoisted_28 = { class: "rule-icon" };
const _hoisted_29 = { class: "rule-row" };
const _hoisted_30 = { class: "rule-icon" };
const _hoisted_31 = { class: "rule-row" };
const _hoisted_32 = { class: "rule-icon" };
const _hoisted_33 = { class: "rule-row" };
const _hoisted_34 = { class: "rule-icon" };
const _hoisted_35 = { class: "rule-row" };
const _hoisted_36 = { class: "rule-icon" };
const _hoisted_37 = { class: "rule-row" };
const _hoisted_38 = { class: "rule-icon" };
const _hoisted_39 = { class: "action-panel" };
const _hoisted_40 = { class: "action-copy" };
const _hoisted_41 = { class: "action-icon" };
const _hoisted_42 = { class: "panel history-panel" };
const _hoisted_43 = { class: "history-head" };
const _hoisted_44 = {
  key: 0,
  class: "empty-history"
};
const _hoisted_45 = {
  key: 1,
  class: "history-list"
};
const _hoisted_46 = {
  key: 1,
  class: "poster poster--empty"
};
const _hoisted_47 = { class: "history-main" };
const _hoisted_48 = { class: "history-title" };
const _hoisted_49 = { class: "history-meta" };
const _hoisted_50 = { class: "history-time" };
const _hoisted_51 = { class: "footer-actions" };
const {computed,inject,onMounted,ref,watch} = await importShared('vue');

const _sfc_main = /* @__PURE__ */ _defineComponent({
  __name: "Config",
  props: {
    initialConfig: { default: () => ({}) },
    api: {}
  },
  emits: ["save", "close", "layout"],
  setup(__props, { emit: __emit }) {
    const props = __props;
    const emit = __emit;
    const toast = inject("moviepilot:toast", null);
    const form = ref({
      enabled: false,
      onlyonce: false,
      emby_url: "",
      user_id: "",
      api_key: "",
      cron: "0 */6 * * *",
      aired_only: true,
      timeout: 20,
      notify_enabled: true,
      notify_on_start: false,
      notify_on_complete: true,
      notify_new: true,
      notify_existing: false,
      notify_failure: true,
      notify_only_changes: true
    });
    const saving = ref(false);
    const scanning = ref(false);
    const testingNotify = ref(false);
    const revealKey = ref(false);
    const message = ref("");
    const messageType = ref("info");
    const summary = ref(null);
    emit("layout", { maxWidth: "78rem" });
    watch(() => props.initialConfig, applyConfig, { immediate: true, deep: true });
    const ready = computed(() => Boolean(form.value.emby_url.trim() && form.value.user_id.trim() && form.value.api_key.trim()));
    const canSave = computed(() => !saving.value && !scanning.value);
    const pluginId = computed(() => String(props.initialConfig?.plugin_id || "").trim());
    const statusLabel = computed(() => form.value.enabled ? "自动扫描已启用" : "自动扫描已停用");
    const statusColor = computed(() => form.value.enabled ? "success" : "default");
    const history = computed(() => summary.value?.subscription_history || []);
    onMounted(() => {
      void loadSummary();
    });
    function applyConfig(value) {
      const initial = value || {};
      form.value = {
        enabled: Boolean(initial.enabled),
        onlyonce: Boolean(initial.onlyonce),
        emby_url: String(initial.emby_url || ""),
        user_id: String(initial.user_id || ""),
        api_key: String(initial.api_key || ""),
        cron: String(initial.cron || "0 */6 * * *"),
        aired_only: initial.aired_only !== false,
        timeout: Number(initial.timeout || 20),
        notify_enabled: initial.notify_enabled !== false,
        notify_on_start: Boolean(initial.notify_on_start),
        notify_on_complete: initial.notify_on_complete !== false,
        notify_new: initial.notify_new !== false,
        notify_existing: Boolean(initial.notify_existing),
        notify_failure: initial.notify_failure !== false,
        notify_only_changes: initial.notify_only_changes !== false
      };
      summary.value = initial.last_summary || null;
    }
    async function loadSummary() {
      if (!props.api || !pluginId.value) return;
      try {
        summary.value = await props.api.get(`plugin/${encodeURIComponent(pluginId.value)}/summary`);
      } catch {
        summary.value = null;
      }
    }
    function save() {
      if ((form.value.enabled || form.value.onlyonce) && !ready.value) {
        setMessage("请先填写 Emby 地址、用户 ID 和 API Key。", "error");
        return;
      }
      saving.value = true;
      emit("save", { ...props.initialConfig, ...form.value });
      setMessage("配置已提交，MoviePilot 正在应用。", "success");
      window.setTimeout(() => {
        saving.value = false;
      }, 700);
    }
    function scanNow() {
      if (!ready.value) {
        setMessage("请先填写完整的 Emby 连接信息。", "error");
        return;
      }
      scanning.value = true;
      emit("save", { ...props.initialConfig, ...form.value, onlyonce: true });
      setMessage("已提交一次性扫描，完成后这里会显示订阅记录。", "info");
      window.setTimeout(() => {
        scanning.value = false;
        void loadSummary();
      }, 1500);
    }
    async function testNotification() {
      if (!props.api || testingNotify.value) return;
      testingNotify.value = true;
      try {
        const result = await props.api.post(`plugin/${encodeURIComponent(pluginId.value)}/test-notify`);
        setMessage(result?.message || "测试通知已提交。", result?.success === false ? "error" : "success");
      } catch (cause) {
        setMessage(cause instanceof Error ? cause.message : "测试通知失败。", "error");
      } finally {
        testingNotify.value = false;
      }
    }
    function formatMissing(missing) {
      return missing?.length ? missing.map((item) => `E${String(item).padStart(2, "0")}`).join("、") : "无缺集信息";
    }
    function formatTime(value) {
      return value ? value.replace("T", " ").replace(/:[0-9]{2}$/, "") : "尚未执行";
    }
    function setMessage(text, type) {
      message.value = text;
      messageType.value = type;
      if (type === "success") toast?.success(text);
      if (type === "error") toast?.error(text);
      if (type === "info") toast?.info(text);
    }
    return (_ctx, _cache) => {
      const _component_VIcon = _resolveComponent("VIcon");
      const _component_VChip = _resolveComponent("VChip");
      const _component_VBtn = _resolveComponent("VBtn");
      const _component_VAlert = _resolveComponent("VAlert");
      const _component_VTextField = _resolveComponent("VTextField");
      const _component_VSwitch = _resolveComponent("VSwitch");
      const _component_VImg = _resolveComponent("VImg");
      return _openBlock(), _createElementBlock("section", _hoisted_1, [
        _createElementVNode("header", _hoisted_2, [
          _createElementVNode("div", _hoisted_3, [
            _createElementVNode("div", _hoisted_4, [
              _createVNode(_component_VIcon, {
                icon: "mdi-television-play",
                size: "24"
              })
            ]),
            _cache[18] || (_cache[18] = _createElementVNode("div", { class: "eyebrow" }, "EMBY / MISSING EPISODES", -1))
          ]),
          _createElementVNode("div", _hoisted_5, [
            _createVNode(_component_VChip, {
              color: statusColor.value,
              variant: "tonal",
              size: "small",
              label: ""
            }, {
              default: _withCtx(() => [
                _createTextVNode(_toDisplayString(statusLabel.value), 1)
              ]),
              _: 1
            }, 8, ["color"]),
            _createVNode(_component_VBtn, {
              icon: "mdi-close",
              variant: "text",
              "aria-label": "关闭设置",
              onClick: _cache[0] || (_cache[0] = ($event) => emit("close"))
            })
          ])
        ]),
        _createElementVNode("div", _hoisted_6, [
          _cache[20] || (_cache[20] = _createElementVNode("div", null, [
            _createElementVNode("h1", null, "Emby 缺集自动订阅"),
            _createElementVNode("p", null, "扫描 Emby 媒体库，发现已播缺集后自动创建 MoviePilot 订阅。")
          ], -1)),
          _createElementVNode("div", _hoisted_7, [
            _cache[19] || (_cache[19] = _createElementVNode("span", null, "最近扫描", -1)),
            _createElementVNode("strong", null, _toDisplayString(formatTime(summary.value?.finished_at)), 1)
          ])
        ]),
        message.value ? (_openBlock(), _createBlock(_component_VAlert, {
          key: 0,
          type: messageType.value,
          variant: "tonal",
          density: "comfortable",
          closable: "",
          class: "notice",
          "onClick:close": _cache[1] || (_cache[1] = ($event) => message.value = "")
        }, {
          default: _withCtx(() => [
            _createTextVNode(_toDisplayString(message.value), 1)
          ]),
          _: 1
        }, 8, ["type"])) : _createCommentVNode("", true),
        _createElementVNode("div", _hoisted_8, [
          _createElementVNode("div", _hoisted_9, [
            _cache[21] || (_cache[21] = _createElementVNode("span", null, "媒体剧集", -1)),
            _createElementVNode("strong", null, _toDisplayString(summary.value?.series ?? "--"), 1)
          ]),
          _createElementVNode("div", _hoisted_10, [
            _cache[22] || (_cache[22] = _createElementVNode("span", null, "发现缺集", -1)),
            _createElementVNode("strong", null, _toDisplayString(summary.value?.missing ?? "--"), 1)
          ]),
          _createElementVNode("div", _hoisted_11, [
            _cache[23] || (_cache[23] = _createElementVNode("span", null, "新增订阅", -1)),
            _createElementVNode("strong", _hoisted_12, _toDisplayString(summary.value?.subscriptions ?? "--"), 1)
          ]),
          _createElementVNode("div", _hoisted_13, [
            _cache[24] || (_cache[24] = _createElementVNode("span", null, "已有订阅", -1)),
            _createElementVNode("strong", null, _toDisplayString(summary.value?.existing_subscriptions ?? "--"), 1)
          ]),
          _createElementVNode("div", _hoisted_14, [
            _cache[25] || (_cache[25] = _createElementVNode("span", null, "扫描跳过", -1)),
            _createElementVNode("strong", null, _toDisplayString(summary.value?.skipped ?? "--"), 1)
          ])
        ]),
        _createElementVNode("form", {
          id: "missing-form",
          class: "workspace",
          onSubmit: _withModifiers(save, ["prevent"])
        }, [
          _createElementVNode("section", _hoisted_15, [
            _cache[26] || (_cache[26] = _createElementVNode("div", { class: "section-head" }, [
              _createElementVNode("div", { class: "section-index" }, "01"),
              _createElementVNode("div", null, [
                _createElementVNode("h2", null, "连接 Emby"),
                _createElementVNode("p", null, "填写 Emby 服务信息，用于读取电视剧和季度的实际集数。")
              ])
            ], -1)),
            _createElementVNode("div", _hoisted_16, [
              _createVNode(_component_VTextField, {
                modelValue: form.value.emby_url,
                "onUpdate:modelValue": _cache[2] || (_cache[2] = ($event) => form.value.emby_url = $event),
                label: "Emby 地址",
                placeholder: "http://192.168.1.20:8096",
                "prepend-inner-icon": "mdi-server-network",
                variant: "outlined",
                density: "comfortable",
                "hide-details": "auto"
              }, null, 8, ["modelValue"]),
              _createVNode(_component_VTextField, {
                modelValue: form.value.user_id,
                "onUpdate:modelValue": _cache[3] || (_cache[3] = ($event) => form.value.user_id = $event),
                label: "用户 ID",
                placeholder: "Emby 用户 UUID",
                "prepend-inner-icon": "mdi-account-outline",
                variant: "outlined",
                density: "comfortable",
                "hide-details": "auto"
              }, null, 8, ["modelValue"]),
              _createVNode(_component_VTextField, {
                modelValue: form.value.api_key,
                "onUpdate:modelValue": _cache[4] || (_cache[4] = ($event) => form.value.api_key = $event),
                type: revealKey.value ? "text" : "password",
                label: "API Key",
                placeholder: "输入 Emby API Key",
                "prepend-inner-icon": "mdi-key-outline",
                "append-inner-icon": revealKey.value ? "mdi-eye-off-outline" : "mdi-eye-outline",
                variant: "outlined",
                density: "comfortable",
                "hide-details": "auto",
                "onClick:appendInner": _cache[5] || (_cache[5] = ($event) => revealKey.value = !revealKey.value)
              }, null, 8, ["modelValue", "type", "append-inner-icon"]),
              _createVNode(_component_VTextField, {
                modelValue: form.value.timeout,
                "onUpdate:modelValue": _cache[6] || (_cache[6] = ($event) => form.value.timeout = $event),
                modelModifiers: { number: true },
                type: "number",
                min: "5",
                max: "120",
                suffix: "秒",
                label: "请求超时",
                "prepend-inner-icon": "mdi-timer-outline",
                variant: "outlined",
                density: "comfortable",
                "hide-details": "auto"
              }, null, 8, ["modelValue"])
            ])
          ]),
          _createElementVNode("section", _hoisted_17, [
            _cache[29] || (_cache[29] = _createElementVNode("div", { class: "section-head" }, [
              _createElementVNode("div", { class: "section-index" }, "02"),
              _createElementVNode("div", null, [
                _createElementVNode("h2", null, "扫描规则"),
                _createElementVNode("p", null, "控制自动扫描的开关、时间以及缺集判定范围。")
              ])
            ], -1)),
            _createElementVNode("div", _hoisted_18, [
              _createElementVNode("div", _hoisted_19, [
                _createElementVNode("div", _hoisted_20, [
                  _createVNode(_component_VIcon, {
                    icon: "mdi-radar",
                    size: "20"
                  })
                ]),
                _cache[27] || (_cache[27] = _createElementVNode("div", { class: "rule-copy" }, [
                  _createElementVNode("strong", null, "启用自动扫描"),
                  _createElementVNode("span", null, "按设定周期检查 Emby 媒体库")
                ], -1)),
                _createVNode(_component_VSwitch, {
                  modelValue: form.value.enabled,
                  "onUpdate:modelValue": _cache[7] || (_cache[7] = ($event) => form.value.enabled = $event),
                  color: "primary",
                  "hide-details": "",
                  inset: ""
                }, null, 8, ["modelValue"])
              ]),
              _createElementVNode("div", _hoisted_21, [
                _createElementVNode("div", _hoisted_22, [
                  _createVNode(_component_VIcon, {
                    icon: "mdi-calendar-check-outline",
                    size: "20"
                  })
                ]),
                _cache[28] || (_cache[28] = _createElementVNode("div", { class: "rule-copy" }, [
                  _createElementVNode("strong", null, "只订阅已播缺集"),
                  _createElementVNode("span", null, "忽略 TMDB 中尚未播出的集数")
                ], -1)),
                _createVNode(_component_VSwitch, {
                  modelValue: form.value.aired_only,
                  "onUpdate:modelValue": _cache[8] || (_cache[8] = ($event) => form.value.aired_only = $event),
                  color: "primary",
                  "hide-details": "",
                  inset: ""
                }, null, 8, ["modelValue"])
              ])
            ]),
            _createElementVNode("div", _hoisted_23, [
              _createVNode(_component_VTextField, {
                modelValue: form.value.cron,
                "onUpdate:modelValue": _cache[9] || (_cache[9] = ($event) => form.value.cron = $event),
                label: "扫描周期 Cron",
                placeholder: "0 */6 * * *",
                "prepend-inner-icon": "mdi-clock-outline",
                variant: "outlined",
                density: "comfortable",
                "hide-details": "auto"
              }, null, 8, ["modelValue"])
            ])
          ]),
          _createElementVNode("section", _hoisted_24, [
            _createElementVNode("div", _hoisted_25, [
              _cache[31] || (_cache[31] = _createElementVNode("div", { class: "section-index" }, "03", -1)),
              _cache[32] || (_cache[32] = _createElementVNode("div", null, [
                _createElementVNode("h2", null, "通知设置"),
                _createElementVNode("p", null, "使用 MoviePilot 已配置的全局通知渠道，不会发送 Emby API Key。")
              ], -1)),
              _createVNode(_component_VBtn, {
                class: "test-notify",
                color: "primary",
                variant: "tonal",
                size: "small",
                "prepend-icon": "mdi-bell-check-outline",
                loading: testingNotify.value,
                disabled: !props.api,
                onClick: testNotification
              }, {
                default: _withCtx(() => [..._cache[30] || (_cache[30] = [
                  _createTextVNode("测试推送", -1)
                ])]),
                _: 1
              }, 8, ["loading", "disabled"])
            ]),
            _createElementVNode("div", _hoisted_26, [
              _createElementVNode("div", _hoisted_27, [
                _createElementVNode("div", _hoisted_28, [
                  _createVNode(_component_VIcon, {
                    icon: "mdi-bell-outline",
                    size: "20"
                  })
                ]),
                _cache[33] || (_cache[33] = _createElementVNode("div", { class: "rule-copy" }, [
                  _createElementVNode("strong", null, "启用通知"),
                  _createElementVNode("span", null, "允许扫描结果发送到全局通知渠道")
                ], -1)),
                _createVNode(_component_VSwitch, {
                  modelValue: form.value.notify_enabled,
                  "onUpdate:modelValue": _cache[10] || (_cache[10] = ($event) => form.value.notify_enabled = $event),
                  color: "primary",
                  "hide-details": "",
                  inset: ""
                }, null, 8, ["modelValue"])
              ]),
              _createElementVNode("div", _hoisted_29, [
                _createElementVNode("div", _hoisted_30, [
                  _createVNode(_component_VIcon, {
                    icon: "mdi-clipboard-check-outline",
                    size: "20"
                  })
                ]),
                _cache[34] || (_cache[34] = _createElementVNode("div", { class: "rule-copy" }, [
                  _createElementVNode("strong", null, "扫描完成汇总"),
                  _createElementVNode("span", null, "扫描有变化或失败时发送结果")
                ], -1)),
                _createVNode(_component_VSwitch, {
                  modelValue: form.value.notify_on_complete,
                  "onUpdate:modelValue": _cache[11] || (_cache[11] = ($event) => form.value.notify_on_complete = $event),
                  color: "primary",
                  "hide-details": "",
                  inset: "",
                  disabled: !form.value.notify_enabled
                }, null, 8, ["modelValue", "disabled"])
              ]),
              _createElementVNode("div", _hoisted_31, [
                _createElementVNode("div", _hoisted_32, [
                  _createVNode(_component_VIcon, {
                    icon: "mdi-plus-box-outline",
                    size: "20"
                  })
                ]),
                _cache[35] || (_cache[35] = _createElementVNode("div", { class: "rule-copy" }, [
                  _createElementVNode("strong", null, "新建订阅提醒"),
                  _createElementVNode("span", null, "列出本次新创建的剧集和缺集")
                ], -1)),
                _createVNode(_component_VSwitch, {
                  modelValue: form.value.notify_new,
                  "onUpdate:modelValue": _cache[12] || (_cache[12] = ($event) => form.value.notify_new = $event),
                  color: "primary",
                  "hide-details": "",
                  inset: "",
                  disabled: !form.value.notify_enabled
                }, null, 8, ["modelValue", "disabled"])
              ]),
              _createElementVNode("div", _hoisted_33, [
                _createElementVNode("div", _hoisted_34, [
                  _createVNode(_component_VIcon, {
                    icon: "mdi-sync-circle-outline",
                    size: "20"
                  })
                ]),
                _cache[36] || (_cache[36] = _createElementVNode("div", { class: "rule-copy" }, [
                  _createElementVNode("strong", null, "复用订阅提醒"),
                  _createElementVNode("span", null, "列出已经存在的订阅")
                ], -1)),
                _createVNode(_component_VSwitch, {
                  modelValue: form.value.notify_existing,
                  "onUpdate:modelValue": _cache[13] || (_cache[13] = ($event) => form.value.notify_existing = $event),
                  color: "primary",
                  "hide-details": "",
                  inset: "",
                  disabled: !form.value.notify_enabled
                }, null, 8, ["modelValue", "disabled"])
              ]),
              _createElementVNode("div", _hoisted_35, [
                _createElementVNode("div", _hoisted_36, [
                  _createVNode(_component_VIcon, {
                    icon: "mdi-alert-circle-outline",
                    size: "20"
                  })
                ]),
                _cache[37] || (_cache[37] = _createElementVNode("div", { class: "rule-copy" }, [
                  _createElementVNode("strong", null, "失败提醒"),
                  _createElementVNode("span", null, "列出创建订阅失败的剧集和原因")
                ], -1)),
                _createVNode(_component_VSwitch, {
                  modelValue: form.value.notify_failure,
                  "onUpdate:modelValue": _cache[14] || (_cache[14] = ($event) => form.value.notify_failure = $event),
                  color: "primary",
                  "hide-details": "",
                  inset: "",
                  disabled: !form.value.notify_enabled
                }, null, 8, ["modelValue", "disabled"])
              ]),
              _createElementVNode("div", _hoisted_37, [
                _createElementVNode("div", _hoisted_38, [
                  _createVNode(_component_VIcon, {
                    icon: "mdi-radar",
                    size: "20"
                  })
                ]),
                _cache[38] || (_cache[38] = _createElementVNode("div", { class: "rule-copy" }, [
                  _createElementVNode("strong", null, "开始扫描提醒"),
                  _createElementVNode("span", null, "扫描开始时先发送一条提示")
                ], -1)),
                _createVNode(_component_VSwitch, {
                  modelValue: form.value.notify_on_start,
                  "onUpdate:modelValue": _cache[15] || (_cache[15] = ($event) => form.value.notify_on_start = $event),
                  color: "primary",
                  "hide-details": "",
                  inset: "",
                  disabled: !form.value.notify_enabled
                }, null, 8, ["modelValue", "disabled"])
              ])
            ]),
            _createVNode(_component_VSwitch, {
              modelValue: form.value.notify_only_changes,
              "onUpdate:modelValue": _cache[16] || (_cache[16] = ($event) => form.value.notify_only_changes = $event),
              color: "primary",
              class: "changes-switch",
              label: "仅在有新订阅、失败或其他变化时发送汇总",
              "hide-details": "",
              inset: "",
              disabled: !form.value.notify_enabled || !form.value.notify_on_complete
            }, null, 8, ["modelValue", "disabled"])
          ]),
          _createElementVNode("section", _hoisted_39, [
            _createElementVNode("div", _hoisted_40, [
              _createElementVNode("div", _hoisted_41, [
                _createVNode(_component_VIcon, {
                  icon: "mdi-play-circle-outline",
                  size: "24"
                })
              ]),
              _cache[39] || (_cache[39] = _createElementVNode("div", null, [
                _createElementVNode("h2", null, "立即扫描媒体库"),
                _createElementVNode("p", null, "提交后在后台读取 Emby，全量检查缺集并创建订阅，不会重复创建已有订阅。")
              ], -1))
            ]),
            _createVNode(_component_VBtn, {
              color: "primary",
              variant: "flat",
              "prepend-icon": "mdi-play",
              loading: scanning.value,
              disabled: !ready.value,
              onClick: scanNow
            }, {
              default: _withCtx(() => [..._cache[40] || (_cache[40] = [
                _createTextVNode("立即扫描", -1)
              ])]),
              _: 1
            }, 8, ["loading", "disabled"])
          ]),
          _createElementVNode("section", _hoisted_42, [
            _createElementVNode("div", _hoisted_43, [
              _cache[41] || (_cache[41] = _createElementVNode("div", { class: "section-head section-head--inline" }, [
                _createElementVNode("div", { class: "section-index" }, "04"),
                _createElementVNode("div", null, [
                  _createElementVNode("h2", null, "订阅历史"),
                  _createElementVNode("p", null, "展示最近实际创建或复用的订阅，包含对应媒体海报和缺集。")
                ])
              ], -1)),
              _createVNode(_component_VBtn, {
                icon: "mdi-refresh",
                variant: "text",
                "aria-label": "刷新订阅历史",
                loading: scanning.value,
                onClick: loadSummary
              }, null, 8, ["loading"])
            ]),
            !history.value.length ? (_openBlock(), _createElementBlock("div", _hoisted_44, [
              _createVNode(_component_VIcon, {
                icon: "mdi-filmstrip-off",
                size: "30"
              }),
              _cache[42] || (_cache[42] = _createElementVNode("span", null, "扫描后，订阅记录会显示在这里", -1))
            ])) : (_openBlock(), _createElementBlock("div", _hoisted_45, [
              (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(history.value, (item) => {
                return _openBlock(), _createElementBlock("article", {
                  key: item.key || `${item.name}-${item.season}`,
                  class: "history-item"
                }, [
                  item.poster ? (_openBlock(), _createBlock(_component_VImg, {
                    key: 0,
                    src: item.poster,
                    class: "poster",
                    cover: "",
                    alt: item.name || "媒体海报"
                  }, null, 8, ["src", "alt"])) : (_openBlock(), _createElementBlock("div", _hoisted_46, [
                    _createVNode(_component_VIcon, {
                      icon: "mdi-movie-open-outline",
                      size: "24"
                    })
                  ])),
                  _createElementVNode("div", _hoisted_47, [
                    _createElementVNode("div", _hoisted_48, [
                      _createElementVNode("strong", null, _toDisplayString(item.name || "未知剧集"), 1),
                      _createVNode(_component_VChip, {
                        size: "x-small",
                        color: item.status === "已创建" ? "success" : "default",
                        variant: "tonal",
                        label: ""
                      }, {
                        default: _withCtx(() => [
                          _createTextVNode(_toDisplayString(item.status || "已处理"), 1)
                        ]),
                        _: 2
                      }, 1032, ["color"])
                    ]),
                    _createElementVNode("span", _hoisted_49, _toDisplayString(item.year || "年份未知") + " · 第 " + _toDisplayString(item.season || "-") + " 季 · " + _toDisplayString(formatMissing(item.missing)), 1),
                    _createElementVNode("span", _hoisted_50, "处理于 " + _toDisplayString(formatTime(item.updated_at)), 1)
                  ])
                ]);
              }), 128))
            ]))
          ])
        ], 32),
        _createElementVNode("footer", _hoisted_51, [
          _createVNode(_component_VBtn, {
            variant: "text",
            "prepend-icon": "mdi-close",
            onClick: _cache[17] || (_cache[17] = ($event) => emit("close"))
          }, {
            default: _withCtx(() => [..._cache[43] || (_cache[43] = [
              _createTextVNode("取消", -1)
            ])]),
            _: 1
          }),
          _createVNode(_component_VBtn, {
            color: "primary",
            variant: "flat",
            "prepend-icon": "mdi-content-save-outline",
            loading: saving.value,
            disabled: !canSave.value,
            type: "submit",
            form: "missing-form"
          }, {
            default: _withCtx(() => [..._cache[44] || (_cache[44] = [
              _createTextVNode("保存配置", -1)
            ])]),
            _: 1
          }, 8, ["loading", "disabled"])
        ])
      ]);
    };
  }
});

const _export_sfc = (sfc, props) => {
  const target = sfc.__vccOpts || sfc;
  for (const [key, val] of props) {
    target[key] = val;
  }
  return target;
};

const Config = /* @__PURE__ */ _export_sfc(_sfc_main, [["__scopeId", "data-v-03249ec7"]]);

export { _export_sfc as _, Config as default };
