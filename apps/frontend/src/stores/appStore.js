import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

/**
 * Global application store — tracks the active campaign/sim/survey
 * across the EcoSim pipeline.
 *
 * FRESH STATE POLICY:
 * - NO localStorage/sessionStorage persistence
 * - Every page load/refresh = brand new session
 * - Sequential step locking: Campaign → Graph → Simulation → Analysis → Report
 * - Interview & Survey only unlock after Report
 */
export const useAppStore = defineStore('app', () => {
  // --- Core IDs (in-memory only, no persistence) ---
  const campaignId = ref('')
  const simId = ref('')
  const surveyId = ref('')
  const groupId = ref('')

  // --- Campaign spec cache ---
  const campaignSpec = ref(null)

  // --- Pipeline step tracking ---
  const STEP_ORDER = ['campaign', 'graph', 'simulation']
  const EXTENDED_STEPS = ['analysis', 'report', 'survey', 'interview'] // unlock after simulation
  const completedSteps = ref(new Set())

  // --- Loading / Error ---
  const loading = ref(false)
  const error = ref('')

  // --- Debug mode: unlock all steps for testing ---
  const debugMode = ref(false)

  // --- Simulation preparation state (in-memory only) ---
  const simPrepData = ref({
    profiles: [],
    timeConfig: null,
    eventConfig: null,
    recConfig: null,
    crisisNames: [],
    reasoning: '',
    estimatedMinutes: 0,
    simReady: false,
    numAgents: 10,
    numRounds: 24,
    prepareStep: 1,
  })

  // ═══ Step Locking Logic ═══

  function completeStep(stepName) {
    // Create new Set to guarantee Vue reactivity trigger
    const next = new Set(completedSteps.value)
    next.add(stepName)
    completedSteps.value = next
    console.log('[EcoSim] Step completed:', stepName, '| All completed:', [...next])
  }

  function isStepCompleted(stepName) {
    return completedSteps.value.has(stepName)
  }

  function enableDebugMode() {
    debugMode.value = true
    console.log('[EcoSim] Debug mode ENABLED — all steps unlocked')
  }

  function isStepUnlocked(stepName) {
    // Debug mode: everything is unlocked
    if (debugMode.value) return true

    // Dashboard is always accessible
    if (stepName === 'dashboard' || stepName === '/') return true

    // Campaign is always the first step — always unlocked
    if (stepName === 'campaign') return true

    // Extended steps (analysis, report, survey, interview) require simulation to be completed
    if (EXTENDED_STEPS.includes(stepName)) {
      return completedSteps.value.has('simulation')
    }

    // For pipeline steps, the PREVIOUS step must be completed
    const idx = STEP_ORDER.indexOf(stepName)
    if (idx <= 0) return true // campaign or unknown
    return completedSteps.value.has(STEP_ORDER[idx - 1])
  }

  function getNextUnlockedStep() {
    // Returns the first step that is unlocked but not completed
    for (const step of STEP_ORDER) {
      if (!completedSteps.value.has(step)) return step
    }
    return 'report' // all done
  }

  // ═══ Setters (NO persistence) ═══

  function setSimPrepData(data) {
    simPrepData.value = { ...simPrepData.value, ...data }
  }

  function clearSimPrepData() {
    simPrepData.value = {
      profiles: [], timeConfig: null, eventConfig: null, recConfig: null,
      crisisNames: [], reasoning: '', estimatedMinutes: 0, simReady: false,
      numAgents: 10, numRounds: 24, prepareStep: 1,
    }
  }

  function setCampaignId(id) {
    campaignId.value = id
  }

  function setCampaignSpec(spec) {
    campaignSpec.value = spec
  }

  function setSimId(id) {
    simId.value = id
  }

  function setSurveyId(id) {
    surveyId.value = id
  }

  function setGroupId(id) {
    groupId.value = id
  }

  function setLoading(val) { loading.value = val }
  function setError(msg) { error.value = msg }
  function clearError() { error.value = '' }

  // --- Computed ---
  const hasCampaign = computed(() => !!campaignId.value)
  const hasSim = computed(() => !!simId.value)
  const hasSurvey = computed(() => !!surveyId.value)

  // --- Reset (clears everything for "Phiên mới") ---
  function reset() {
    campaignId.value = ''
    simId.value = ''
    surveyId.value = ''
    groupId.value = ''
    campaignSpec.value = null
    loading.value = false
    error.value = ''
    completedSteps.value = new Set()
    clearSimPrepData()
    // Also clear any leftover localStorage from old versions
    localStorage.removeItem('ecosim_campaign_id')
    localStorage.removeItem('ecosim_sim_id')
    localStorage.removeItem('ecosim_survey_id')
    localStorage.removeItem('ecosim_group_id')
    sessionStorage.removeItem('ecosim_sim_prep')
  }

  // Auto-clean localStorage on first load (migration from old behavior)
  localStorage.removeItem('ecosim_campaign_id')
  localStorage.removeItem('ecosim_sim_id')
  localStorage.removeItem('ecosim_survey_id')
  localStorage.removeItem('ecosim_group_id')
  sessionStorage.removeItem('ecosim_sim_prep')

  // Auto-enable debug mode from URL: ?debug=1
  if (typeof window !== 'undefined') {
    const params = new URLSearchParams(window.location.search)
    if (params.get('debug') === '1') {
      debugMode.value = true
      console.log('[EcoSim] Debug mode enabled via URL parameter')
    }
  }

  return {
    campaignId, simId, surveyId, groupId, campaignSpec,
    loading, error, debugMode,
    simPrepData,
    completedSteps,
    // Step locking
    STEP_ORDER, EXTENDED_STEPS,
    completeStep, isStepCompleted, isStepUnlocked, getNextUnlockedStep,
    enableDebugMode,
    // Setters
    setCampaignId, setCampaignSpec, setSimId, setSurveyId, setGroupId,
    setSimPrepData, clearSimPrepData,
    setLoading, setError, clearError,
    hasCampaign, hasSim, hasSurvey,
    reset,
  }
})
