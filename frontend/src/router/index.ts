import { createRouter, createWebHistory } from 'vue-router'

import ProjectsView from '../views/ProjectsView.vue'
import KnowledgeView from '../views/KnowledgeView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/projects' },
    { path: '/projects', name: 'projects', component: ProjectsView },
    { path: '/knowledge', name: 'knowledge', component: KnowledgeView },
  ],
})

export default router
