const labels = {
  application_deadline: '신청',
  submission_deadline: '제출',
  event: '행사',
  announcement: '발표',
  other: '기타 일정',
}

export function seoulDate(value) {
  if (!value) return null
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return null
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit', day: '2-digit',
  }).formatToParts(date)
  const fields = Object.fromEntries(parts.map(part => [part.type, part.value]))
  return `${fields.year}-${fields.month}-${fields.day}`
}

function displayName(event) {
  const participationPeriod = event.event_type === 'event'
    && event.action_required?.includes('참여하기')
    && /(?:이벤트|참여)\s*기간/.test(event.date_text || event.evidence_text || '')
  return participationPeriod ? '참여' : labels[event.event_type] || '기타 일정'
}

export function calendarEventsOnDate(items, key) {
  const occurrences = []
  for (const event of items) {
    const start = seoulDate(event.start_at)
    const end = seoulDate(event.end_at || event.effective_at) || start
    if (!start || !end) continue
    if (start !== end && start === key) occurrences.push({ event, phase: 'start' })
    if (end === key) occurrences.push({ event, phase: start === end ? 'single' : 'end' })
  }

  const grouped = new Map()
  for (const { event, phase } of occurrences) {
    const deadline = ['application_deadline', 'submission_deadline'].includes(event.event_type)
    if (!deadline) {
      const name = displayName(event)
      const suffix = phase === 'start' ? ' 시작' : phase === 'end' ? (name === '참여' ? ' 마감' : ' 종료') : ''
      grouped.set(`${event.id}:${phase}`, { ...event, id: `${event.id}:${phase}`, display_label: `${name}${suffix}` })
      continue
    }
    const groupKey = `${event.notice_id}:${phase}`
    if (!grouped.has(groupKey)) grouped.set(groupKey, { ...event, id: groupKey, types: new Set(), phase })
    grouped.get(groupKey).types.add(event.event_type)
  }
  return [...grouped.values()].map(event => {
    if (!event.types) return event
    const both = event.types.size > 1
    const action = both ? '신청·제출' : event.types.has('application_deadline') ? '신청' : '제출'
    return {
      ...event,
      event_type: both ? 'combined_deadline' : event.event_type,
      display_label: `${action} ${event.phase === 'start' ? '시작' : '마감'}`,
    }
  })
}
