// Headline and notices for a verified response; wording depends only on status and warnings.
export function resultHeading(response) {
  if (response.results.length) return response.status === 'found' ? '기억과 일치하는 장면' : '확정하기 어려운 검색 후보'
  if (response.status !== 'unsupported') return '관련 자막을 찾지 못했어요'
  if (response.warnings.includes('evidence_rejected')) return '원문 근거를 확인하지 못했어요'
  if (response.warnings.includes('subtitle_only_scope')) return '자막으로 확인할 수 없는 요청이에요'
  return '확인할 근거가 부족해요'
}

export function resultNotices(response) {
  const notes = []
  if (!response.results.length) notes.push('다른 표현이나 기억나는 단어로 다시 검색해 보세요. 영상에 장면이 없다는 뜻은 아닙니다.')
  else if (response.status === 'partial') notes.push('원문과 시각은 확인했지만 의미 검증을 완료하지 못했습니다.')
  else if (response.status === 'ambiguous') notes.push('관련 가능성이 있지만 질문과 장면의 일치를 확정하기 어렵습니다.')
  if (response.warnings.includes('speaker_unknown')) notes.push('자막에는 화자 정보가 없어 발화자는 확인할 수 없습니다.')
  if (response.warnings.includes('evidence_rejected')) notes.push('원문 근거를 확인하지 못한 후보는 제외했습니다.')
  return notes
}

export const EVIDENCE_TAGS = { mixed: '대사·편집 설명 혼합', editorial: '편집 설명', dialogue: '원문 자막', unknown: '원문 자막' }
