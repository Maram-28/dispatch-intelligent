import React from 'react'

export function DetailGroup({ label, value, color }) {
  return (
    <div>
      <div style={{ fontSize: '11px', fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase', marginBottom: '4px' }}>{label}</div>
      <div style={{ fontSize: '15px', fontWeight: 600, color: color || '#1e293b' }}>{value}</div>
    </div>
  )
}
