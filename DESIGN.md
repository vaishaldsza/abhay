---
name: Abhay DDMA Command
theme:
  color_mode: LIGHT
  font: INTER
  roundness: ROUND_EIGHT
  custom_color: '#0b2545'
---

# Abhay DDMA Command Design System

Operational design system engineered for Indian District Disaster Management Authority (DDMA) command centers, Emergency Operations Centers (EOC), citizen distress intake, and field rescue coordination.

---

## 1. Visual Foundation & Philosophy

- **Atmosphere:** Calm, authoritative, high-legibility, and urgent without inducing panic.
- **Tone & Persona:** Mission-critical gov-tech and tactical disaster management.
- **Core Directive:** Deterministic operational clarity. Elimination of ambiguous slogans (e.g., zero instances of *"help is coming"* or premature *"dispatched"* labels before verified acceptance).

---

## 2. Color Palette & Tokens

### Brand & Interface Colors
| Token | Hex | Role & Usage |
| :--- | :--- | :--- |
| `primary` | `#0B2545` | Deep Navy: Command headers, authoritative badges, primary buttons |
| `on-primary` | `#FFFFFF` | Text/icons on primary surfaces |
| `primary-container` | `#133863` | Dark navy surface container & active nav items |
| `secondary` | `#F59E0B` | Saffron / Amber: Critical operational alerts, warning highlights, high-visibility actions |
| `on-secondary` | `#FFFFFF` | Contrast text on saffron elements |
| `surface` | `#FAF8FF` / `#F8FAFC` | Main application background (low eye-fatigue light theme) |
| `surface-dim` | `#D2D9F4` | Muted background borders and divider tones |
| `surface-container-lowest` | `#FFFFFF` | Pure white card surfaces, modals, data tables |
| `surface-container-low` | `#F2F3FF` | Secondary card fills, subtle row striping |
| `surface-container-high` | `#E2E8F0` | Border outlines, input borders, structural division |
| `outline` | `#94A3B8` | Input outlines, subtle borders |
| `outline-variant` | `#CBD5E1` | Card dividers, tabular borders |

### Strict Status Taxonomy
Status colors must be applied with 100% consistency across maps, queues, chips, and logs:

| Status Token | Hex | Meaning & Condition |
| :--- | :--- | :--- |
| `status-danger` | `#DC2626` | **Needs Help / Critical Distress:** Resident flagged requiring immediate assistance, medical, or evacuation. |
| `status-warning` | `#EA580C` | **Can Help a Neighbor / Attention:** Verified local volunteer or neighbor caregiver available. |
| `status-success` | `#16A34A` | **Evacuated / Safe / Reached:** Evacuation completed or resident accounted for. |
| `status-neutral` | `#9CA3AF` | **Not Reached Yet / Pending:** Unanswered calls, pending ground verification. |
| `status-info` | `#2563EB` | **Driver Accepted:** Assigned vehicle (e.g., *NDRF Boat-01*) has confirmed mission. |

---

## 3. Typography (Inter)

- **Font Family:** `Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif`
- **Monospace / Tabular:** Tabular figures (`font-variant-numeric: tabular-nums; font-mono`) used for timestamps, GPS coordinates, vehicle callsigns, headcount, and retry counters.

### Type Scale
- **Display / Command Title:** `text-2xl font-bold tracking-tight text-[#0B2545]`
- **Section Headline:** `text-xl font-bold text-[#0B2545]`
- **Subheadline / Card Header:** `text-base font-semibold text-slate-900`
- **Body Regular:** `text-sm font-normal text-slate-700 leading-relaxed`
- **Tabular Data / Code:** `font-mono text-xs font-medium text-slate-800`
- **Caption & Meta:** `text-xs font-medium text-slate-500`
- **Button & Navigation Label:** `text-sm font-semibold tracking-wide uppercase`

---

## 4. Multi-Language Support & Localization

Built to support script-balanced layout stability across:
- **English** (`EN`)
- **हिन्दी** (Hindi)
- **ಕನ್ನಡ** (Kannada)

### Localization Rules:
1. Always preserve dual-script labeling on field-worker and resident interfaces (e.g., `ಔಷಧಿ ಅಥವಾ ಆಮ್ಲಜನಕ ಬೇಕು / Needs medicine or oxygen`).
2. Language toggles must never cause layout shift or overflow truncation on fixed 390px mobile screens.

---

## 5. Privacy & DPDP Act 2023 Principles

Strict statutory privacy defaults enforced throughout all views:
- **Name Minimisation:** Only resident first names are displayed.
- **Phone Number Masking:** All citizen and helper telephone numbers are strictly masked: `+91 XXXXX XXXXX`.
- **Statutory Notice:** `"Designed around DPDP Act 2023 principles: purpose limitation, data minimisation, consent, and automatic deletion."`
- **Retention & Purge:** Telemetry data deleted 72 hours after incident closure.

---

## 6. Deterministic Voice & Telephony Rules

- **Zero-Hallucination Mandate:**
  > *"Status changes only through code, never the AI. The agent never says help is coming until a driver has accepted."*
- **Audit Attributions:** Status updates logged in audit ledgers must state: `"Changed by system rules, not AI"`.
- **Resident Notice (Verbatim):**
  > *"Resident will be informed only after the driver accepts."*
- **Architecture Specification:** MVP operates on recorded audio input and a Python backend (no unverified LLM state mutations).

---

## 7. Component Patterns

### Status Chips
- Pill or rounded-md (`rounded-md`, 4px–8px radius).
- Light tinted background (10%–15% opacity) with solid status text and a solid 6px dot indicator.

### Action Buttons
- **Primary:** Deep navy background (`bg-[#0B2545] text-white hover:bg-[#133863]`), rounded-lg (8px).
- **Secondary:** White background with slate border (`border border-slate-300 text-slate-700 hover:bg-slate-50`).
- **Urgent / Triage Action:** High-visibility amber/saffron (`bg-[#F59E0B] text-slate-950 font-bold hover:bg-[#D97706]`).
- **Destructive:** Crimson alert (`bg-[#DC2626] text-white hover:bg-[#B91C1C]`).

### Cards & Surfaces
- `bg-white border border-slate-200 rounded-lg shadow-sm p-4` (8px standard corner radius).
- High visual separation with distinct header bars and icon badges.
