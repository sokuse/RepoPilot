import { createRouter, createWebHistory } from 'vue-router'

import ProjectsView from '../views/ProjectsView.vue'
import KnowledgeView from '../views/KnowledgeView.vue'
import DiagnosisView from '../views/DiagnosisView.vue'
import EvaluationView from '../views/EvaluationView.vue'
import { useDeveloperMode } from '../composables/useDeveloperMode'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/projects' },
    { path: '/projects', name: 'projects', component: ProjectsView },
    { path: '/knowledge', name: 'knowledge', component: KnowledgeView },
    { path: '/diagnosis', name: 'diagnosis', component: DiagnosisView },
    {
      path: '/evaluation',
      name: 'evaluation',
      component: EvaluationView,
      meta: { developerOnly: true },
    },
  ],
})

router.beforeEach((to) => {
  const { developerLabAvailable, developerMode } = useDeveloperMode()
  if (to.meta.developerOnly && (!developerLabAvailable || !developerMode.value)) {
    return { name: 'projects' }
  }
})

export default router
