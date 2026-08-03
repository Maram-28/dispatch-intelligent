import React, { useState } from 'react'
import { motion } from 'framer-motion'
import { CheckCircle2, User } from 'lucide-react'
import { useLanguage } from '../hooks/useLanguage'

export function ClassificationModal({ onClose, onSubmit, isClassifying, result }) {
  const { t } = useLanguage()
  const [formData, setFormData] = useState(() => ({
    numero: `INC${Math.floor(Math.random() * 100000)}`,
    breve_description: '',
    description: '',
    entreprise: ''
  }))

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000, backdropFilter: 'blur(4px)' }}>
      <motion.div
        initial={{ scale: 0.9, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        style={{ background: 'white', padding: '32px', borderRadius: '16px', width: '550px', boxShadow: '0 20px 25px -5px rgba(0,0,0,0.1)' }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px' }}>
          <h2 style={{ fontSize: '20px', fontWeight: 700 }}>{t('classification.title')}</h2>
          {result && <span style={{ color: '#10b981', fontSize: '12px', fontWeight: 600, display: 'flex', alignItems: 'center', gap: 4 }}><CheckCircle2 size={14}/> {t('classification.analysisComplete')}</span>}
        </div>

        {!result ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            <div>
              <label style={{ display: 'block', fontSize: '13px', fontWeight: 600, marginBottom: '6px' }}>{t('classification.shortDescription')}</label>
              <input
                style={{ width: '100%', padding: '10px', borderRadius: '8px', border: '1px solid #e2e8f0', boxSizing: 'border-box' }}
                placeholder={t('classification.shortDescriptionPlaceholder')}
                value={formData.breve_description}
                onChange={e => setFormData({ ...formData, breve_description: e.target.value })}
              />
            </div>
            <div>
              <label style={{ display: 'block', fontSize: '13px', fontWeight: 600, marginBottom: '6px' }}>{t('classification.fullDescription')}</label>
              <textarea
                style={{ width: '100%', padding: '10px', borderRadius: '8px', border: '1px solid #e2e8f0', minHeight: '100px', boxSizing: 'border-box' }}
                placeholder={t('classification.fullDescriptionPlaceholder')}
                value={formData.description}
                onChange={e => setFormData({ ...formData, description: e.target.value })}
              />
            </div>
            <div>
              <label style={{ display: 'block', fontSize: '13px', fontWeight: 600, marginBottom: '6px' }}>{t('classification.companyBrand')}</label>
              <input
                style={{ width: '100%', padding: '10px', borderRadius: '8px', border: '1px solid #e2e8f0', boxSizing: 'border-box' }}
                placeholder={t('classification.companyBrandPlaceholder')}
                value={formData.entreprise}
                onChange={e => setFormData({ ...formData, entreprise: e.target.value })}
              />
            </div>
            <div style={{ display: 'flex', gap: '12px', marginTop: '12px' }}>
              <button
                onClick={onClose}
                style={{ flex: 1, padding: '12px', borderRadius: '8px', border: '1px solid #e2e8f0', background: 'white', cursor: 'pointer' }}
              >
                {t('common.cancel')}
              </button>
              <button
                disabled={isClassifying || !formData.breve_description}
                onClick={() => onSubmit(formData)}
                style={{
                  flex: 1,
                  padding: '12px',
                  borderRadius: '8px',
                  border: 'none',
                  background: isClassifying ? '#94a3b8' : '#f6c026',
                  color: '#000',
                  fontWeight: 600,
                  cursor: isClassifying ? 'not-allowed' : 'pointer'
                }}
              >
                {isClassifying ? t('classification.analyzing') : t('classification.classify')}
              </button>
            </div>
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
            <div style={{ background: '#f8fafc', padding: '16px', borderRadius: '12px', border: '1px solid #e2e8f0' }}>
              <div style={{ display: 'flex', gap: '24px', marginBottom: '16px', flexWrap: 'wrap' }}>
                <div>
                  <div style={{ fontSize: '11px', color: '#64748b', fontWeight: 600, textTransform: 'uppercase' }}>{t('ticketDetails.category')}</div>
                  <div style={{ fontWeight: 600 }}>{result.categorie}</div>
                </div>
                <div>
                  <div style={{ fontSize: '11px', color: '#64748b', fontWeight: 600, textTransform: 'uppercase' }}>{t('ticketDetails.priority')}</div>
                  <div style={{ fontWeight: 600, color: '#ef4444' }}>{result.priorite_calculee}</div>
                </div>
                <div>
                  <div style={{ fontSize: '11px', color: '#64748b', fontWeight: 600, textTransform: 'uppercase' }}>{t('classification.confidence')}</div>
                  <div style={{ fontWeight: 600, color: '#f6c026' }}>{Math.round(result.confidence * 100)}%</div>
                </div>
              </div>
              <div>
                <div style={{ fontSize: '11px', color: '#64748b', fontWeight: 600, textTransform: 'uppercase', marginBottom: '4px' }}>{t('ticketDetails.aiReasoning')}</div>
                <div style={{ fontSize: '13px', lineHeight: 1.5 }}>{result.reasoning}</div>
              </div>
            </div>

            {result.assigned_to && (
              <div style={{ background: '#fffbeb', padding: '16px', borderRadius: '12px', border: '1px solid #fde68a', display: 'flex', alignItems: 'center', gap: '12px' }}>
                <div style={{ background: '#f6c026', borderRadius: '50%', width: '40px', height: '40px', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                  <User size={20} color="#000" />
                </div>
                <div>
                  <div style={{ fontSize: '11px', color: '#92400e', fontWeight: 600, textTransform: 'uppercase', marginBottom: '2px' }}>{t('classification.assignedTo')}</div>
                  <div style={{ fontWeight: 700, fontSize: '15px' }}>{result.assigned_to.nom}</div>
                  <div style={{ fontSize: '12px', color: '#78716c', marginTop: '2px' }}>
                    {t('ticketDetails.assignmentScore')} {Math.round(result.assigned_to.score_assignation * 100)}%
                  </div>
                </div>
              </div>
            )}

            <button
              onClick={onClose}
              style={{ width: '100%', padding: '12px', borderRadius: '8px', border: 'none', background: '#000', color: '#fff', fontWeight: 600, cursor: 'pointer' }}
            >
              {t('classification.finish')}
            </button>
          </div>
        )}
      </motion.div>
    </div>
  )
}
