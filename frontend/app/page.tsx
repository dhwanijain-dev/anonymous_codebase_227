'use client'

import { useMemo, useRef, useState } from 'react'
import {
  Activity,
  AreaChart,
  Bell,
  CalendarDays,
  ChevronDown,
  ChevronLeft,
  CircleHelp,
  Crosshair,
  FileImage,
  Filter,
  Globe2,
  ImagePlus,
  Layers3,
  Link2,
  Map,
  Menu,
  MessageSquare,
  MoreHorizontal,
  Paperclip,
  PanelLeftClose,
  Plus,
  Send,
  Settings,
  Satellite,
  Search,
  SlidersHorizontal,
  Sparkles,
  Target,
  Upload,
  X,
  Zap,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { detectDemoScenario, type DemoScenarioKey } from '@/lib/demo-scenarios'
import { DemoResponseRenderer } from '@/components/demo-responses'
import { DemoQueryPanel } from '@/components/demo-panel'

type Result = { id: number; title: string; date: string; score: string; tone: string }

// const heroImage = 'https://hebbkx1anhila5yf.public.blob.vercel-storage.com/image.png-PgqJikL117i8ucund9m8w47ciRtBeH.jpeg'
const suggestions = [
  'Show me newly built structures near a river',
  'Find vehicle concentrations in Ladakh',
  'Map water body changes from 2023 to 2024',
  'Compare agricultural expansion in this area',
]
const starterRecent = ['New structures near river', 'Vehicle concentration analysis', 'Border road development', 'Water extent change', 'Similar sites to this location', 'Agricultural expansion', 'Run change analysis (2020–2024)']
const scenarios = [
  { label: 'Semantic Search', prompt: 'Show me newly built structures near a river', input: 'Wide-area overhead satellite image with a visible river, roads, rooftops, and settlement edges.', output: 'Ranked satellite tiles with construction footprints and newly detected structures highlighted.', classification: 'Semantic search · object detection' },
  { label: 'Change Analysis', prompt: 'Compare water extent change from 2023 to 2024', input: 'Two aligned images of the same area: 2023 before image followed by 2024 after image.', output: 'Before/after viewer with water boundaries, detected change type, and earliest occurrence.', classification: 'Multi-temporal · change detection' },
  { label: 'Quality Engine', prompt: 'Check whether this apparent change is cloud or seasonal variation', input: 'Two or more images with visible haze, clouds, snow, or seasonal vegetation differences.', output: 'Confidence score explaining why the variation is not meaningful structural change.', classification: 'Quality scoring · false-positive rejection' },
  { label: 'Discovery & Clustering', prompt: 'Find similar sites to this confirmed location', input: 'One clear overhead image of a confirmed outpost, facility, road junction, or interesting site.', output: 'Clustered similar locations across a map/grid with similarity scores and distribution.', classification: 'Image embeddings · clustering' },
  { label: 'Review Queue', prompt: 'Open the ranked review queue for this area', input: 'One scene or a change-analysis result containing multiple candidate observations.', output: 'Review candidates with before/after evidence, confirm/reject actions, and provenance metadata.', classification: 'Human review · provenance' },
  { label: 'Offline Ingestion', prompt: 'Ingest this GeoTIFF into the offline search index', input: 'A GeoTIFF or Cloud-Optimized GeoTIFF (COG) scene with acquisition metadata.', output: 'Processing progress, indexed scene confirmation, and availability in subsequent search.', classification: 'GeoTIFF/COG · offline indexing' },
]

function makeResults(query: string): Result[] {
  const lower = query.toLowerCase()
  const subject = lower.includes('water') ? 'Water boundary change' : lower.includes('quality') || lower.includes('cloud') || lower.includes('seasonal') ? 'Quality review' : lower.includes('similar') || lower.includes('site') ? 'Similar site' : lower.includes('queue') || lower.includes('review') ? 'Review candidate' : lower.includes('geotiff') || lower.includes('ingest') ? 'Indexed scene' : lower.includes('vehicle') ? 'Vehicle concentration' : 'New structure detected'
  return Array.from({ length: 8 }, (_, i) => ({ id: i, title: i === 0 ? subject : `${subject} · sector ${String.fromCharCode(65 + i)}`, date: `202${3 + (i % 2)}-${String(i + 1).padStart(2, '0')}-${String(10 + i).padStart(2, '0')}`, score: (0.96 - i * 0.06).toFixed(2), tone: ['#9ab68c', '#b7a985', '#789b83', '#bcae7b'][i % 4] }))
}

export default function Page() {
  const [query, setQuery] = useState('')
  const [files, setFiles] = useState<File[]>([])
  const [submitted, setSubmitted] = useState('')
  const [isGenerating, setIsGenerating] = useState(false)
  const [recent, setRecent] = useState(starterRecent)
  const [showFilters, setShowFilters] = useState(false)
  const [showHelp, setShowHelp] = useState(false)
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [selected, setSelected] = useState<Result | null>(null)
  const [demoScenario, setDemoScenario] = useState<DemoScenarioKey | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const results = useMemo(() => makeResults(submitted || 'new structures near river'), [submitted])
  const mode = files.length > 1 ? 'Change analysis' : files.length === 1 ? 'Similar imagery' : submitted.toLowerCase().includes('queue') || submitted.toLowerCase().includes('review') ? 'Review queue' : submitted.toLowerCase().includes('geotiff') || submitted.toLowerCase().includes('ingest') ? 'Offline ingestion' : submitted.toLowerCase().includes('quality') || submitted.toLowerCase().includes('cloud') || submitted.toLowerCase().includes('seasonal') ? 'Quality engine' : submitted.toLowerCase().includes('similar') || submitted.toLowerCase().includes('site') ? 'Discovery & clustering' : 'Semantic search'

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
          <button onClick={() => selectSuggestion('Show me newly built structures near a river')}><Sparkles /> Explore</button><button onClick={() => selectSuggestion('Find similar sites across the map')}><Map /> Map View</button><button onClick={() => selectSuggestion('Compare water extent change from 2023 to 2024')}><Activity /> Change Analysis</button><button onClick={() => selectSuggestion('Find similar sites to this confirmed location')}><Link2 /> Similar Locations</button><button onClick={() => selectSuggestion('Ingest this GeoTIFF into the offline search index')}><Upload /> Ingest Data</button><button onClick={() => selectSuggestion('Open the ranked review queue for this area')}><FileImage /> Review Queue</button>
        </nav>
        <div className="recent-heading"><span>Recent Chats</span><Search /></div>
        <div className="recent-list">{recent.map((item, i) => <button key={item} onClick={() => selectSuggestion(item)}><MessageSquare /><span>{item}<small>{i + 2} {i === 0 ? 'hours' : 'days'} ago</small></span></button>)}</div>
        <div className="analysis-area"><div className="area-avatar">⌁</div><div><strong>Analysis Area</strong><span>Ladakh Sector</span><small>34.2° N, 77.6° E</small></div><Settings /></div>
      </aside>

      {!sidebarOpen && <button className="open-sidebar" onClick={() => setSidebarOpen(true)} aria-label="Open sidebar"><Menu /></button>}
      <section className="workspace">
        <header className="topbar"><div className="topbar-spacer" /><button className="world-select"><Globe2 /> World View <ChevronDown /></button><button className="top-icon"><span>☼</span></button><button className="top-icon"><Bell /></button><div className="profile">DJ</div></header>
        {!submitted && !isGenerating && <div className="hero" style={{ backgroundImage: `linear-gradient(180deg, rgba(255,255,255,.08), rgba(255,255,255,.92) 82%), ` }}>
          <div className="hero-copy"><div className="eyebrow">O B S E R V E<br />U N D E R S T A N D<br />A N T I C I P A T E</div><div className="hero-title"><h1>DRISHTI</h1><p>Your Geospatial Intelligence Assistant</p><span>Search. Analyse. Discover. Monitor Change.</span><i /></div><div className="feature-pills"><span><Satellite /> Satellite Imagery</span><span><AreaChart /> Multi-temporal Analysis</span><span><Link2 /> Semantic Search</span><span><Layers3 /> Discovery & Clustering</span></div></div>
        </div>}
        <div className={`content-area ${submitted || isGenerating ? 'chat-mode' : ''} ${isGenerating ? 'content-generating' : ''}`}>
          {isGenerating && <div className="generation-state" role="status"><div className="shimmer-orbit"><Sparkles /></div><div><strong>Generating intelligence</strong><span>Scanning the simulated archive · classifying observations · ranking results</span></div><div className="shimmer-line" /></div>}
          {submitted && <div className="conversation"><div className="chat-row user-row"><div className="profile small">DJ</div><div className="user-prompt"><p>{submitted}</p>{files.length > 0 && <small>{files.length} attachment{files.length > 1 ? 's' : ''} included</small>}</div></div>{demoScenario ? <div className="chat-row assistant-row"><div className="mini-logo">▲</div><DemoResponseRenderer scenario={demoScenario} /></div> : <><div className="chat-row assistant-row"><div className="mini-logo">▲</div><div className="assistant-message"><div className="assistant-label"><strong>Drishti Intelligence</strong><span className="status-dot" /> Simulated result</div><p>I analyzed your request using the simulated geospatial archive. I found {results.length} ranked observations matching this intent, classified as <b>{mode}</b>.</p></div></div><section className="results chat-results"><div className="results-heading"><div><span className="eyebrow dark">SIMULATED ARCHIVE RESPONSE</span><h2>{results.length} matching observations</h2><p>Ranked by relevance · {mode} · 42 ms</p></div><Button variant="outline"><Filter data-icon="inline-start" /> Refine results</Button></div><div className="result-grid">{results.map((result) => <button className="result-card" key={result.id} onClick={() => setSelected(result)}><div className="sat-tile" style={{ background: `linear-gradient(135deg, transparent 40%, rgba(29,77,65,.45) 41% 55%, transparent 56%), radial-gradient(circle at ${20 + result.id * 8}% ${28 + result.id * 5}%, rgba(54,113,83,.7), transparent 28%), repeating-linear-gradient(${result.id * 13}deg, ${result.tone}, #d4c38d 8px, #829d7e 18px)` }}><span>SCN-{String(3030 + result.id)}</span></div><div className="card-meta"><strong>#{result.id + 1} · {result.score}</strong><span>{result.title}</span><small>{result.date} · Sentinel-{result.id % 2 ? '2B' : '2A'}</small></div></button>)}</div></section></>}</div>}
          <div className="composer-wrap">
            <div className="composer-top"><textarea value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing && e.keyCode !== 229) { e.preventDefault(); submit() } }} placeholder="Ask a question about satellite imagery..." aria-label="Ask a question about satellite imagery" />
              <button className="examples">Examples <ChevronDown /></button><button className="attach-icon" aria-label="Attach image" onClick={() => fileRef.current?.click()}><ImagePlus /></button><input ref={fileRef} type="file" accept="image/*,video/*" multiple hidden onChange={(e) => setFiles(Array.from(e.target.files || []).slice(0, 2))} /></div>
            {files.length > 0 && <div className="attachments">{files.map((file) => <div className="attachment" key={file.name}><FileImage /><span>{file.name}</span><button onClick={() => setFiles(files.filter((f) => f.name !== file.name))}><X /></button></div>)}</div>}
            <div className="composer-actions"><Button variant="secondary" onClick={() => fileRef.current?.click()}><ImagePlus data-icon="inline-start" /> Add Image</Button><Button variant="secondary"><Crosshair data-icon="inline-start" /> Area of Interest</Button><Button variant="secondary"><CalendarDays data-icon="inline-start" /> Date Range</Button><Button variant="secondary"><Satellite data-icon="inline-start" /> Sensor</Button><Button variant="secondary" onClick={() => setShowFilters(!showFilters)}><SlidersHorizontal data-icon="inline-start" /> More Filters</Button><Button className="send-button" onClick={() => submit()} aria-label="Run analysis"><Send /></Button></div>
            {showFilters && <div className="filter-panel"><label>From<input type="date" defaultValue="2023-01-01" /></label><label>To<input type="date" defaultValue="2024-12-31" /></label><label>Sensor<select defaultValue="Any"><option>Any</option><option>Sentinel-2</option><option>SAR</option></select></label><label>Minimum quality<input type="range" min="0" max="1" step=".1" defaultValue=".5" /></label></div>}
            <div className="mode-line"><span>Detected search type</span><b>{mode}</b><code>{files.length > 1 ? 'POST /change/analyze' : files.length === 1 ? 'POST /search/image/upload' : 'POST /search/text'}</code></div>
          </div>
          {!submitted && <div className="suggestions"><span>Try asking</span>{suggestions.map((item) => <button key={item} onClick={() => selectSuggestion(item)}>{item}</button>)}</div>}
          <DemoQueryPanel onSelect={(q) => setQuery(q)} />

        </div>
      </section>
      {selected && <div className="detail-overlay" onClick={() => setSelected(null)}><aside className="detail-drawer" onClick={(e) => e.stopPropagation()}><div className="drawer-head"><div><span className="eyebrow dark">OBSERVATION DETAIL</span><h2>{selected.title}</h2></div><button className="icon-button" onClick={() => setSelected(null)}><X /></button></div><div className="large-tile sat-tile" style={{ background: `linear-gradient(135deg, transparent 40%, rgba(29,77,65,.45) 41% 55%, transparent 56%), repeating-linear-gradient(20deg, ${selected.tone}, #d4c38d 8px, #829d7e 18px)` }} /><div className="confidence"><div><span>Semantic match</span><b>{selected.score}</b></div><div className="confidence-bar"><i style={{ width: `${Number(selected.score) * 100}%` }} /></div></div><dl><dt>Location</dt><dd>34.201° N, 77.612° E</dd><dt>Acquired</dt><dd>{selected.date} 00:00 UTC</dd><dt>Platform</dt><dd>Sentinel-2A · MSI</dd><dt>Source file</dt><dd className="mono">/data/raw/demo/S2A_20230701.tif</dd><dt>Model</dt><dd className="mono">mock-rs-embed 1.0.0</dd></dl><div className="drawer-actions"><Button onClick={() => setSelected(null)}>Accept</Button><Button variant="outline" onClick={() => setSelected(null)}>Reject</Button><Button variant="outline">Export</Button></div></aside></div>}
      {showHelp && <div className="help-overlay" onClick={() => setShowHelp(false)}><div className="help-card" onClick={(e) => e.stopPropagation()}><button className="icon-button close-help" onClick={() => setShowHelp(false)}><X /></button><span className="eyebrow dark">DRISHTI SIMULATION</span><h2>How to use this mockup</h2><p>Everything here is simulated locally. Use these prepared demo scenarios to plan the real imagery you want to hardcode into your showcase video.</p><div className="scenario-list">{scenarios.map((scenario) => <article className="scenario" key={scenario.label}><div className="scenario-head"><strong>{scenario.label}</strong><span>{scenario.classification}</span></div><b>Prompt: “{scenario.prompt}”</b><span><em>Input image:</em> {scenario.input}</span><span><em>Mock response:</em> {scenario.output}</span><button onClick={() => { setQuery(scenario.prompt); setShowHelp(false) }}>Use this prompt</button></article>)}</div><Button onClick={() => setShowHelp(false)}>Continue exploring</Button></div></div>}
      <button className="help-button" onClick={() => setShowHelp(true)} aria-label="Open help"><CircleHelp /></button>
    </main>
  )
}
