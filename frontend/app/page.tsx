'use client'

import { useRef, useState } from 'react'
import {
  Activity,
  AreaChart,
  Bell,
  CalendarDays,
  ChevronDown,
  Crosshair,
  FileImage,
  Globe2,
  ImagePlus,
  Layers3,
  Link2,
  Map,
  Menu,
  MessageSquare,
  PanelLeftClose,
  Plus,
  Send,
  Settings,
  Satellite,
  Search,
  SlidersHorizontal,
  Sparkles,
  Upload,
  X,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { detectDemoScenario, DEMO_QUERIES, type DemoScenarioKey } from '@/lib/demo-scenarios'
import { DemoResponseRenderer } from '@/components/demo-responses'
import { DemoQueryPanel } from '@/components/demo-panel'

const suggestions = [
  DEMO_QUERIES.semantic.full,
  DEMO_QUERIES.change.full,
  DEMO_QUERIES.discovery.short,
  DEMO_QUERIES.review.short,
]
const starterRecent = [
  'Semantic search · construction',
  'Change analysis · before/after',
  'Quality engine · seasonal check',
  'Discovery · similar sites',
  'Review queue · candidate changes',
]

export default function Page() {
  const [query, setQuery] = useState('')
  const [files, setFiles] = useState<File[]>([])
  const [submitted, setSubmitted] = useState('')
  const [isGenerating, setIsGenerating] = useState(false)
  const [recent, setRecent] = useState(starterRecent)
  const [showFilters, setShowFilters] = useState(false)
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [demoScenario, setDemoScenario] = useState<DemoScenarioKey | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  function submit(value = query) {
    if ((!value.trim() && files.length === 0) || isGenerating) return
    const nextPrompt = value.trim() || 'Analyze the attached imagery'
    const detected = detectDemoScenario(nextPrompt)
    setIsGenerating(true)
    setSubmitted('')
    setDemoScenario(null)
    setRecent((items) => [nextPrompt, ...items.filter((item) => item !== nextPrompt)].slice(0, 8))
    const delay = detected ? 1200 : 1800
    window.setTimeout(() => {
      setSubmitted(nextPrompt)
      setDemoScenario(detected)
      setIsGenerating(false)
    }, delay)
  }

  function startNewChat() {
    setQuery('')
    setSubmitted('')
    setFiles([])
    setIsGenerating(false)
    setDemoScenario(null)
    setRecent((items) => ['New chat', ...items.filter((item) => item !== 'New chat')].slice(0, 8))
  }

  function selectSuggestion(value: string) {
    setQuery(value)
    submit(value)
  }

  return (
    <main className="drishti-shell">
      <aside className={`sidebar ${sidebarOpen ? '' : 'sidebar-collapsed'}`}>
        <div className="brand-row">
          <div className="brand-mark"><span>▲</span></div>
          <div className="brand-copy"><strong>DRISHTI</strong><span>Geospatial Intelligence Assistant</span><small>Ministry of Defence (Indian Army)</small></div>
          <button className="icon-button sidebar-toggle" aria-label="Collapse sidebar" onClick={() => setSidebarOpen(false)}><PanelLeftClose /></button>
        </div>
        <Button className="new-chat" onClick={startNewChat}><Plus data-icon="inline-start" /> New Chat</Button>
        <nav className="nav-list" aria-label="Primary navigation">
          <button onClick={() => selectSuggestion(DEMO_QUERIES.semantic.full)}><Sparkles /> Semantic Search</button>
          <button onClick={() => selectSuggestion(DEMO_QUERIES.change.full)}><Activity /> Change Analysis</button>
          <button onClick={() => selectSuggestion(DEMO_QUERIES.quality.full)}><Layers3 /> Quality Engine</button>
          <button onClick={() => selectSuggestion(DEMO_QUERIES.discovery.full)}><Map /> Discovery</button>
          <button onClick={() => selectSuggestion(DEMO_QUERIES.review.full)}><FileImage /> Review Queue</button>
        </nav>
        <div className="recent-heading"><span>Recent Chats</span><Search /></div>
        <div className="recent-list">{recent.map((item, i) => <button key={item} onClick={() => selectSuggestion(item)}><MessageSquare /><span>{item}<small>{i + 2} {i === 0 ? 'hours' : 'days'} ago</small></span></button>)}</div>
        <div className="analysis-area"><div className="area-avatar">⌁</div><div><strong>Analysis Area</strong><span>Ladakh Sector</span><small>34.2° N, 77.6° E</small></div><Settings /></div>
      </aside>

      {!sidebarOpen && <button className="open-sidebar" onClick={() => setSidebarOpen(true)} aria-label="Open sidebar"><Menu /></button>}
      <section className="workspace">
        <header className="topbar"><div className="topbar-spacer" /><button className="world-select"><Globe2 /> World View <ChevronDown /></button><button className="top-icon"><span>☼</span></button><button className="top-icon"><Bell /></button><div className="profile">DJ</div></header>
        {!submitted && !isGenerating && <div className="hero" style={{ backgroundImage: `linear-gradient(180deg, rgba(255,255,255,.08), rgba(255,255,255,.92) 82%), ` }}>
          <div className="hero-copy"><div className="eyebrow">O B S E R V E<br />U N D E R S T A N D<br />A N T I C I P A T E</div><div className="hero-title"><h1>DRISHTI</h1><p>Your Geospatial Intelligence Assistant</p><span>Search. Analyse. Discover. Monitor Change.</span><i /></div><div className="feature-pills"><span><Satellite /> Satellite Imagery</span><span><AreaChart /> Multi-temporal Analysis</span><span><Link2 /> Semantic Search</span><span><Layers3 /> Discovery &amp; Clustering</span></div></div>
        </div>}
        <div className={`content-area ${submitted || isGenerating ? 'chat-mode' : ''} ${isGenerating ? 'content-generating' : ''}`}>
          {isGenerating && <div className="generation-state" role="status"><div className="shimmer-orbit"><Sparkles /></div><div><strong>Generating intelligence</strong><span>Scanning the simulated archive · classifying observations · ranking results</span></div><div className="shimmer-line" /></div>}
          {submitted && <div className="conversation">
            <div className="chat-row user-row"><div className="profile small">DJ</div><div className="user-prompt"><p>{submitted}</p>{files.length > 0 && <small>{files.length} attachment{files.length > 1 ? 's' : ''} included</small>}</div></div>
            {demoScenario ? (
              <div className="chat-row assistant-row"><div className="mini-logo">▲</div><DemoResponseRenderer scenario={demoScenario} /></div>
            ) : (
              <div className="chat-row assistant-row"><div className="mini-logo">▲</div><div className="assistant-message"><div className="assistant-label"><strong>Drishti Intelligence</strong><span className="status-dot" /> Response</div><p>This query did not match a demo scenario. Use the <b>Demo Scenarios</b> panel below or try one of the sidebar options to see the full simulation.</p></div></div>
            )}
          </div>}
          <div className="composer-wrap">
            <div className="composer-top"><textarea value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing && e.keyCode !== 229) { e.preventDefault(); submit() } }} placeholder="Ask a question about satellite imagery..." aria-label="Ask a question about satellite imagery" />
              <button className="attach-icon" aria-label="Attach image" onClick={() => fileRef.current?.click()}><ImagePlus /></button><input ref={fileRef} type="file" accept="image/*,video/*" multiple hidden onChange={(e) => setFiles(Array.from(e.target.files || []).slice(0, 2))} /></div>
            {files.length > 0 && <div className="attachments">{files.map((file) => <div className="attachment" key={file.name}><FileImage /><span>{file.name}</span><button onClick={() => setFiles(files.filter((f) => f.name !== file.name))}><X /></button></div>)}</div>}
            <div className="composer-actions"><Button variant="secondary" onClick={() => fileRef.current?.click()}><ImagePlus data-icon="inline-start" /> Add Image</Button><Button variant="secondary"><Crosshair data-icon="inline-start" /> Area of Interest</Button><Button variant="secondary"><CalendarDays data-icon="inline-start" /> Date Range</Button><Button variant="secondary"><Satellite data-icon="inline-start" /> Sensor</Button><Button variant="secondary" onClick={() => setShowFilters(!showFilters)}><SlidersHorizontal data-icon="inline-start" /> More Filters</Button><Button className="send-button" onClick={() => submit()} aria-label="Run analysis"><Send /></Button></div>
            {showFilters && <div className="filter-panel"><label>From<input type="date" defaultValue="2023-01-01" /></label><label>To<input type="date" defaultValue="2024-12-31" /></label><label>Sensor<select defaultValue="Any"><option>Any</option><option>Sentinel-2</option><option>SAR</option></select></label><label>Minimum quality<input type="range" min="0" max="1" step=".1" defaultValue=".5" /></label></div>}
          </div>
          {!submitted && <div className="suggestions"><span>Try asking</span>{suggestions.map((item) => <button key={item} onClick={() => selectSuggestion(item)}>{item}</button>)}</div>}
          <DemoQueryPanel onSelect={(q) => setQuery(q)} />

        </div>
      </section>
    </main>
  )
}
