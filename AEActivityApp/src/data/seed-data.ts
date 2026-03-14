import type { AEProfile, Activity, CalendarEvent } from '../types'

export const seedAEs: AEProfile[] = [
  {
    id: 'ae-001',
    name: 'Patrick Hogan',
    email: 'patrick.hogan@elastic.co',
    region: 'East',
    territory: 'DoD/IC',
    team: 'Federal',
  },
  {
    id: 'ae-002',
    name: 'Sarah Chen',
    email: 'sarah.chen@elastic.co',
    region: 'West',
    territory: 'Civilian',
    team: 'Federal',
  },
  {
    id: 'ae-003',
    name: 'Marcus Williams',
    email: 'marcus.williams@elastic.co',
    region: 'East',
    territory: 'SLED',
    team: 'SLED',
  },
  {
    id: 'ae-004',
    name: 'Jennifer Park',
    email: 'jennifer.park@elastic.co',
    region: 'West',
    territory: 'Healthcare',
    team: 'SLED',
  },
  {
    id: 'ae-005',
    name: 'David Barclay',
    email: 'david.barclay@elastic.co',
    region: 'Central',
    territory: 'DoD/IC',
    team: 'Federal',
  },
  {
    id: 'ae-006',
    name: 'Amanda Torres',
    email: 'amanda.torres@elastic.co',
    region: 'East',
    territory: 'Civilian',
    team: 'Federal',
  },
  {
    id: 'ae-007',
    name: 'Ryan Kimura',
    email: 'ryan.kimura@elastic.co',
    region: 'West',
    territory: 'SLED',
    team: 'SLED',
  },
  {
    id: 'ae-008',
    name: 'Lisa Nguyen',
    email: 'lisa.nguyen@elastic.co',
    region: 'Central',
    territory: 'Healthcare',
    team: 'SLED',
  },
]

export const seedActivities: Activity[] = [
  { id: 'act-001', aeId: 'ae-001', type: 'bvr_created', date: '2026-03-01', description: 'Created DISA BVR for Zero Trust migration', dealId: 'deal-001', dealName: 'DISA Zero Trust', acv: 2400000 },
  { id: 'act-002', aeId: 'ae-001', type: 'bvr_delivered', date: '2026-03-03', description: 'Delivered DISA BVR to customer', dealId: 'deal-001', dealName: 'DISA Zero Trust', acv: 2400000 },
  { id: 'act-003', aeId: 'ae-001', type: 'customer_meeting', date: '2026-03-05', description: 'DISA executive briefing on observability ROI' },
  { id: 'act-004', aeId: 'ae-001', type: 'value_deck_created', date: '2026-03-07', description: 'Created value deck for Army Cyber Command', dealId: 'deal-002', dealName: 'Army Cyber', acv: 1800000 },
  { id: 'act-005', aeId: 'ae-001', type: 'executive_briefing', date: '2026-03-10', description: 'CIO briefing on Elastic security portfolio' },

  { id: 'act-010', aeId: 'ae-002', type: 'bvr_created', date: '2026-03-02', description: 'Created VA modernization BVR', dealId: 'deal-003', dealName: 'VA Modernization', acv: 1500000 },
  { id: 'act-011', aeId: 'ae-002', type: 'customer_meeting', date: '2026-03-04', description: 'VA stakeholder alignment meeting' },
  { id: 'act-012', aeId: 'ae-002', type: 'workshop_delivered', date: '2026-03-06', description: 'Elastic SIEM workshop for VA SOC team' },
  { id: 'act-013', aeId: 'ae-002', type: 'rfp_response', date: '2026-03-08', description: 'Responded to NASA RFI on log analytics', dealId: 'deal-004', dealName: 'NASA Log Analytics', acv: 900000 },

  { id: 'act-020', aeId: 'ae-003', type: 'bvr_created', date: '2026-03-01', description: 'Nebraska SLED observability BVR', dealId: 'deal-005', dealName: 'Nebraska OCIO', acv: 750000 },
  { id: 'act-021', aeId: 'ae-003', type: 'bvr_delivered', date: '2026-03-04', description: 'Delivered Nebraska BVR to procurement', dealId: 'deal-005', dealName: 'Nebraska OCIO', acv: 750000 },
  { id: 'act-022', aeId: 'ae-003', type: 'customer_meeting', date: '2026-03-06', description: 'Nebraska OCIO follow-up call' },
  { id: 'act-023', aeId: 'ae-003', type: 'one_pager_created', date: '2026-03-09', description: 'Created one-pager for Minnesota IT consolidation', dealId: 'deal-006', dealName: 'Minnesota IT', acv: 500000 },
  { id: 'act-024', aeId: 'ae-003', type: 'technical_validation', date: '2026-03-11', description: 'Technical validation for Georgia Cyber Center', dealId: 'deal-007', dealName: 'Georgia Cyber', acv: 650000 },

  { id: 'act-030', aeId: 'ae-004', type: 'customer_meeting', date: '2026-03-02', description: 'HHS data platform discovery call' },
  { id: 'act-031', aeId: 'ae-004', type: 'bvr_created', date: '2026-03-05', description: 'Created HHS observability BVR', dealId: 'deal-008', dealName: 'HHS Data Platform', acv: 2100000 },
  { id: 'act-032', aeId: 'ae-004', type: 'executive_briefing', date: '2026-03-08', description: 'HHS CTO briefing on search AI capabilities' },
  { id: 'act-033', aeId: 'ae-004', type: 'workshop_delivered', date: '2026-03-10', description: 'Elastic observability workshop for HHS ops team' },

  { id: 'act-040', aeId: 'ae-005', type: 'bvr_created', date: '2026-03-03', description: 'Created Air Force SIEM migration BVR', dealId: 'deal-009', dealName: 'USAF SIEM', acv: 3200000 },
  { id: 'act-041', aeId: 'ae-005', type: 'bvr_delivered', date: '2026-03-05', description: 'Delivered USAF SIEM BVR', dealId: 'deal-009', dealName: 'USAF SIEM', acv: 3200000 },
  { id: 'act-042', aeId: 'ae-005', type: 'customer_meeting', date: '2026-03-07', description: 'USAF program office review' },
  { id: 'act-043', aeId: 'ae-005', type: 'value_deck_created', date: '2026-03-09', description: 'Created NSA endpoint security value deck', dealId: 'deal-010', dealName: 'NSA Endpoint', acv: 1700000 },
  { id: 'act-044', aeId: 'ae-005', type: 'rfp_response', date: '2026-03-11', description: 'Responded to DIA analytics RFP', dealId: 'deal-011', dealName: 'DIA Analytics', acv: 1100000 },
  { id: 'act-045', aeId: 'ae-005', type: 'customer_meeting', date: '2026-03-12', description: 'DIA technical deep-dive session' },

  { id: 'act-050', aeId: 'ae-006', type: 'bvr_created', date: '2026-03-01', description: 'Created IRS fraud detection BVR', dealId: 'deal-012', dealName: 'IRS Fraud Detection', acv: 1900000 },
  { id: 'act-051', aeId: 'ae-006', type: 'customer_meeting', date: '2026-03-04', description: 'IRS program manager sync' },
  { id: 'act-052', aeId: 'ae-006', type: 'one_pager_created', date: '2026-03-07', description: 'Created SSA observability one-pager', dealId: 'deal-013', dealName: 'SSA Observability', acv: 800000 },

  { id: 'act-060', aeId: 'ae-007', type: 'customer_meeting', date: '2026-03-02', description: 'California DMV discovery call' },
  { id: 'act-061', aeId: 'ae-007', type: 'bvr_created', date: '2026-03-06', description: 'Created Oregon education analytics BVR', dealId: 'deal-014', dealName: 'Oregon Education', acv: 450000 },
  { id: 'act-062', aeId: 'ae-007', type: 'technical_validation', date: '2026-03-09', description: 'Technical validation for Washington DOT', dealId: 'deal-015', dealName: 'WA DOT', acv: 600000 },

  { id: 'act-070', aeId: 'ae-008', type: 'customer_meeting', date: '2026-03-03', description: 'Mayo Clinic SOC assessment call' },
  { id: 'act-071', aeId: 'ae-008', type: 'bvr_created', date: '2026-03-06', description: 'Created Cleveland Clinic observability BVR', dealId: 'deal-016', dealName: 'Cleveland Clinic', acv: 1200000 },
  { id: 'act-072', aeId: 'ae-008', type: 'bvr_delivered', date: '2026-03-09', description: 'Delivered Cleveland Clinic BVR', dealId: 'deal-016', dealName: 'Cleveland Clinic', acv: 1200000 },
  { id: 'act-073', aeId: 'ae-008', type: 'workshop_delivered', date: '2026-03-11', description: 'Elastic security workshop for Kaiser Permanente' },
]

export const seedCalendarEvents: CalendarEvent[] = [
  { id: 'evt-001', aeId: 'ae-001', title: 'DISA Zero Trust Phase 2 Review', date: '2026-03-17', type: 'customer_call', attendees: ['Patrick Hogan', 'John Bradley'] },
  { id: 'evt-002', aeId: 'ae-001', title: 'Army Cyber Value Deck Walkthrough', date: '2026-03-19', type: 'deal_review', dealId: 'deal-002', attendees: ['Patrick Hogan'] },
  { id: 'evt-003', aeId: 'ae-002', title: 'VA SOC Team Follow-up', date: '2026-03-18', type: 'follow_up', attendees: ['Sarah Chen', 'John Bradley'] },
  { id: 'evt-004', aeId: 'ae-003', title: 'Nebraska Procurement Final Review', date: '2026-03-20', type: 'deal_review', dealId: 'deal-005', attendees: ['Marcus Williams'] },
  { id: 'evt-005', aeId: 'ae-004', title: 'HHS Elastic Workshop', date: '2026-03-21', type: 'workshop', attendees: ['Jennifer Park', 'John Bradley'] },
  { id: 'evt-006', aeId: 'ae-005', title: 'USAF SIEM Migration Planning', date: '2026-03-17', type: 'customer_call', dealId: 'deal-009', attendees: ['David Barclay', 'John Bradley'] },
  { id: 'evt-007', aeId: 'ae-005', title: 'DIA Analytics Deep-Dive Part 2', date: '2026-03-24', type: 'executive_briefing', dealId: 'deal-011', attendees: ['David Barclay'] },
  { id: 'evt-008', aeId: 'ae-006', title: 'IRS Quarterly Business Review', date: '2026-03-19', type: 'internal_review', attendees: ['Amanda Torres', 'Ben Kim'] },
  { id: 'evt-009', aeId: 'ae-007', title: 'Oregon Education Pilot Kickoff', date: '2026-03-25', type: 'workshop', dealId: 'deal-014', attendees: ['Ryan Kimura'] },
  { id: 'evt-010', aeId: 'ae-008', title: 'Cleveland Clinic Go-Live Support', date: '2026-03-22', type: 'customer_call', dealId: 'deal-016', attendees: ['Lisa Nguyen', 'John Bradley'] },
]
