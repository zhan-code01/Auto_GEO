declare module '@wangeditor/editor-for-vue' {
  import type { DefineComponent } from 'vue'
  export const Editor: DefineComponent<any, any, any>
  export const Toolbar: DefineComponent<any, any, any>
}

declare module '@/views/site-builder/ConfigWizard.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<{}, {}, any>
  export default component
}
