import type { FC, SVGProps } from 'react'
import type { MapNodePayload } from '../ontology'
import type { MapGlyphTier } from './glyphTier'
import { mapGlyphTierFromFruit } from './glyphTier'

import IdeaBare from './assets/idea-bare.svg?react'
import IdeaFlowering from './assets/idea-flowering.svg?react'
import IdeaFruiting from './assets/idea-fruiting.svg?react'
import IdeaLeafy from './assets/idea-leafy.svg?react'

import InitiativeBare from './assets/initiative-bare.svg?react'
import InitiativeFlowering from './assets/initiative-flowering.svg?react'
import InitiativeFruiting from './assets/initiative-fruiting.svg?react'
import InitiativeLeafy from './assets/initiative-leafy.svg?react'

import ProjectBare from './assets/project-bare.svg?react'
import ProjectFlowering from './assets/project-flowering.svg?react'
import ProjectFruiting from './assets/project-fruiting.svg?react'
import ProjectLeafy from './assets/project-leafy.svg?react'

import TaskBare from './assets/task-bare.svg?react'
import TaskFlowering from './assets/task-flowering.svg?react'
import TaskFruiting from './assets/task-fruiting.svg?react'
import TaskLeafy from './assets/task-leafy.svg?react'

type SvgCmp = FC<SVGProps<SVGSVGElement>>

const IDEA: Record<MapGlyphTier, SvgCmp> = {
  leafy: IdeaLeafy,
  bare: IdeaBare,
  flowering: IdeaFlowering,
  fruiting: IdeaFruiting,
}

const INITIATIVE: Record<MapGlyphTier, SvgCmp> = {
  leafy: InitiativeLeafy,
  bare: InitiativeBare,
  flowering: InitiativeFlowering,
  fruiting: InitiativeFruiting,
}

const PROJECT: Record<MapGlyphTier, SvgCmp> = {
  leafy: ProjectLeafy,
  bare: ProjectBare,
  flowering: ProjectFlowering,
  fruiting: ProjectFruiting,
}

const TASK: Record<MapGlyphTier, SvgCmp> = {
  leafy: TaskLeafy,
  bare: TaskBare,
  flowering: TaskFlowering,
  fruiting: TaskFruiting,
}

export type MapGlyphEntity = 'idea' | 'initiative' | 'project' | 'task'

const BY_ENTITY: Record<MapGlyphEntity, Record<MapGlyphTier, SvgCmp>> = {
  idea: IDEA,
  initiative: INITIATIVE,
  project: PROJECT,
  task: TASK,
}

export function mapNodeKindToGlyphEntity(kind: MapNodePayload['kind']): MapGlyphEntity | null {
  switch (kind) {
    case 'seed':
      return 'idea'
    case 'tree':
      return 'initiative'
    case 'branch':
      return 'project'
    case 'flower':
      return 'task'
    default:
      return null
  }
}

type MapEntityGlyphProps = {
  entity: MapGlyphEntity
  tier: MapGlyphTier
} & SVGProps<SVGSVGElement>

/** Renders the approved SVG asset for one entity + tier (centered by parent). */
export function MapEntityGlyph({ entity, tier, className, ...rest }: MapEntityGlyphProps) {
  const Cmp = BY_ENTITY[entity][tier]
  return <Cmp className={className} role="presentation" focusable="false" {...rest} />
}

type MapEntityGlyphFromFruitProps = {
  entity: MapGlyphEntity
  fruit01: number
} & SVGProps<SVGSVGElement>

export function MapEntityGlyphFromFruit({ entity, fruit01, ...rest }: MapEntityGlyphFromFruitProps) {
  const tier = mapGlyphTierFromFruit(fruit01)
  return <MapEntityGlyph entity={entity} tier={tier} {...rest} />
}
