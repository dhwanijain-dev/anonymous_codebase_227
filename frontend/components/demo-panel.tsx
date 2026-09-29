'use client'

import { useState } from 'react'
import { Sparkles, ChevronDown, ChevronUp } from 'lucide-react'
import { DEMO_PANEL_ITEMS, DEMO_QUERIES, type DemoScenarioKey } from '@/lib/demo-scenarios'

interface Props {
  onSelect: (query: string) => void
}

export function DemoQueryPanel({ onSelect }: Props) {
  const [open, setOpen] = useState(false)

  return (
    <div className="demo-panel-wrap">
      <button
        className="demo-panel-toggle"
        onClick={() => setOpen(!open)}
        type="button"
        aria-expanded={open}
      >
        <Sparkles />
        <span>Demo Scenarios</span>
        {open ? <ChevronUp /> : <ChevronDown />}
      </button>
      {open && (
        <div className="demo-panel-dropdown">
          {DEMO_PANEL_ITEMS.map(({ key, label }) => (
            <button
              key={key}
              className="demo-panel-item"
              type="button"
              onClick={() => {
                onSelect(DEMO_QUERIES[key].full)
                setOpen(false)
              }}
            >
              {label}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
