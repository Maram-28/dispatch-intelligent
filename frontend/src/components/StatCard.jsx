import React from 'react'

export function StatCard({ label, value, trend, icon }) {
  return (
    <div className="stat-card">
      <div className="stat-label">
        {icon} {label} {trend && <span className={`stat-trend ${trend.startsWith('+') ? 'trend-up' : 'trend-down'}`}>{trend}</span>}
      </div>
      <div className="stat-value">
        {value}
      </div>
    </div>
  )
}
