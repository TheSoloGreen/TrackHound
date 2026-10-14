import { useEffect, useState, type ReactNode } from 'react'
import { mediaApi } from '../api/client'

// A normal <img> cannot attach the session's bearer token. Load through Axios
// and release the temporary browser URL when the title changes or unmounts.
export default function ShowArtwork({ id, alt, fallback }: { id: number; alt: string; fallback: ReactNode }) {
  const [src, setSrc] = useState<string | null>(null)
  useEffect(() => {
    const controller = new AbortController()
    let objectUrl: string | undefined
    setSrc(null)
    void mediaApi.getArtwork(id, controller.signal).then(({ data }) => {
      if (controller.signal.aborted) return
      objectUrl = URL.createObjectURL(data)
      setSrc(objectUrl)
    }).catch(() => { /* Keep the title's fallback when artwork is unavailable. */ })
    return () => {
      controller.abort()
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [id])
  return src ? <img src={src} alt={alt} className="w-16 h-24 object-cover rounded-lg"
    onError={() => setSrc(null)} /> : <>{fallback}</>
}
