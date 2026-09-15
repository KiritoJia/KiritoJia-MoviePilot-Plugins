import { importShared } from './__federation_fn_import-JrT3xvdd.js';
import Config, { _ as _export_sfc } from './__federation_expose_Config-BikJ3Ybb.js';

const {defineComponent:_defineComponent} = await importShared('vue');

const {resolveComponent:_resolveComponent,openBlock:_openBlock,createBlock:_createBlock,createCommentVNode:_createCommentVNode,toDisplayString:_toDisplayString,createTextVNode:_createTextVNode,withCtx:_withCtx,createElementBlock:_createElementBlock} = await importShared('vue');

const _hoisted_1 = { class: "emby-app-page" };
const {onMounted,ref} = await importShared('vue');
const _sfc_main = /* @__PURE__ */ _defineComponent({
  __name: "AppPage",
  props: {
    api: {},
    pluginId: { default: "KiritoEmbyMissingSubscribe" },
    initialConfig: { default: void 0 },
    config: { default: void 0 },
    navKey: { default: "main" }
  },
  setup(__props) {
    const props = __props;
    const config = ref(props.initialConfig || props.config || null);
    const loading = ref(!config.value);
    const error = ref("");
    const pluginPath = (path) => `plugin/${encodeURIComponent(props.pluginId)}/${path.replace(/^\//, "")}`;
    async function loadConfig() {
      if (config.value) return;
      loading.value = true;
      error.value = "";
      try {
        config.value = await props.api.get(pluginPath("config"));
      } catch (cause) {
        error.value = cause instanceof Error ? cause.message : "无法读取插件配置";
      } finally {
        loading.value = false;
      }
    }
    async function saveConfig(value) {
      const saved = await props.api.post(pluginPath("config"), value);
      config.value = saved || value;
    }
    onMounted(() => {
      void loadConfig();
    });
    return (_ctx, _cache) => {
      const _component_VProgressLinear = _resolveComponent("VProgressLinear");
      const _component_VAlert = _resolveComponent("VAlert");
      return _openBlock(), _createElementBlock("section", _hoisted_1, [
        loading.value ? (_openBlock(), _createBlock(_component_VProgressLinear, {
          key: 0,
          indeterminate: "",
          color: "primary"
        })) : _createCommentVNode("", true),
        error.value ? (_openBlock(), _createBlock(_component_VAlert, {
          key: 1,
          type: "error",
          variant: "tonal",
          class: "ma-4"
        }, {
          default: _withCtx(() => [
            _createTextVNode(_toDisplayString(error.value), 1)
          ]),
          _: 1
        })) : _createCommentVNode("", true),
        config.value ? (_openBlock(), _createBlock(Config, {
          key: 2,
          "initial-config": config.value,
          api: props.api,
          onSave: saveConfig
        }, null, 8, ["initial-config", "api"])) : _createCommentVNode("", true)
      ]);
    };
  }
});

const AppPage = /* @__PURE__ */ _export_sfc(_sfc_main, [["__scopeId", "data-v-a83168b8"]]);

export { AppPage as default };
