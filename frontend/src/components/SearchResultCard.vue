<script setup>
defineProps({
  searchType: { type: String, default: 'structured_search' },
  filters: { type: Object, default: () => ({}) },
  notices: { type: Array, default: () => [] },
})

defineEmits(['open'])

const periodLabels = {
  all: '전체 기간',
  today: '오늘',
  tomorrow: '내일',
  this_week: '이번 주',
  next_week: '다음 주',
  custom: '지정 기간',
}

const statusLabels = {
  all: '전체 상태',
  confirmed: '확인 완료',
  needs_review: '검토 필요',
}

const eventTypeLabels = {
  application_deadline: '신청 마감',
  submission_deadline: '제출 마감',
  event: '행사',
  announcement: '발표',
  other: '기타 일정',
}

function filterSummary(filters) {
  const labels = [periodLabels[filters.period] || '전체 기간', statusLabels[filters.status] || '전체 상태']
  if (filters.event_types?.length) labels.push(filters.event_types.map(type => eventTypeLabels[type] || type).join(' · '))
  return labels.join(' · ')
}

function statusLabel(status) {
  return statusLabels[status] || status
}

function eventLabel(type) {
  return eventTypeLabels[type] || '일정'
}

function eventDate(event) {
  if (event.date_text) return event.date_text
  const value = event.effective_at || event.start_at || event.end_at
  if (!value) return '날짜 확인 필요'
  return new Intl.DateTimeFormat('ko-KR', {
    dateStyle: 'medium',
    timeStyle: event.all_day ? undefined : 'short',
    timeZone: 'Asia/Seoul',
  }).format(new Date(value))
}
</script>

<template>
  <section class="search-results" aria-label="공지 검색 결과">
    <div v-if="searchType === 'structured_search'" class="search-summary">
      <span>검색 조건</span>
      <strong>{{ filterSummary(filters) }}</strong>
    </div>
    <div v-else class="search-summary">
      <span>의미 검색 출처</span>
      <strong>관련 공지 {{ notices.length }}건</strong>
    </div>

    <p v-if="!notices.length" class="search-empty">조건에 해당하는 저장된 공지가 없습니다.</p>

    <article v-for="notice in notices" :key="notice.id" class="search-notice-card">
      <div class="search-notice-heading">
        <div>
          <span class="status" :class="notice.status">{{ statusLabel(notice.status) }}</span>
          <span v-if="typeof notice.score === 'number'" class="similarity-score">유사도 {{ notice.score.toFixed(3) }}</span>
          <h3>{{ notice.title }}</h3>
        </div>
        <button type="button" class="detail-button" @click="$emit('open', notice.id)">상세 보기 →</button>
      </div>

      <dl class="search-meta">
        <div><dt>대상</dt><dd>{{ notice.target?.join(', ') || '별도 안내 없음' }}</dd></div>
        <div><dt>신청 방법</dt><dd>{{ notice.application_method || '별도 안내 없음' }}</dd></div>
      </dl>

      <div v-if="notice.events?.length" class="search-events">
        <div v-for="event in notice.events" :key="event.id" class="search-event">
          <span class="event-dot"></span>
          <div>
            <strong>{{ eventLabel(event.event_type) }}</strong>
            <p>{{ eventDate(event) }}<template v-if="event.location"> · {{ event.location }}</template></p>
            <small v-if="event.evidence_text">{{ event.evidence_text }}</small>
          </div>
        </div>
      </div>
    </article>
  </section>
</template>
