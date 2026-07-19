import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useReviewStore } from './review'

describe('review store', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('moves through the four review steps without exceeding the bounds', () => {
    const store = useReviewStore()

    expect(store.currentStep).toBe(1)
    store.nextStep()
    store.nextStep()
    store.nextStep()
    store.nextStep()
    expect(store.currentStep).toBe(4)

    store.previousStep()
    store.previousStep()
    store.previousStep()
    store.previousStep()
    expect(store.currentStep).toBe(1)

    store.goToStep(99)
    expect(store.currentStep).toBe(4)
    store.goToStep(-2)
    expect(store.currentStep).toBe(1)
  })

  it('updates template, clauses, tuning and approval state locally', () => {
    const store = useReviewStore()

    store.selectTemplate('services')
    store.toggleClause('payment-terms')
    store.setSensitivity(72)
    store.completeAnalysis()
    store.approveDraft()

    expect(store.selectedTemplateId).toBe('services')
    expect(store.clauses.find((item) => item.id === 'payment-terms')?.enabled).toBe(false)
    expect(store.sensitivity).toBe(72)
    expect(store.analysisStatus).toBe('approved')
  })

  it('supports rejecting changes and ignores unknown clauses', () => {
    const store = useReviewStore()
    const enabledCount = store.clauses.filter((item) => item.enabled).length

    store.toggleClause('missing-clause')
    store.rejectChanges()

    expect(store.clauses.filter((item) => item.enabled)).toHaveLength(enabledCount)
    expect(store.analysisStatus).toBe('rejected')
  })

  it('clamps sensitivity to the supported percentage range', () => {
    const store = useReviewStore()

    store.setSensitivity(-10)
    expect(store.sensitivity).toBe(0)

    store.setSensitivity(105)
    expect(store.sensitivity).toBe(100)
  })

  it('does not toggle disabled clauses', () => {
    const store = useReviewStore()
    const clause = store.clauses.find((item) => item.id === 'non-compete')

    expect(clause?.disabled).toBe(true)
    expect(clause?.enabled).toBe(false)
    store.toggleClause('non-compete')
    expect(clause?.enabled).toBe(false)
  })
})
