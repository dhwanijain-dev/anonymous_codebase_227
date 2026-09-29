// ---------------------------------------------------------------------------
// DRISHTI – Demo Scenario Configuration
// ---------------------------------------------------------------------------
// All simulated demo data lives here.  Asset paths point to /assets/* which
// maps to frontend/public/assets/.  Adjust extensions here if files are
// renamed.  No backend dependency.
// ---------------------------------------------------------------------------

export type DemoScenarioKey = 'semantic' | 'change' | 'quality' | 'discovery' | 'review'

// ── Asset paths ──────────────────────────────────────────────────────────────

export const DEMO_ASSETS = {
  semantic: {
    input: '/assets/semantic-img1.jpg',
    outputs: [
      '/assets/semantic-response-1.jpeg',
      '/assets/semantic-response-2.jpeg',
      '/assets/semantic-response-3.jpeg',
    ],
  },

  change: {
    before: '/assets/chnage-input-1.jpg',   // original filename has typo
    after: '/assets/change-input-2.jpg',
    difference: '/assets/change-output-1.jpg',
    annotated: '/assets/change-output-2.jpg',
  },

  quality: {
    inputs: [
      '/assets/quality-input-1.jpg',
      '/assets/quality-input-2.jpg',
      '/assets/quality-input-3.jpg',
    ],
    annotated: '/assets/quality-output-1.jpg',
    difference: '/assets/quality-output-2.jpg',
  },

  discovery: {
    input: '/assets/discovery-input-1.jpeg',
    tiles: [
      '/assets/discover-tile-1.jpg',
      '/assets/discover-tile-2.jpg',
      '/assets/discover-tile-3.jpg',
      '/assets/discover-tile-4.jpg',
      '/assets/discovery-tile5.jpg',     // original filename – no hyphen
      '/assets/discovery-tile-6.jpg',
    ],
    map: '/assets/discovery-map.jpg',
  },

  review: {
    input: '/assets/review-input-1.jpg',
    tiles: [
      '/assets/review-tile-1.jpg',
      '/assets/review-tile-2.jpg',
      '/assets/review-tile-3.jpg',
      '/assets/review-tile-4.jpg',
    ],
    before: '/assets/review-response-1.jpg',
    after: '/assets/review-response-2.jpg',
  },
} as const

// ── Hardcoded demo queries ───────────────────────────────────────────────────

export const DEMO_QUERIES: Record<DemoScenarioKey, { full: string; short: string }> = {
  semantic: {
    full: 'Find satellite scenes similar to this image and identify areas showing new structures or construction.',
    short: 'Find similar satellite scenes with new construction.',
  },
  change: {
    full: 'Analyze the changes between these two satellite images and identify newly constructed structures.',
    short: 'Compare these two images and show what changed.',
  },
  quality: {
    full: 'Check these scenes for image-quality differences and determine whether the observed variation represents real structural change.',
    short: 'Is this a real change or just image variation?',
  },
  discovery: {
    full: 'Find similar sites to this location and show where they are geographically clustered.',
    short: 'Find similar sites.',
  },
  review: {
    full: 'Review the detected candidate changes and show the evidence and provenance for each one.',
    short: 'Show me the detected changes for review.',
  },
}

// ── Demo panel display labels ────────────────────────────────────────────────

export const DEMO_PANEL_ITEMS: { key: DemoScenarioKey; label: string }[] = [
  { key: 'semantic', label: 'Semantic Search' },
  { key: 'change', label: 'Change Analysis' },
  { key: 'quality', label: 'Quality Engine' },
  { key: 'discovery', label: 'Discovery & Clustering' },
  { key: 'review', label: 'Review Queue' },
]

// ── Keyword-based query router ───────────────────────────────────────────────

const KEYWORD_MAP: [DemoScenarioKey, string[]][] = [
  ['semantic',  ['semantic', 'similar satellite', 'similar scenes', 'new construction', 'construction']],
  ['change',    ['change', 'compare', 'before and after', 'what changed']],
  ['quality',   ['quality', 'image variation', 'real change', 'cloud', 'haze', 'seasonal']],
  ['discovery', ['discover', 'discovery', 'similar sites', 'cluster', 'geographic']],
  ['review',    ['review', 'candidate', 'provenance', 'detected changes', 'evidence']],
]

export function detectDemoScenario(raw: string): DemoScenarioKey | null {
  const q = raw.toLowerCase().trim()
  if (!q) return null

  // Exact-match first (highest confidence)
  for (const key of Object.keys(DEMO_QUERIES) as DemoScenarioKey[]) {
    const { full, short } = DEMO_QUERIES[key]
    if (q === full.toLowerCase() || q === short.toLowerCase()) return key
  }

  // Keyword fallback
  for (const [key, keywords] of KEYWORD_MAP) {
    if (keywords.some((kw) => q.includes(kw))) return key
  }

  return null
}

// ── Simulated result metadata ────────────────────────────────────────────────

export const SEMANTIC_RESULTS = [
  { similarity: 94, description: 'Possible new construction detected near settlement boundary.', tag: 'New structure detected' },
  { similarity: 89, description: 'New structural footprint detected adjacent to existing road network.', tag: 'Potential construction' },
  { similarity: 86, description: 'Potential expansion of built-up area detected.', tag: 'Potential construction' },
]

export const DISCOVERY_SITES = [
  { id: 1, similarity: 94, pattern: 'High' },
  { id: 2, similarity: 91, pattern: 'High' },
  { id: 3, similarity: 87, pattern: 'Medium' },
  { id: 4, similarity: 84, pattern: 'Medium' },
  { id: 5, similarity: 80, pattern: 'Medium' },
  { id: 6, similarity: 76, pattern: 'Low' },
]

export const REVIEW_CANDIDATES = [
  { id: 1, label: 'Candidate 01', description: 'Potential structural change', status: 'Pending Review' },
  { id: 2, label: 'Candidate 02', description: 'Road extension detected', status: 'Pending Review' },
  { id: 3, label: 'Candidate 03', description: 'Clearing near vegetation boundary', status: 'Pending Review' },
  { id: 4, label: 'Candidate 04', description: 'New surface detected', status: 'Pending Review' },
]

export const QUALITY_PANEL = {
  imageQuality: 'Good',
  cloudHaze: 'Detected',
  structuralChange: 'Low confidence',
  assessment: 'Likely non-structural variation',
}
