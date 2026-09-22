import { useQuery } from '@tanstack/react-query'
import { authApi } from '../api/client'

export default function BuildVersion() {
  const { data } = useQuery({ queryKey: ['buildInfo'], queryFn: async () => (await authApi.getBuildInfo()).data,
    staleTime: 0, refetchOnWindowFocus: true, refetchInterval: 60000 })
  if (!data) return <span>Version unavailable</span>
  return <span title={`Container revision: ${data.revision}`}>TrackHound v{data.version} · {data.revision.slice(0, 12)}</span>
}
