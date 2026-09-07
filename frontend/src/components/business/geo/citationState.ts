// GEO 测评记录「引用证据状态」展示工具
//
// 后端 citation_status 四态映射到报表可读文案,供证据明细表 / 回答详情抽屉复用。
// 映射与 backend/services/geo_citation.py、方案 §六.1 一致:
//   captured        → 真实引用列表(可回溯)
//   empty           → 抓取成功但零条
//   unavailable     → 抓取异常
//   not_supported   → 平台/通道无引用能力(报表按 null 呈现)
//   (无状态,历史)     → 按 raw_citations/cited_urls 有无回退

export interface CitationLink {
  url: string
  domain?: string
}

export type CitationStateKind =
  | 'captured'
  | 'empty'
  | 'unavailable'
  | 'not_supported'
  | 'legacy'
  | 'none'

export interface CitationStateView {
  kind: CitationStateKind
  label: string
  links: CitationLink[]
  captureMethod?: string | null
  tooltip: string
}

function collectLinks(row: any): CitationLink[] {
  const raw = Array.isArray(row?.raw_citations) ? row.raw_citations : []
  const fromRaw: CitationLink[] = raw
    .map((c: any) => {
      if (!c || typeof c !== 'object') return null
      const url = c.url || c.href || ''
      if (!url) return null
      return { url, domain: c.domain || undefined }
    })
    .filter(Boolean) as CitationLink[]
  if (fromRaw.length) return fromRaw
  const urls = Array.isArray(row?.cited_urls) ? row.cited_urls.map((u: any) => ({ url: String(u) })) : []
  return urls
}

export function describeCitationState(row: any): CitationStateView {
  const status = row?.citation_status
  const captureMethod = row?.capture_method || null
  const links = collectLinks(row)
  const methodText = captureMethod ? ` · 采集方式:${captureMethod}` : ''
  const base = { links, captureMethod }

  switch (status) {
    case 'captured': {
      const label = links.length ? `已引用 ${links.length} 条` : '已引用'
      const detail = links.length ? `${links.length} 条外部来源,详情中可逐个查看` : '标注了引用,但无链接明细'
      return { ...base, kind: 'captured', label, tooltip: `${label} · ${detail}${methodText}` }
    }
    case 'empty':
      return { ...base, kind: 'empty', label: '未引用来源', tooltip: `抓取成功但本次未引用来源${methodText}` }
    case 'unavailable':
      return { ...base, kind: 'unavailable', label: '引用采集失败', tooltip: `本次引用抓取异常,无法确认是否引用${methodText}` }
    case 'not_supported':
      return { ...base, kind: 'not_supported', label: '无引用能力', tooltip: `该平台/通道不具备引用展示能力${methodText}` }
    default: {
      if (links.length) {
        return { ...base, kind: 'legacy', label: `引用 ${links.length} 条`, tooltip: `历史记录(未标注引用状态),含 ${links.length} 条来源` }
      }
      return { ...base, kind: 'none', label: '—', tooltip: '' }
    }
  }
}

export function citationTagType(kind: CitationStateKind): 'success' | 'info' | 'warning' | 'primary' | 'danger' | undefined {
  switch (kind) {
    case 'captured':
      return 'success'
    case 'legacy':
      return 'primary'
    case 'unavailable':
      return 'warning'
    case 'empty':
    case 'not_supported':
      return 'info'
    case 'none':
      return undefined
  }
}
