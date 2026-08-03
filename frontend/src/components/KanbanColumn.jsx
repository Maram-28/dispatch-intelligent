import React from 'react'
import { TicketCard } from './TicketCard'

export function KanbanColumn({ title, count, tickets, onTicketClick, icon }) {
  return (
    <div className="kanban-column">
      <div className="column-header">
        <span className="column-title" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          {icon && icon}{title}
        </span>
        <span className="column-count">{count}</span>
      </div>
      {tickets.map(ticket => (
        <TicketCard key={ticket.id} {...ticket} onClick={() => onTicketClick(ticket)} />
      ))}
    </div>
  )
}
