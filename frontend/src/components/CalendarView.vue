<script setup>
import { computed, ref, watch } from 'vue'
import { calendarEventsOnDate, seoulDate } from '../calendarOccurrences.js'

const props = defineProps({
  year: Number,
  month: Number,
  items: { type: Array, default: () => [] },
  undated: { type: Array, default: () => [] },
  loading: Boolean,
  error: String,
})
const emit = defineEmits(['previous', 'next', 'today', 'retry', 'open'])
const weekdays = ['일', '월', '화', '수', '목', '금', '토']
const labels = {
  application_deadline: '신청 마감',
  submission_deadline: '제출 마감',
  event: '행사',
  announcement: '발표',
  other: '기타 일정',
}
const selectedDay = ref(1)
watch(() => [props.year, props.month], () => {
  const today = new Date()
  const seoul = new Intl.DateTimeFormat('en-US', {
    timeZone: 'Asia/Seoul', year: 'numeric', month: 'numeric', day: 'numeric',
  }).formatToParts(today)
  const parts = Object.fromEntries(seoul.map(part => [part.type, Number(part.value)]))
  selectedDay.value = parts.year === props.year && parts.month === props.month ? parts.day : 1
}, { immediate: true })

function dayKey(day) {
  return `${props.year}-${String(props.month).padStart(2, '0')}-${String(day).padStart(2, '0')}`
}

function eventsOn(day) {
  return calendarEventsOnDate(props.items, dayKey(day))
}

const daysInMonth = computed(() => new Date(props.year, props.month, 0).getDate())
const cells = computed(() => {
  const offset = new Date(props.year, props.month - 1, 1).getDay()
  const count = Math.ceil((offset + daysInMonth.value) / 7) * 7
  return Array.from({ length: count }, (_, index) => {
    const day = index - offset + 1
    return day > 0 && day <= daysInMonth.value ? day : null
  })
})
const selectedEvents = computed(() => eventsOn(selectedDay.value))
function eventDateRange(event) {
  const start = seoulDate(event.start_at)
  const end = seoulDate(event.end_at)
  return end && end !== start ? `${start} ~ ${end}` : start || end || '날짜 확인 필요'
}
</script>

<template>
  <section class="calendar-view" aria-label="저장된 공지 달력">
    <header class="calendar-toolbar">
      <div><h2>{{ year }}년 {{ month }}월</h2><p>저장한 공지의 일정을 확인하세요.</p></div>
      <div class="calendar-navigation">
        <button type="button" aria-label="이전 달" @click="emit('previous')">‹</button>
        <button type="button" @click="emit('today')">오늘</button>
        <button type="button" aria-label="다음 달" @click="emit('next')">›</button>
      </div>
    </header>
    <p v-if="loading" role="status" class="calendar-feedback">일정을 불러오는 중…</p>
    <p v-if="error" role="alert" class="calendar-feedback error">{{ error }} <button type="button" @click="emit('retry')">다시 시도</button></p>
    <template v-if="!error">
      <div class="calendar-grid" aria-label="월간 달력">
        <div v-for="weekday in weekdays" :key="weekday" class="calendar-weekday">{{ weekday }}</div>
        <div v-for="(day, index) in cells" :key="index" class="calendar-cell" :class="{ empty: !day, selected: day === selectedDay }">
          <button v-if="day" type="button" class="calendar-day" :aria-label="`${month}월 ${day}일, 일정 ${eventsOn(day).length}개`" :aria-pressed="day === selectedDay" @click="selectedDay = day">
            <span class="calendar-day-number">{{ day }}</span>
            <span v-for="event in eventsOn(day).slice(0, 2)" :key="event.id" class="calendar-chip" :class="event.event_type">{{ event.notice_title }} · {{ event.display_label }}</span>
            <span v-if="eventsOn(day).length > 2" class="calendar-more">+{{ eventsOn(day).length - 2 }}개 더</span>
          </button>
        </div>
      </div>
      <section class="calendar-agenda" aria-label="선택한 날짜의 일정">
        <h3>{{ month }}월 {{ selectedDay }}일 일정</h3>
        <p v-if="!selectedEvents.length" class="calendar-muted">이 날짜에 저장된 일정이 없습니다.</p>
        <article v-for="event in selectedEvents" :key="event.id" class="calendar-agenda-item">
          <span class="calendar-type" :class="event.event_type">{{ event.display_label }}</span>
          <div><strong>{{ event.notice_title }}</strong><p>{{ eventDateRange(event) }}<template v-if="event.location"> · {{ event.location }}</template></p><small>{{ event.date_text }}</small></div>
          <button type="button" @click="emit('open', event.notice_id)">공고 상세 보기</button>
        </article>
      </section>
      <section v-if="undated.length" class="calendar-agenda" aria-label="날짜 확인 필요 일정">
        <h3>날짜 확인 필요</h3>
        <article v-for="event in undated" :key="event.id" class="calendar-agenda-item">
          <span class="calendar-type" :class="event.event_type">{{ labels[event.event_type] || '기타 일정' }}</span>
          <div><strong>{{ event.notice_title }}</strong><p>{{ event.date_text || '날짜가 확정되지 않았습니다.' }}</p></div>
          <button type="button" @click="emit('open', event.notice_id)">공고 상세 보기</button>
        </article>
      </section>
    </template>
  </section>
</template>
