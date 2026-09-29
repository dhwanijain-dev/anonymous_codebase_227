'use client'

import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { X, Check, XCircle, ChevronRight, Eye } from 'lucide-react'
import {
  DEMO_ASSETS,
  SEMANTIC_RESULTS,
  DISCOVERY_SITES,
  REVIEW_CANDIDATES,
  QUALITY_PANEL,
  type DemoScenarioKey,
} from '@/lib/demo-scenarios'

// ── Shared image component with graceful fallback ─────────────────────────────

function DemoImage({
  src,
  alt,
  className = '',
  onClick,
}: {
  src: string
  alt: string
  className?: string
  onClick?: () => void
}) {
  const [error, setError] = useState(false)
  if (error) {
    return (
      <div className={`demo-img-fallback ${className}`} title={`Missing: ${src}`}>
        <span>⚠ {src.split('/').pop()}</span>
      </div>
    )
  }
  return (
    <img
      src={src}
      alt={alt}
      className={`demo-img ${className}`}
      onError={() => setError(true)}
      onClick={onClick}
      draggable={false}
    />
  )
}

// ═══════════════════════════════════════════════════════════════════════════════
// 1. SEMANTIC SEARCH
// ═══════════════════════════════════════════════════════════════════════════════

export function SemanticResponse() {
  const { input, outputs } = DEMO_ASSETS.semantic
  return (
    <div className="demo-response">
      <div className="assistant-label">
        <strong>Drishti Intelligence</strong>
        <span className="status-dot" /> Semantic Search
      </div>

      <div className="demo-section">
        <span className="demo-section-label">QUERY IMAGE</span>
        <DemoImage src={input} alt="Query satellite image" className="demo-query-img" />
      </div>

      <p className="demo-text">
        I found <b>3</b> semantically similar scenes with potential structural development.
      </p>

      <div className="demo-result-grid three-col">
        {outputs.map((src, i) => {
          const meta = SEMANTIC_RESULTS[i]
          return (
            <div className="demo-result-card" key={i}>
              <DemoImage src={src} alt={`Semantic result ${i + 1}`} className="demo-card-img" />
              <div className="demo-card-body">
                <div className="demo-card-row">
                  <strong>Match {meta.similarity}%</strong>
                  <span className="demo-tag">{meta.tag}</span>
                </div>
                <p>{meta.description}</p>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════════════════════
// 2. CHANGE ANALYSIS
// ═══════════════════════════════════════════════════════════════════════════════

export function ChangeResponse() {
  const { before, after, difference, annotated } = DEMO_ASSETS.change
  const [activeView, setActiveView] = useState<'before' | 'after' | 'difference' | 'annotated'>('before')
  const [sliderPos, setSliderPos] = useState(50)

  const viewMap = { before, after, difference, annotated }
  const labels: Record<string, string> = {
    before: 'Before',
    after: 'After',
    difference: 'Difference Map',
    annotated: 'Detected Changes',
  }

  return (
    <div className="demo-response">
      <div className="assistant-label">
        <strong>Drishti Intelligence</strong>
        <span className="status-dot" /> Change Analysis
      </div>

      <p className="demo-text">
        <b>Change Analysis</b> — Comparing two aligned satellite scenes.
      </p>

      {/* Before / After slider */}
      <div className="demo-section">
        <span className="demo-section-label">BEFORE / AFTER COMPARISON</span>
        <div className="demo-slider-wrap">
          <div className="demo-slider-container">
            <DemoImage src={after} alt="After image" className="demo-slider-img" />
            <div className="demo-slider-clip" style={{ width: `${sliderPos}%` }}>
              <DemoImage src={before} alt="Before image" className="demo-slider-img" />
            </div>
            <input
              type="range"
              min="0"
              max="100"
              value={sliderPos}
              onChange={(e) => setSliderPos(Number(e.target.value))}
              className="demo-slider-range"
              aria-label="Before/After slider"
            />
            <div className="demo-slider-line" style={{ left: `${sliderPos}%` }}>
              <div className="demo-slider-handle" />
            </div>
            <span className="demo-slider-label left">BEFORE</span>
            <span className="demo-slider-label right">AFTER</span>
          </div>
        </div>
      </div>

      {/* View toggle */}
      <div className="demo-view-tabs">
        {(Object.keys(labels) as Array<keyof typeof labels>).map((key) => (
          <button
            key={key}
            className={`demo-view-tab ${activeView === key ? 'active' : ''}`}
            onClick={() => setActiveView(key as typeof activeView)}
          >
            {labels[key]}
          </button>
        ))}
      </div>

      <div className="demo-section">
        <span className="demo-section-label">{labels[activeView]?.toUpperCase()}</span>
        <DemoImage src={viewMap[activeView]} alt={labels[activeView]} className="demo-full-img" />
      </div>

      <div className="demo-analysis-summary">
        <h4>Change detected</h4>
        <ul>
          <li>New structural footprint</li>
          <li>Expansion near existing built-up area</li>
          <li>Existing road network remains largely unchanged</li>
        </ul>
        <div className="demo-confidence-badge high">Confidence: High</div>
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════════════════════
// 3. QUALITY ENGINE
// ═══════════════════════════════════════════════════════════════════════════════

export function QualityResponse() {
  const { inputs, annotated, difference } = DEMO_ASSETS.quality
  return (
    <div className="demo-response">
      <div className="assistant-label">
        <strong>Drishti Intelligence</strong>
        <span className="status-dot" /> Quality Engine
      </div>

      <p className="demo-text">
        <b>Quality Assessment</b> — Evaluating three observations for structural vs. non-structural variation.
      </p>

      <div className="demo-result-grid three-col">
        {inputs.map((src, i) => (
          <div className="demo-result-card" key={i}>
            <DemoImage src={src} alt={`Scene ${i + 1}`} className="demo-card-img" />
            <div className="demo-card-body">
              <strong>Scene {i + 1}</strong>
            </div>
          </div>
        ))}
      </div>

      <div className="demo-section">
        <span className="demo-section-label">QUALITY / CHANGE ASSESSMENT</span>
        <DemoImage src={annotated} alt="Annotated quality output" className="demo-full-img" />
      </div>

      <div className="demo-section">
        <span className="demo-section-label">DIFFERENCE VISUALIZATION</span>
        <DemoImage src={difference} alt="Difference visualization" className="demo-full-img" />
      </div>

      <div className="demo-analysis-summary">
        <h4>No significant structural change confirmed.</h4>
        <p>Observed variation is primarily associated with:</p>
        <ul>
          <li>Atmospheric conditions</li>
          <li>Seasonal / vegetation variation</li>
          <li>Illumination differences</li>
        </ul>
        <div className="demo-confidence-badge low">Structural-change confidence: Low</div>
      </div>

      <div className="demo-quality-panel">
        <div className="demo-qp-item"><span>IMAGE QUALITY</span><b>{QUALITY_PANEL.imageQuality}</b></div>
        <div className="demo-qp-item"><span>CLOUD / HAZE</span><b>{QUALITY_PANEL.cloudHaze}</b></div>
        <div className="demo-qp-item"><span>STRUCTURAL CHANGE</span><b>{QUALITY_PANEL.structuralChange}</b></div>
        <div className="demo-qp-item"><span>ASSESSMENT</span><b>{QUALITY_PANEL.assessment}</b></div>
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════════════════════
// 4. DISCOVERY & CLUSTERING
// ═══════════════════════════════════════════════════════════════════════════════

export function DiscoveryResponse() {
  const { input, tiles, map } = DEMO_ASSETS.discovery
  return (
    <div className="demo-response">
      <div className="assistant-label">
        <strong>Drishti Intelligence</strong>
        <span className="status-dot" /> Discovery &amp; Clustering
      </div>

      <div className="demo-section">
        <span className="demo-section-label">REFERENCE SITE</span>
        <DemoImage src={input} alt="Reference site" className="demo-query-img" />
      </div>

      <p className="demo-text">
        <b>6 Similar Sites Found</b>
      </p>

      <div className="demo-result-grid three-col">
        {tiles.map((src, i) => {
          const site = DISCOVERY_SITES[i]
          return (
            <div className="demo-result-card" key={i}>
              <DemoImage src={src} alt={`Site ${site.id}`} className="demo-card-img" />
              <div className="demo-card-body">
                <strong>Site {String(site.id).padStart(2, '0')}</strong>
                <div className="demo-card-row">
                  <span>Similarity: {site.similarity}%</span>
                  <span className="demo-tag">Pattern: {site.pattern}</span>
                </div>
              </div>
            </div>
          )
        })}
      </div>

      <div className="demo-section">
        <span className="demo-section-label">GEOGRAPHIC DISTRIBUTION</span>
        <DemoImage src={map} alt="Discovery map" className="demo-full-img" />
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════════════════════
// 5. REVIEW QUEUE + PROVENANCE
// ═══════════════════════════════════════════════════════════════════════════════

export function ReviewResponse() {
  const { tiles, before, after } = DEMO_ASSETS.review
  const [statuses, setStatuses] = useState<Record<number, 'pending' | 'confirmed' | 'rejected'>>({
    1: 'pending', 2: 'pending', 3: 'pending', 4: 'pending',
  })
  const [openCandidate, setOpenCandidate] = useState<number | null>(null)

  function updateStatus(id: number, status: 'confirmed' | 'rejected') {
    setStatuses((prev) => ({ ...prev, [id]: status }))
    setOpenCandidate(null)
  }

  const statusIcon = (s: string) =>
    s === 'confirmed' ? <Check className="demo-status-icon confirmed" /> :
    s === 'rejected' ? <XCircle className="demo-status-icon rejected" /> : null

  const statusLabel = (s: string) =>
    s === 'confirmed' ? '✓ Confirmed' : s === 'rejected' ? '✕ Rejected' : 'Pending Review'

  return (
    <div className="demo-response">
      <div className="assistant-label">
        <strong>Drishti Intelligence</strong>
        <span className="status-dot" /> Review Queue
      </div>

      <p className="demo-text">
        <b>Review Queue</b> — 4 candidate areas detected.
      </p>

      <div className="demo-result-grid two-col">
        {REVIEW_CANDIDATES.map((cand, i) => (
          <button
            className={`demo-result-card demo-review-tile ${statuses[cand.id] !== 'pending' ? 'reviewed' : ''}`}
            key={cand.id}
            onClick={() => setOpenCandidate(cand.id)}
            type="button"
          >
            <DemoImage src={tiles[i]} alt={cand.label} className="demo-card-img" />
            <div className="demo-card-body">
              <div className="demo-card-row">
                <strong>{cand.label}</strong>
                {statusIcon(statuses[cand.id])}
              </div>
              <p>{cand.description}</p>
              <span className={`demo-status-label ${statuses[cand.id]}`}>
                {statusLabel(statuses[cand.id])}
              </span>
            </div>
            <ChevronRight className="demo-card-chevron" />
          </button>
        ))}
      </div>

      {/* Review modal */}
      {openCandidate !== null && (
        <div className="detail-overlay" onClick={() => setOpenCandidate(null)}>
          <aside className="detail-drawer" onClick={(e) => e.stopPropagation()}>
            <div className="drawer-head">
              <div>
                <span className="eyebrow dark">OBSERVATION DETAIL</span>
                <h2>Candidate {String(openCandidate).padStart(2, '0')}</h2>
              </div>
              <button className="icon-button" onClick={() => setOpenCandidate(null)}><X /></button>
            </div>

            <div className="demo-section">
              <span className="demo-section-label">BEFORE</span>
              <DemoImage src={before} alt="Before" className="demo-full-img" />
            </div>

            <div className="demo-section">
              <span className="demo-section-label">AFTER</span>
              <DemoImage src={after} alt="After" className="demo-full-img" />
            </div>

            <div className="demo-provenance-panel">
              <h4>Provenance</h4>
              <dl>
                <dt>Source Scene</dt><dd>Satellite Archive</dd>
                <dt>Acquisition</dt><dd>2024-06-15 05:42 UTC</dd>
                <dt>Processing</dt>
                <dd>
                  <ol className="demo-processing-steps">
                    <li>Ingestion</li>
                    <li>Registration</li>
                    <li>Change Detection</li>
                    <li>Candidate Extraction</li>
                  </ol>
                </dd>
                <dt>Status</dt>
                <dd>
                  <span className={`demo-status-label ${statuses[openCandidate]}`}>
                    {statusLabel(statuses[openCandidate])}
                  </span>
                </dd>
              </dl>
            </div>

            <div className="drawer-actions">
              <Button onClick={() => updateStatus(openCandidate, 'confirmed')}>Confirm</Button>
              <Button variant="outline" onClick={() => updateStatus(openCandidate, 'rejected')}>Reject</Button>
              <Button variant="outline" onClick={() => setOpenCandidate(null)}>Close</Button>
            </div>
          </aside>
        </div>
      )}
    </div>
  )
}

// ═══════════════════════════════════════════════════════════════════════════════
// Router – returns the right component per scenario
// ═══════════════════════════════════════════════════════════════════════════════

const RESPONSE_MAP: Record<DemoScenarioKey, React.FC> = {
  semantic: SemanticResponse,
  change: ChangeResponse,
  quality: QualityResponse,
  discovery: DiscoveryResponse,
  review: ReviewResponse,
}

export function DemoResponseRenderer({ scenario }: { scenario: DemoScenarioKey }) {
  const Component = RESPONSE_MAP[scenario]
  return <Component />
}
