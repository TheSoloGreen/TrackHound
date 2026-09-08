import type { QueryClient } from '@tanstack/react-query'

// Prefixes also cover filtered lists, paginated results, and all open details.
export function refreshLibrary(queryClient: QueryClient) {
  return Promise.all([
    'stats', 'shows', 'show', 'files', 'file', 'season', 'scanLocations', 'trackRemovalPlan',
  ].map((key) => queryClient.invalidateQueries({ queryKey: [key] })))
}
