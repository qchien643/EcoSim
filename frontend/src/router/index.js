import { createRouter, createWebHistory } from 'vue-router'
import { useAppStore } from '../stores/appStore'

const routes = [
  { path: '/', name: 'dashboard', component: () => import('../views/DashboardView.vue') },
  { path: '/campaign', name: 'campaign', component: () => import('../views/CampaignView.vue') },
  { path: '/graph', name: 'graph', component: () => import('../views/GraphView.vue') },
  { path: '/simulation', name: 'simulation', component: () => import('../views/SimulationView.vue') },
  { path: '/analysis', name: 'analysis', component: () => import('../views/AnalysisView.vue') },
  { path: '/report', name: 'report', component: () => import('../views/ReportView.vue') },
  { path: '/survey', name: 'survey', component: () => import('../views/SurveyView.vue') },
  { path: '/interview', name: 'interview', component: () => import('../views/InterviewView.vue') },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// ── Navigation Guard: enforce sequential step locking ──
router.beforeEach((to, from, next) => {
  const store = useAppStore()
  const stepName = to.name || ''

  if (store.isStepUnlocked(stepName)) {
    next()
  } else {
    // Redirect to the next unlocked step
    const fallback = store.getNextUnlockedStep()
    console.warn(`[Router Guard] Step "${stepName}" is locked. Redirecting to "${fallback}"`)
    next({ name: fallback })
  }
})

export default router
