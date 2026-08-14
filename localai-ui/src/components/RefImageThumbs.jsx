import { useEffect, useState } from 'react'

// 첨부한 참조 이미지 미리보기. 예전에는 "{count}장 첨부됨" 텍스트만 있어서 제품 사진이
// 제대로 붙었는지, 엉뚱한 파일을 골랐는지 확인할 방법이 없었다(2026-08-13).
// createObjectURL은 명시적으로 revoke하지 않으면 파일 선택을 바꿀 때마다 blob이 쌓인다.
export default function RefImageThumbs({ files = [] }) {
  const [urls, setUrls] = useState([])

  useEffect(() => {
    const next = files.map((f) => URL.createObjectURL(f))
    setUrls(next)
    return () => next.forEach((u) => URL.revokeObjectURL(u))
  }, [files])

  if (urls.length === 0) return null

  return (
    <div className="agent-attempt-strip">
      {urls.map((url, i) => (
        <figure key={url} className="agent-attempt">
          <img src={url} alt={files[i]?.name || ''} />
          <figcaption>{files[i]?.name}</figcaption>
        </figure>
      ))}
    </div>
  )
}
