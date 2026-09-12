import { importShared } from './__federation_fn_import-JrT3xvdd.js';

const {defineComponent:_defineComponent} = await importShared('vue');

const {resolveComponent:_resolveComponent,createVNode:_createVNode,createElementVNode:_createElementVNode,createTextVNode:_createTextVNode,toDisplayString:_toDisplayString,withCtx:_withCtx,openBlock:_openBlock,createBlock:_createBlock,createCommentVNode:_createCommentVNode,withModifiers:_withModifiers,createElementBlock:_createElementBlock} = await importShared('vue');

const _hoisted_1 = { class: "emby-config" };
const _hoisted_2 = { class: "hero" };
const _hoisted_3 = { class: "hero__identity" };
const _hoisted_4 = { class: "hero__icon" };
const _hoisted_5 = { class: "hero__crumb" };
const _hoisted_6 = { class: "hero__actions" };
const _hoisted_7 = { class: "content" };
const _hoisted_8 = { class: "panel" };
const _hoisted_9 = { class: "panel__heading" };
const _hoisted_10 = { class: "heading-icon blue" };
const _hoisted_11 = { class: "field-grid" };
const _hoisted_12 = { class: "panel" };
const _hoisted_13 = { class: "panel__heading" };
const _hoisted_14 = { class: "heading-icon green" };
const _hoisted_15 = { class: "setting-list" };
const _hoisted_16 = { class: "setting-row" };
const _hoisted_17 = { class: "setting-row" };
const _hoisted_18 = { class: "setting-row" };
const _hoisted_19 = { class: "panel panel--command" };
const _hoisted_20 = { class: "panel__heading" };
const _hoisted_21 = { class: "heading-icon amber" };
const _hoisted_22 = { class: "command-row" };
const _hoisted_23 = { class: "command-state" };
const _hoisted_24 = { class: "summary" };
const _hoisted_25 = { class: "summary__title" };
const _hoisted_26 = { class: "metric-grid" };
const _hoisted_27 = { class: "metric" };
const _hoisted_28 = { class: "metric" };
const _hoisted_29 = { class: "metric" };
const _hoisted_30 = { class: "metric" };
const _hoisted_31 = { class: "summary__item" };
const _hoisted_32 = { class: "summary__item" };
const _hoisted_33 = { class: "summary__item" };
const _hoisted_34 = { class: "summary__tip" };
const _hoisted_35 = { class: "footer-actions" };
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
      timeout: 20
    });
    const saving = ref(false);
    const scanning = ref(false);
    const revealKey = ref(false);
    const message = ref("");
    const messageType = ref("info");
    const summary = ref(null);
    emit("layout", { maxWidth: "74rem" });
    watch(() => props.initialConfig, applyConfig, { immediate: true, deep: true });
    const ready = computed(() => Boolean(form.value.emby_url.trim() && form.value.user_id.trim() && form.value.api_key.trim()));
    const canSave = computed(() => !saving.value && !scanning.value);
    const pluginId = computed(() => String(props.initialConfig?.plugin_id || "").trim());
    const statusLabel = computed(() => form.value.enabled ? "运行中" : "已停用");
    const statusColor = computed(() => form.value.enabled ? "success" : "default");
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
        timeout: Number(initial.timeout || 20)
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
    async function scanNow() {
      if (!ready.value) {
        setMessage("请先填写完整的 Emby 连接信息。", "error");
        return;
      }
      emit("save", { ...props.initialConfig, ...form.value, onlyonce: true });
      setMessage("已提交一次性扫描，MoviePilot 将在后台执行。", "info");
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
      return _openBlock(), _createElementBlock("section", _hoisted_1, [
        _createElementVNode("header", _hoisted_2, [
          _createElementVNode("div", _hoisted_3, [
            _createElementVNode("div", _hoisted_4, [
              _createVNode(_component_VIcon, {
                icon: "mdi-television-play",
                size: "26"
              })
            ]),
            _createElementVNode("div", null, [
              _createElementVNode("div", _hoisted_5, [
                _cache[11] || (_cache[11] = _createTextVNode("MoviePilot ", -1)),
                _createVNode(_component_VIcon, {
                  icon: "mdi-chevron-right",
                  size: "14"
                }),
                _cache[12] || (_cache[12] = _createTextVNode(" 媒体自动化", -1))
              ]),
              _cache[13] || (_cache[13] = _createElementVNode("h1", null, "Emby 缺集自动订阅", -1)),
              _cache[14] || (_cache[14] = _createElementVNode("p", null, "读取 Emby 媒体库，发现已播缺集后自动交给 MoviePilot 订阅。", -1))
            ])
          ]),
          _createElementVNode("div", _hoisted_6, [
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
        _createElementVNode("form", {
          id: "missing-form",
          class: "workspace",
          onSubmit: _withModifiers(save, ["prevent"])
        }, [
          _createElementVNode("main", _hoisted_7, [
            _createElementVNode("section", _hoisted_8, [
              _createElementVNode("div", _hoisted_9, [
                _createElementVNode("div", _hoisted_10, [
                  _createVNode(_component_VIcon, { icon: "mdi-link-variant" })
                ]),
                _cache[15] || (_cache[15] = _createElementVNode("div", null, [
                  _createElementVNode("h2", null, "连接 Emby"),
                  _createElementVNode("p", null, "使用 Emby API 读取电视剧、季度和已存在的集数。")
                ], -1))
              ]),
              _createElementVNode("div", _hoisted_11, [
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
            _createElementVNode("section", _hoisted_12, [
              _createElementVNode("div", _hoisted_13, [
                _createElementVNode("div", _hoisted_14, [
                  _createVNode(_component_VIcon, { icon: "mdi-radar" })
                ]),
                _cache[16] || (_cache[16] = _createElementVNode("div", null, [
                  _createElementVNode("h2", null, "扫描策略"),
                  _createElementVNode("p", null, "控制扫描周期以及哪些缺集可以进入订阅。")
                ], -1))
              ]),
              _createElementVNode("div", _hoisted_15, [
                _createElementVNode("div", _hoisted_16, [
                  _cache[17] || (_cache[17] = _createElementVNode("div", null, [
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
                _createElementVNode("div", _hoisted_17, [
                  _cache[18] || (_cache[18] = _createElementVNode("div", null, [
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
                ]),
                _createElementVNode("div", _hoisted_18, [
                  _cache[19] || (_cache[19] = _createElementVNode("div", null, [
                    _createElementVNode("strong", null, "扫描周期"),
                    _createElementVNode("span", null, "使用标准 Cron 表达式，默认每 6 小时")
                  ], -1)),
                  _createVNode(_component_VTextField, {
                    modelValue: form.value.cron,
                    "onUpdate:modelValue": _cache[9] || (_cache[9] = ($event) => form.value.cron = $event),
                    class: "compact-field",
                    label: "Cron",
                    placeholder: "0 */6 * * *",
                    variant: "outlined",
                    density: "compact",
                    "hide-details": ""
                  }, null, 8, ["modelValue"])
                ])
              ])
            ]),
            _createElementVNode("section", _hoisted_19, [
              _createElementVNode("div", _hoisted_20, [
                _createElementVNode("div", _hoisted_21, [
                  _createVNode(_component_VIcon, { icon: "mdi-lightning-bolt-outline" })
                ]),
                _cache[20] || (_cache[20] = _createElementVNode("div", null, [
                  _createElementVNode("h2", null, "立即执行"),
                  _createElementVNode("p", null, "保存配置后，可以立即扫描一次整个 Emby 媒体库。")
                ], -1))
              ]),
              _createElementVNode("div", _hoisted_22, [
                _createElementVNode("div", _hoisted_23, [
                  _createVNode(_component_VIcon, {
                    icon: "mdi-database-search-outline",
                    color: "primary",
                    size: "24"
                  }),
                  _cache[21] || (_cache[21] = _createElementVNode("span", null, "扫描完成后只会为缺集季度创建订阅，不会重复创建。", -1))
                ]),
                _createVNode(_component_VBtn, {
                  color: "primary",
                  variant: "tonal",
                  "prepend-icon": "mdi-play",
                  loading: scanning.value,
                  onClick: scanNow
                }, {
                  default: _withCtx(() => [..._cache[22] || (_cache[22] = [
                    _createTextVNode("立即扫描", -1)
                  ])]),
                  _: 1
                }, 8, ["loading"])
              ])
            ])
          ]),
          _createElementVNode("aside", _hoisted_24, [
            _createElementVNode("div", _hoisted_25, [
              _createVNode(_component_VIcon, {
                icon: "mdi-chart-box-outline",
                color: "primary"
              }),
              _cache[23] || (_cache[23] = _createElementVNode("h2", null, "运行概览", -1))
            ]),
            _createElementVNode("div", _hoisted_26, [
              _createElementVNode("div", _hoisted_27, [
                _cache[24] || (_cache[24] = _createElementVNode("span", null, "剧集", -1)),
                _createElementVNode("strong", null, _toDisplayString(summary.value?.series ?? "--"), 1)
              ]),
              _createElementVNode("div", _hoisted_28, [
                _cache[25] || (_cache[25] = _createElementVNode("span", null, "缺集", -1)),
                _createElementVNode("strong", null, _toDisplayString(summary.value?.missing ?? "--"), 1)
              ]),
              _createElementVNode("div", _hoisted_29, [
                _cache[26] || (_cache[26] = _createElementVNode("span", null, "新增订阅", -1)),
                _createElementVNode("strong", null, _toDisplayString(summary.value?.subscriptions ?? "--"), 1)
              ]),
              _createElementVNode("div", _hoisted_30, [
                _cache[27] || (_cache[27] = _createElementVNode("span", null, "已有订阅", -1)),
                _createElementVNode("strong", null, _toDisplayString(summary.value?.existing_subscriptions ?? "--"), 1)
              ])
            ]),
            _cache[33] || (_cache[33] = _createElementVNode("div", { class: "summary__divider" }, null, -1)),
            _createElementVNode("div", _hoisted_31, [
              _createVNode(_component_VIcon, { icon: "mdi-clock-outline" }),
              _cache[28] || (_cache[28] = _createElementVNode("span", null, "上次扫描", -1)),
              _createElementVNode("strong", null, _toDisplayString(summary.value?.finished_at || "尚未执行"), 1)
            ]),
            _createElementVNode("div", _hoisted_32, [
              _createVNode(_component_VIcon, { icon: "mdi-alert-circle-outline" }),
              _cache[29] || (_cache[29] = _createElementVNode("span", null, "扫描跳过", -1)),
              _createElementVNode("strong", null, _toDisplayString(summary.value?.skipped ?? "--"), 1)
            ]),
            _createElementVNode("div", _hoisted_33, [
              _createVNode(_component_VIcon, { icon: "mdi-close-circle-outline" }),
              _cache[30] || (_cache[30] = _createElementVNode("span", null, "订阅失败", -1)),
              _createElementVNode("strong", null, _toDisplayString(summary.value?.subscribe_failures ?? "--"), 1)
            ]),
            !ready.value ? (_openBlock(), _createBlock(_component_VAlert, {
              key: 0,
              type: "warning",
              variant: "tonal",
              density: "compact",
              class: "summary__alert"
            }, {
              default: _withCtx(() => [..._cache[31] || (_cache[31] = [
                _createTextVNode("填写完整连接信息后才能开始扫描。", -1)
              ])]),
              _: 1
            })) : _createCommentVNode("", true),
            _createElementVNode("div", _hoisted_34, [
              _createVNode(_component_VIcon, {
                icon: "mdi-information-outline",
                size: "18"
              }),
              _cache[32] || (_cache[32] = _createElementVNode("span", null, "插件只负责识别缺集和创建订阅，后续搜索、下载、整理由 MoviePilot 原生流程完成。", -1))
            ])
          ])
        ], 32),
        _createElementVNode("footer", _hoisted_35, [
          _createVNode(_component_VBtn, {
            variant: "text",
            "prepend-icon": "mdi-close",
            onClick: _cache[10] || (_cache[10] = ($event) => emit("close"))
          }, {
            default: _withCtx(() => [..._cache[34] || (_cache[34] = [
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
            default: _withCtx(() => [..._cache[35] || (_cache[35] = [
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

const Config = /* @__PURE__ */ _export_sfc(_sfc_main, [["__scopeId", "data-v-0f705ca3"]]);

export { Config as default };
