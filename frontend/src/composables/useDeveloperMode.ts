import { ref, watch } from 'vue'

// 正式构建可通过 VITE_ENABLE_DEVELOPER_LAB=false 完全关闭实验室入口。
const developerLabAvailable = import.meta.env.VITE_ENABLE_DEVELOPER_LAB !== 'false'
const savedPreference = window.localStorage.getItem('repopilot-developer-mode')
const developerMode = ref(developerLabAvailable && savedPreference !== 'false')

watch(developerMode, (enabled) => {
  window.localStorage.setItem('repopilot-developer-mode', String(enabled))
})

export function useDeveloperMode() {
  function setDeveloperMode(enabled: boolean) {
    developerMode.value = developerLabAvailable && enabled
  }

  return { developerLabAvailable, developerMode, setDeveloperMode }
}
