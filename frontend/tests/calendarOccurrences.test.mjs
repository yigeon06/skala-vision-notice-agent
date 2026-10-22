import assert from 'node:assert/strict'
import test from 'node:test'
import { calendarEventsOnDate } from '../src/calendarOccurrences.js'

const at = date => `${date}T00:00:00+09:00`
const until = date => `${date}T23:59:59+09:00`

function occurrence(overrides = {}) {
  return {
    id: 10,
    notice_id: 6,
    notice_title: 'K-뉴딜 아카데미 참여후기 이벤트',
    event_type: 'event',
    date_text: '이벤트 기간 10월 21일 ~ 10월 28일',
    action_required: ['참여하기'],
    start_at: at('2026-10-21'),
    end_at: until('2026-10-28'),
    effective_at: at('2026-10-21'),
    ...overrides,
  }
}

test('participation period appears only on its start and end dates', () => {
  const items = [occurrence()]
  assert.equal(calendarEventsOnDate(items, '2026-10-21')[0].display_label, '참여 시작')
  for (let day = 22; day <= 27; day++) {
    assert.deepEqual(calendarEventsOnDate(items, `2026-10-${day}`), [])
  }
  assert.equal(calendarEventsOnDate(items, '2026-10-28')[0].display_label, '참여 마감')
})

test('multi-day event and announcement use endpoints without repeating', () => {
  const event = occurrence({ action_required: [], date_text: '행사 기간', start_at: at('2026-10-31'), end_at: until('2026-11-02') })
  assert.equal(calendarEventsOnDate([event], '2026-10-31')[0].display_label, '행사 시작')
  assert.deepEqual(calendarEventsOnDate([event], '2026-11-01'), [])
  assert.equal(calendarEventsOnDate([event], '2026-11-02')[0].display_label, '행사 종료')

  const announcement = occurrence({ event_type: 'announcement', action_required: [], start_at: at('2026-10-21'), end_at: until('2026-10-23') })
  assert.equal(calendarEventsOnDate([announcement], '2026-10-23')[0].display_label, '발표 종료')
})

test('one-day event appears once and same-day deadlines still group', () => {
  const event = occurrence({ action_required: [], start_at: at('2026-10-21'), end_at: until('2026-10-21') })
  assert.deepEqual(calendarEventsOnDate([event], '2026-10-21').map(item => item.display_label), ['행사'])

  const deadlines = ['application_deadline', 'submission_deadline'].map((event_type, index) => occurrence({
    id: index + 1, event_type, action_required: [],
    start_at: at('2026-10-21'), end_at: until('2026-10-21'),
    effective_at: until('2026-10-21'),
  }))
  assert.deepEqual(calendarEventsOnDate(deadlines, '2026-10-21').map(item => item.display_label), ['신청·제출 마감'])
})
