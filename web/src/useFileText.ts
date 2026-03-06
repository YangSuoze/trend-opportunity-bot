import { useCallback, useMemo, useState } from 'react'

export interface LoadedFile {
  name: string
  size: number
  lastModified: number
  text: string
}

export function useFileText() {
  const [file, setFile] = useState<File | null>(null)
  const [loaded, setLoaded] = useState<LoadedFile | null>(null)
  const [error, setError] = useState<string>('')
  const [isLoading, setIsLoading] = useState(false)

  const load = useCallback(async (nextFile: File) => {
    setFile(nextFile)
    setError('')
    setIsLoading(true)
    try {
      const text = await nextFile.text()
      setLoaded({
        name: nextFile.name,
        size: nextFile.size,
        lastModified: nextFile.lastModified,
        text,
      })
    } catch (e) {
      setLoaded(null)
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setIsLoading(false)
    }
  }, [])

  const reload = useCallback(async () => {
    if (!file) return
    await load(file)
  }, [file, load])

  return useMemo(
    () => ({ file, loaded, error, isLoading, load, reload }),
    [error, file, isLoading, load, loaded, reload],
  )
}
