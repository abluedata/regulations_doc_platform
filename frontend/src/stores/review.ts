import { defineStore } from 'pinia'
import { ref } from 'vue'
import type {
  ReviewAnalysisStatus,
  ReviewClause,
  ReviewFile,
  ReviewRisk,
  ReviewTemplate,
} from '@/types'

const DEMO_FILES: ReviewFile[] = [
  { id: 'msa-services', name: 'MSA_Corp_Services_v2.pdf', size: '1.4 MB', progress: 100, status: 'ready' },
  { id: 'nda-standard', name: 'NDA_Standard_Final.docx', size: '892 KB', progress: 68, status: 'uploading' },
  { id: 'lease-annex', name: 'Lease_Agreement_Annex_A.pdf', size: '4.2 MB', progress: 0, status: 'queued' },
]

const DEMO_TEMPLATES: ReviewTemplate[] = [
  {
    id: 'mutual-nda',
    name: '互保密协议',
    category: '保密协议',
    description: '用于商业探索期间相互交换信息的标准保密协议。',
    checks: 18,
    icon: 'lock',
    popular: true,
  },
  {
    id: 'services',
    name: '主服务协议',
    category: '商业合同',
    description: '覆盖服务范围、付款、责任和终止条件的商业合同审查。',
    checks: 24,
    icon: 'description',
  },
  {
    id: 'employment-agreement',
    name: '录用通知书',
    category: '人事政策',
    description: '包含竞业禁止和知识产权转让条款的高管级雇佣协议。',
    checks: 15,
    icon: 'badge',
  },
  {
    id: 'ip-assignment',
    name: '知识产权转让',
    category: '知识产权法',
    description: '知识产权、发明和专利代码资产的法律转让。',
    checks: 21,
    icon: 'copyright',
  },
  {
    id: 'lease-agreement',
    name: '租赁协议',
    category: '房地产',
    description: '专注于租金递增和维护义务的商业房地产租赁分析。',
    checks: 42,
    icon: 'real_estate_agent',
  },
]

const DEMO_CLAUSES: ReviewClause[] = [
  {
    id: 'payment-terms',
    group: 'finance',
    title: '付款条款',
    description: '监控 Net-X 天数及提前付款折扣。',
    enabled: true,
    threshold: '阈值: 30 天',
  },
  {
    id: 'liability-cap',
    group: 'finance',
    title: '责任限额',
    description: '累计法律责任限额与合同价值对比。',
    enabled: true,
    priority: 'high',
  },
  {
    id: 'data-privacy',
    group: 'compliance',
    title: '数据隐私',
    description: 'GDPR/CCPA 数据传输协议。',
    enabled: true,
  },
  {
    id: 'non-compete',
    group: 'compliance',
    title: '竞业禁止',
    description: '限制性契约及适用范围。',
    enabled: false,
    disabled: true,
  },
]

const DEMO_RISKS: ReviewRisk[] = [
  {
    id: 'unlimited-liability',
    level: 'high',
    section: '第 3.1 节',
    title: '无限制责任',
    description: '该条款实际上取消了对间接损害的限制，使公司面临无限的潜在索赔风险。',
    currentText: '“total aggregate liability... limited to $5,000,000 USD.”',
    referenceText: '“Liability shall be limited to 1x the annual contract value.”',
  },
  {
    id: 'termination-notice',
    level: 'medium',
    section: '第 6.2 节',
    title: '非标准终止条款',
    description: '90 天的通知期长于标准 30 天的公司政策。',
  },
  {
    id: 'ambiguous-definition',
    level: 'low',
    section: '第 1.4 节',
    title: '定义模糊',
    description: '“交付物”的定义可以更加细化，以保护核心专有知识产权。',
  },
]

export const useReviewStore = defineStore('review', () => {
  const currentStep = ref(1)
  const selectedTemplateId = ref('mutual-nda')
  const sensitivity = ref(85)
  const analysisStatus = ref<ReviewAnalysisStatus>('idle')
  const files = ref<ReviewFile[]>(DEMO_FILES.map((item) => ({ ...item })))
  const templates = ref<ReviewTemplate[]>(DEMO_TEMPLATES.map((item) => ({ ...item })))
  const clauses = ref<ReviewClause[]>(DEMO_CLAUSES.map((item) => ({ ...item })))
  const risks = ref<ReviewRisk[]>(DEMO_RISKS.map((item) => ({ ...item })))

  function nextStep() {
    currentStep.value = Math.min(4, currentStep.value + 1)
  }

  function previousStep() {
    currentStep.value = Math.max(1, currentStep.value - 1)
  }

  function goToStep(step: number) {
    currentStep.value = Math.min(4, Math.max(1, step))
  }

  function selectTemplate(id: string) {
    selectedTemplateId.value = id
  }

  function toggleClause(id: string) {
    const clause = clauses.value.find((item) => item.id === id)
    if (!clause || clause.disabled) return
    clause.enabled = !clause.enabled
  }

  function setSensitivity(value: number) {
    sensitivity.value = Math.min(100, Math.max(0, Math.round(value)))
  }

  function completeAnalysis() {
    analysisStatus.value = 'complete'
  }

  function approveDraft() {
    analysisStatus.value = 'approved'
  }

  function rejectChanges() {
    analysisStatus.value = 'rejected'
  }

  return {
    currentStep,
    selectedTemplateId,
    sensitivity,
    analysisStatus,
    files,
    templates,
    clauses,
    risks,
    nextStep,
    previousStep,
    goToStep,
    selectTemplate,
    toggleClause,
    setSensitivity,
    completeAnalysis,
    approveDraft,
    rejectChanges,
  }
})
