import type { ExtractionProfile } from './types'

export const CLINIC_PROFILE_ID = 'clinic_operations'

export const CLINIC_PROFILE: ExtractionProfile = {
  id: CLINIC_PROFILE_ID,
  name: 'Clinic operations (sample)',
  description:
    'Clinic operations, patient onboarding/follow-up, content ecosystem, community events, and systems/automation.',
  initiativeGuidance: {
    preferredStyle:
      'Broad, durable operating areas that group related projects and tasks (e.g. Clinic Operations, Patient Onboarding and Follow-Up).',
    examples: [
      'Clinic Operations',
      'Patient Onboarding and Follow-Up',
      'Content and Program Development',
      'Community Events and Engagement',
      'Systems and Automation Infrastructure',
    ],
    maxCount: 7,
    breadth: 'broad',
  },
  enabledEntityTypes: ['summary', 'insights', 'initiatives', 'projects', 'tasks', 'assets', 'people', 'signals'],
  signalGuidance: {
    examples: [
      'Attention: operational workflows that are too manual',
      'Risk: scope/revenue misalignment or unsustainable workload',
      'Opportunity: better use of EMR/practice management data',
      'Opportunity: community events or content that deepen the relationship',
    ],
    instructions:
      'Focus on risks/opportunities/blockers that affect patient experience, clinic throughput, financial clarity, or strategic expansion.',
  },
  assetGuidance: {
    examples: [
      'Practice management / EMR system',
      'Onboarding email templates',
      'Patient education media library',
      'Supplier or formulary ordering portal',
      'Operations dashboard',
    ],
    instructions:
      'Prefer named systems, documents, workflows, and tools that are repeatedly referenced. Avoid generic labels like "AI tool" when a more specific name exists.',
  },
  peopleGuidance: {
    examples: [
      'Lead practitioner',
      'Front-office coordinator',
      'Creative or community partner',
      'External billing vendor',
    ],
    instructions:
      'Extract real people and organizations with clear roles in the clinic or ecosystem. Do NOT emit generic speaker labels (Speaker A/B/C).',
  },
  groupingConfig: {
    mergeDuplicatesAggressively: true,
    preferCanonicalBuckets: true,
  },
}

export const SERVICE_BUSINESS_PROFILE_ID = 'service_business'

export const SERVICE_BUSINESS_PROFILE: ExtractionProfile = {
  id: SERVICE_BUSINESS_PROFILE_ID,
  name: 'General Service Business',
  description:
    'Client-facing service business (e.g. agency, consulting, coaching) with pipelines, delivery, and relationship management.',
  initiativeGuidance: {
    preferredStyle:
      'Broad areas like lead generation, sales pipeline, service delivery, client success, internal operations.',
    examples: [
      'Lead Generation and Marketing',
      'Sales Pipeline and Onboarding',
      'Service Delivery and Quality',
      'Client Success and Retention',
      'Internal Operations and Finance',
    ],
    maxCount: 6,
    breadth: 'broad',
  },
  enabledEntityTypes: ['summary', 'insights', 'initiatives', 'projects', 'tasks', 'assets', 'people', 'signals'],
  signalGuidance: {
    examples: [
      'Attention: inconsistent handoff from sales to delivery',
      'Risk: key client at churn risk',
      'Opportunity: standardize onboarding workflow',
    ],
    instructions:
      'Highlight risks/opportunities/blockers that impact revenue, client satisfaction, and delivery reliability.',
  },
  assetGuidance: {
    examples: ['CRM system', 'Proposal templates', 'Onboarding checklist', 'Client playbooks', 'Internal SOPs'],
    instructions:
      'Treat recurring systems, templates, and SOPs as assets. Focus on those that can be improved or better leveraged.',
  },
  peopleGuidance: {
    examples: ['Account managers', 'Project leads', 'Key client stakeholders'],
    instructions:
      'Extract staff and client roles that matter for decision-making or execution. Ignore anonymous speakers without clear roles.',
  },
  groupingConfig: {
    mergeDuplicatesAggressively: true,
    preferCanonicalBuckets: true,
  },
}

export const NONPROFIT_PROFILE_ID = 'nonprofit_programs'

export const NONPROFIT_PROFILE: ExtractionProfile = {
  id: NONPROFIT_PROFILE_ID,
  name: 'Nonprofit Programs',
  description:
    'Nonprofit or community organization with programs, fundraising, volunteers, and impact initiatives.',
  initiativeGuidance: {
    preferredStyle:
      'Program/initiative areas like Programs and Services, Community Engagement, Fundraising, Operations.',
    examples: [
      'Programs and Services',
      'Community Outreach and Engagement',
      'Fundraising and Partnerships',
      'Volunteer Management',
      'Operations and Compliance',
    ],
    maxCount: 7,
    breadth: 'medium',
  },
  enabledEntityTypes: ['summary', 'insights', 'initiatives', 'projects', 'tasks', 'assets', 'people', 'signals'],
  signalGuidance: {
    examples: [
      'Risk: funding uncertainty for a key program',
      'Opportunity: new partnership or grant',
      'Attention: volunteer burnout or gaps',
    ],
    instructions:
      'Emphasize signals related to impact, sustainability, funding, and community relationships.',
  },
  assetGuidance: {
    examples: ['Donor CRM', 'Grant tracker spreadsheet', 'Program curriculum documents', 'Volunteer handbook'],
    instructions:
      'Treat repeat-mentioned systems, documents, and shared resources as assets, especially those tied to programs or fundraising.',
  },
  peopleGuidance: {
    examples: ['Program directors', 'Board members', 'Key partners', 'Major donors'],
    instructions:
      'Extract people and organizations that shape programs, funding, or community reach. Ignore generic labels without clear roles.',
  },
  groupingConfig: {
    mergeDuplicatesAggressively: true,
    preferCanonicalBuckets: true,
  },
}

export const DEFAULT_EXTRACTION_PROFILE = CLINIC_PROFILE

