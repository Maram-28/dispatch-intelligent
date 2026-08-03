import React from 'react'

export function NavItem({ icon, label, active, onClick }) {
  return (
    <button type="button" className={`nav-item ${active ? 'active' : ''}`} onClick={onClick}>
      {icon}
      <span>{label}</span>
    </button>
  )
}
