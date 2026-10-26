// How each size of home is worded.
//
// Two forms are needed and neither can be made from the other. The dropdown
// wants a thing you pick ("a room", "2 bedrooms"). The sentences want a
// collective the share is a share of ("72% of its rooms", "Share of 2
// bedroom homes at or under £900"). Running the dropdown wording through
// the sentences is what produced "72% of its a room homes are in budget".
//
// This lives in the site rather than in the published data because it is
// wording, and wording should never need a routing rebuild to change. The
// published meta carries a label per category so the dataset reads on its
// own, and nothing here depends on it.

interface Forms {
  /** As a choice: what the dropdown offers. */
  choice: string
  /** As a collection: what a percentage is a percentage of. */
  collective: string
}

const NAMED: Record<string, Forms> = {
  room: { choice: 'a room', collective: 'rooms' },
  studio: { choice: 'a studio', collective: 'studios' },
  all: { choice: 'any size', collective: 'homes of any size' },
}

const BEDROOMS = /^(\d+\+?)$/

/**
 * Total over anything the pipeline can emit, rather than a lookup that can
 * miss.
 *
 * ONS has renamed its categories before. A category with no entry here
 * should read awkwardly and still say which size it means, never come out
 * blank in the middle of a sentence.
 */
function formsFor(category: string): Forms {
  if (category.trim() === '') return NAMED.all as Forms

  const named = NAMED[category]
  if (named) return named

  const match = BEDROOMS.exec(category)
  const count = match?.[1]
  if (count !== undefined) {
    return {
      choice: count === '1' ? '1 bedroom' : `${count} bedrooms`,
      collective: `${count} bedroom homes`,
    }
  }

  return { choice: category, collective: `${category} homes` }
}

export function choiceLabel(category: string): string {
  return formsFor(category).choice
}

export function collectiveLabel(category: string): string {
  return formsFor(category).collective
}
