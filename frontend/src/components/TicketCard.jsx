import React from 'react'
import { Clock, TrendingUp, CheckCircle2 } from 'lucide-react'
import { useLanguage } from '../hooks/useLanguage'

export function TicketCard({ title, desc, category, priority, confidence, agent, time, status, onClick }) {
  const { t } = useLanguage()
  const isDone = status === 'Done'
  return (
    <div
      className="ticket-card"
      onClick={onClick}
      style={isDone ? { opacity: 0.65, borderLeft: '3px solid #10b981' } : undefined}
    >
      <div className="ticket-tags">
        <span className={`tag-priority tag-${priority.toLowerCase()}`}>{priority}</span>
        <span className="tag-category">{category}</span>
        {isDone
          ? <span style={{ display: 'flex', alignItems: 'center', gap: '3px', fontSize: '11px', color: '#10b981', fontWeight: 600 }}>
              <CheckCircle2 size={12} /> {t('ticketDetails.statusDone')}
            </span>
          : <span className="ticket-confidence"><TrendingUp size={12} /> {confidence}%</span>
        }
      </div>
      <h3 className="ticket-title">{title}</h3>
      <p className="ticket-desc">{desc}</p>
      <div className="ticket-footer">
        <div className="ticket-agent">
          <div className="agent-avatar"></div>
          {agent}
        </div>
        <div className="ticket-time">
          <Clock size={12} /> {time}
        </div>
      </div>
    </div>
  )
}
