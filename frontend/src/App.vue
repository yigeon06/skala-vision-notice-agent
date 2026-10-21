<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import ChatMessage from './components/ChatMessage.vue'
import ExtractionCard from './components/ExtractionCard.vue'
import NoticeDetail from './components/NoticeDetail.vue'
import SearchResultCard from './components/SearchResultCard.vue'
import CalendarView from './components/CalendarView.vue'

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8100'
const messages = ref([])
const draft = ref('')
const searchMode = ref('auto')
const searchModes = [
  { value: 'auto', label: '자동' },
  { value: 'structured_search', label: '공지/일정 조회' },
  { value: 'semantic_search', label: '세부 내용 조회' },
]
const attachment = ref(null)
const attachmentUrl = ref('')
const notices = ref([])
const selectedNotice = ref(null)
const selectedId = ref(null)
const view = ref('chat')
const seoulToday = new Intl.DateTimeFormat('en-US', {
  timeZone: 'Asia/Seoul', year: 'numeric', month: 'numeric',
}).formatToParts(new Date())
const todayParts = Object.fromEntries(seoulToday.map(part => [part.type, Number(part.value)]))
const calendarYear = ref(todayParts.year)
const calendarMonth = ref(todayParts.month)
const calendarItems = ref([])
const calendarUndated = ref([])
const calendarLoading = ref(false)
const calendarError = ref('')
const busy = ref(false)
const listLoading = ref(false)
const detailLoading = ref(false)
const listError = ref('')
const detailError = ref('')
const composerError = ref('')
const sidebarOpen = ref(false)
const conversationEnd = ref(null)
const fileInput = ref(null)
const composer = ref(null)
const urls = new Set()
let detailVersion = 0
let calendarVersion = 0

const canSend = computed(() => !busy.value && (draft.value.trim() || attachment.value))

async function api(path, options = {}) {
  let response
  try {
    response = await fetch(`${API_BASE}${path}`, options)
  } catch {
    throw new Error('서버에 연결하지 못했습니다. 백엔드 실행 상태를 확인하고 다시 시도해 주세요.')
  }
  const body = await response.json().catch(() => ({}))
  if (!response.ok) {
    const detail = typeof body.detail === 'string' ? body.detail : `요청 실패 (${response.status})`
    throw new Error(response.status === 422 ? '입력 내용을 확인해 주세요.' : detail || `요청 실패 (${response.status})`)
  }
  return body
}

async function scrollToEnd() {
  await nextTick()
  conversationEnd.value?.scrollIntoView({ block: 'end' })
}

function removeAttachment() {
  if (attachmentUrl.value) {
    URL.revokeObjectURL(attachmentUrl.value)
    urls.delete(attachmentUrl.value)
  }
  attachment.value = null
  attachmentUrl.value = ''
  if (fileInput.value) fileInput.value.value = ''
}

function selectFile(event) {
  const file = event.target.files?.[0]
  if (!file) return
  composerError.value = ''
  if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type) || file.size > 10 * 1024 * 1024) {
    composerError.value = 'PNG, JPG, WEBP 형식의 10MB 이하 이미지를 선택해 주세요.'
    event.target.value = ''
    return
  }
  removeAttachment()
  attachment.value = file
  attachmentUrl.value = URL.createObjectURL(file)
  urls.add(attachmentUrl.value)
}

async function send() {
  if (!canSend.value) return
  composerError.value = ''
  const item = {
    id: crypto.randomUUID(), role: 'user', kind: attachment.value ? 'image' : 'text',
    content: draft.value.trim() || '이 공지 이미지를 분석해 주세요.',
    file: attachment.value, preview: attachmentUrl.value,
    status: 'pending', error: '', imageId: '', requestId: crypto.randomUUID(),
    searchMode: searchMode.value,
  }
  // 미리보기 URL의 소유권을 메시지로 옮긴다. 다른 첨부와 독립적으로 유지한다.
  attachment.value = null
  attachmentUrl.value = ''
  if (fileInput.value) fileInput.value.value = ''
  draft.value = ''
  messages.value.push(item)
  await processMessage(messages.value[messages.value.length - 1])
}

async function processMessage(item) {
  if (busy.value) return
  busy.value = true
  item.status = 'pending'
  item.error = ''
  await scrollToEnd()
  try {
    const index = messages.value.findIndex(message => message.id === item.id)
    const history = messages.value.slice(0, index + 1)
      .filter(message => message.content && message.role && (message.status === 'complete' || message.id === item.id))
      .map(({ role, content }) => ({ role, content }))
    const payload = { messages: history, search_mode: item.searchMode || 'auto' }

    if (item.kind === 'image') {
      if (!item.imageId) {
        const form = new FormData()
        form.append('file', item.file)
        const uploaded = await api('/images', { method: 'POST', body: form })
        item.imageId = uploaded.image_id
      }
      payload.image_id = item.imageId
    }

    const result = await api('/agent', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    const response = {
      id: crypto.randomUUID(), role: 'assistant', kind: 'text',
      content: result.message, route: result.route, status: 'complete',
    }
    if (result.route === 'notice_register' && result.data?.extraction) {
      Object.assign(response, {
        kind: 'extraction', extraction: result.data.extraction,
        validation: result.data.validation, imageId: result.data.image_id || item.imageId,
        requestId: item.requestId, saved: false, error: '', feedback: '', embeddingWarning: '',
      })
    } else if (result.route === 'notice_search' && (
      result.data?.search_type === 'structured_search'
      || (result.data?.search_type === 'semantic_search' && result.data?.sources?.length)
    )) {
      Object.assign(response, {
        kind: 'search', searchType: result.data.search_type,
        filters: result.data.filters,
        notices: result.data.notices || result.data.sources || [],
      })
    }
    messages.value.splice(index + 1, 0, response)
    item.status = 'complete'
  } catch (error) {
    item.status = 'failed'
    item.error = error.message
  } finally {
    busy.value = false
    await scrollToEnd()
    composer.value?.focus()
  }
}

async function saveNotice(item, extraction) {
  if (busy.value || item.saved) return
  busy.value = true
  item.error = ''
  item.feedback = ''
  item.embeddingWarning = ''
  // 저장 실패 후 재시도할 때도 동일한 본문·요청 ID를 유지한다.
  item.savePayload ??= JSON.parse(JSON.stringify(extraction))
  try {
    const result = await api('/notices/register', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ image_id: item.imageId, request_id: item.requestId, extraction: item.savePayload }),
    })
    item.saved = true
    item.extraction = result.extraction
    item.validation = { status: result.status, issues: result.issues }
    item.feedback = `공지 #${result.notice_id} ${result.created ? '저장 완료' : '저장 확인 완료'}`
    if (result.embedding?.status === 'failed') {
      item.embeddingWarning = result.embedding.warning
    } else if (result.embedding?.status === 'ready') {
      item.feedback += ' · 의미 검색 준비 완료'
    }
    await loadNotices()
    if (view.value === 'calendar') await loadCalendar()
  } catch (error) {
    item.error = error.message
  } finally {
    busy.value = false
  }
}

async function loadNotices() {
  if (listLoading.value) return
  listLoading.value = true
  listError.value = ''
  try {
    notices.value = (await api('/notices')).items
  } catch (error) {
    listError.value = error.message
  } finally {
    listLoading.value = false
  }
}

async function loadCalendar() {
  const version = ++calendarVersion
  calendarLoading.value = true
  calendarError.value = ''
  try {
    const result = await api(`/calendar/events?year=${calendarYear.value}&month=${calendarMonth.value}`)
    if (version === calendarVersion) {
      calendarItems.value = result.items
      calendarUndated.value = result.undated
    }
  } catch (error) {
    if (version === calendarVersion) calendarError.value = error.message
  } finally {
    if (version === calendarVersion) calendarLoading.value = false
  }
}

function showCalendar() {
  closeDetail()
  view.value = 'calendar'
  sidebarOpen.value = false
  loadCalendar()
}

function showChat() {
  closeDetail()
  view.value = 'chat'
  sidebarOpen.value = false
}

function changeCalendarMonth(offset) {
  const date = new Date(calendarYear.value, calendarMonth.value - 1 + offset, 1)
  calendarYear.value = date.getFullYear()
  calendarMonth.value = date.getMonth() + 1
  loadCalendar()
}

function showCurrentMonth() {
  calendarYear.value = todayParts.year
  calendarMonth.value = todayParts.month
  loadCalendar()
}

async function openNotice(id) {
  const version = ++detailVersion
  selectedId.value = id
  selectedNotice.value = null
  detailError.value = ''
  detailLoading.value = true
  sidebarOpen.value = false
  try {
    const notice = await api(`/notices/${id}`)
    if (version === detailVersion) selectedNotice.value = notice
  } catch (error) {
    if (version === detailVersion) detailError.value = error.message
  } finally {
    if (version === detailVersion) detailLoading.value = false
  }
}

function closeDetail() {
  detailVersion++
  selectedId.value = null
  selectedNotice.value = null
  detailLoading.value = false
  detailError.value = ''
}

function onComposerKeydown(event) {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing && event.keyCode !== 229) {
    event.preventDefault()
    send()
  }
}

onMounted(loadNotices)
onBeforeUnmount(() => { for (const url of urls) URL.revokeObjectURL(url) })
</script>

<template>
  <div class="app-shell">
    <button v-if="sidebarOpen" class="sidebar-backdrop" aria-label="공지 목록 닫기" @click="sidebarOpen = false"></button>
    <aside class="sidebar" :class="{ 'is-open': sidebarOpen }" aria-label="저장된 공지">
      <a class="brand" href="#" @click.prevent="showChat">
        <span class="brand-symbol">N</span><span>Notice<span class="brand-subtitle">공지·일정 도우미</span></span>
      </a>
      <button class="conversation-button" @click="showChat">대화 보기 <span>↗</span></button>
      <button class="conversation-button calendar-sidebar-button" @click="showCalendar">달력 보기 <span>▦</span></button>
      <div class="sidebar-heading"><h2>저장된 공지</h2><button class="text-button" :disabled="listLoading" @click="loadNotices">새로고침</button></div>
      <p v-if="listLoading" class="sidebar-note" role="status">목록을 불러오는 중…</p>
      <div v-if="listError" class="feedback error" role="alert">{{ listError }}<button class="text-button" @click="loadNotices">다시 시도</button></div>
      <p v-if="!listLoading && !listError && !notices.length" class="sidebar-note">아직 저장된 공지가 없습니다.<br />이미지를 첨부해 첫 공지를 등록해 보세요.</p>
      <nav class="notice-list" aria-label="공지 목록">
        <button v-for="notice in notices" :key="notice.id" class="notice-item" :class="{ active: selectedId === notice.id }" @click="openNotice(notice.id)">
          <span class="status-dot" :class="notice.status"></span>
          <span class="notice-copy"><strong>{{ notice.title }}</strong><small>일정 {{ notice.event_count }}개 · {{ notice.status === 'confirmed' ? '확인 완료' : '검토 필요' }}</small></span>
        </button>
      </nav>
      <div class="sidebar-footer"><span class="online-dot"></span>나의 공지 보관함<p>저장한 공지는 다시 접속해도 유지됩니다.</p></div>
    </aside>

    <main class="workspace">
      <header class="chat-header">
        <div class="header-title"><button class="menu-button" aria-label="공지 목록 열기" :aria-expanded="sidebarOpen" @click="sidebarOpen = true">☰</button><div><h1>공지 도우미</h1><p>대화하고, 공지를 정리하세요.</p></div></div>
        <span class="header-badge">{{ selectedId !== null ? '공지 상세' : view === 'calendar' ? '저장된 일정 달력' : '일반 대화 · 이미지 등록' }}</span>
      </header>

      <section v-if="selectedId !== null" class="notice-workspace" aria-label="공지 상세">
        <button class="text-button back-button" @click="closeDetail">← {{ view === 'calendar' ? '달력으로 돌아가기' : '대화로 돌아가기' }}</button>
        <p v-if="detailLoading" role="status">공지를 불러오는 중…</p>
        <div v-if="detailError" class="feedback error" role="alert">{{ detailError }} <button class="text-button" @click="openNotice(selectedId)">다시 시도</button></div>
        <NoticeDetail :notice="selectedNotice" />
      </section>

      <section v-if="selectedId === null && view === 'calendar'" class="calendar-workspace">
        <CalendarView :year="calendarYear" :month="calendarMonth" :items="calendarItems" :undated="calendarUndated"
          :loading="calendarLoading" :error="calendarError" @previous="changeCalendarMonth(-1)"
          @next="changeCalendarMonth(1)" @today="showCurrentMonth" @retry="loadCalendar" @open="openNotice" />
      </section>

      <div v-show="selectedId === null && view === 'chat'" class="chat-pane">
        <section class="conversation" aria-label="대화 내용" :aria-busy="busy">
          <div v-if="!messages.length" class="welcome">
            <span class="welcome-symbol">N</span><p class="eyebrow">YOUR NOTICE ASSISTANT</p>
            <h2>공지는 간편하게,<br />대화는 자연스럽게.</h2>
            <p>궁금한 내용을 물어보거나<br />공지 이미지를 첨부해 내용을 정리해 보세요.</p>
            <div class="welcome-actions"><button @click="draft = '어떤 일을 도와줄 수 있어?'; composer?.focus()"><span>↗</span>도우미에게 물어보기</button><button @click="fileInput?.click()"><span>＋</span>공지 이미지 첨부하기</button></div>
          </div>
          <ChatMessage v-for="item in messages" :key="item.id" :role="item.role">
            <p class="message-text">{{ item.content }}</p>
            <img v-if="item.preview" class="message-image" :src="item.preview" :alt="item.file.name" />
            <p v-if="item.kind === 'image'" class="message-caption">{{ item.file.name }}</p>
            <ExtractionCard v-if="item.kind === 'extraction'" :value="item.extraction" :validation="item.validation" :busy="busy" :saved="item.saved" :locked="Boolean(item.savePayload)" @save="saveNotice(item, $event)" />
            <SearchResultCard v-if="item.kind === 'search'" :search-type="item.searchType" :filters="item.filters" :notices="item.notices" @open="openNotice" />
            <p v-if="item.feedback" class="feedback success" role="status">{{ item.feedback }}</p>
            <p v-if="item.embeddingWarning" class="feedback error" role="alert">{{ item.embeddingWarning }}</p>
            <div v-if="item.error" class="feedback error" role="alert">{{ item.error }}<button class="text-button" :disabled="busy" @click="item.kind === 'extraction' ? saveNotice(item, item.extraction) : processMessage(item)">{{ item.kind === 'extraction' ? '같은 내용으로 저장 재시도' : '다시 시도' }}</button></div>
            <p v-if="item.status === 'pending'" class="pending-status" role="status"><span class="spinner"></span>{{ item.kind === 'image' ? '이미지에서 공지 내용을 읽고 있습니다…' : '답변을 작성하고 있습니다…' }}</p>
          </ChatMessage>
          <div ref="conversationEnd"></div>
        </section>

        <footer class="composer-area">
          <div class="search-mode-picker" role="group" aria-label="조회 방식">
            <button v-for="mode in searchModes" :key="mode.value" type="button"
              :aria-pressed="searchMode === mode.value" :class="{ selected: searchMode === mode.value }"
              :disabled="busy" @click="searchMode = mode.value">{{ mode.label }}</button>
          </div>
          <form class="composer" @submit.prevent="send">
            <div v-if="attachment" class="attachment-preview"><img :src="attachmentUrl" alt="첨부 이미지 미리보기" /><span>{{ attachment.name }}<small>공지 이미지로 분석합니다.</small></span><button type="button" aria-label="첨부 이미지 삭제" :disabled="busy" @click="removeAttachment">×</button></div>
            <label class="sr-only" for="chat-input">메시지 입력</label>
            <textarea id="chat-input" ref="composer" v-model="draft" rows="2" placeholder="메시지를 입력하거나 공지 이미지를 첨부하세요" :disabled="busy" @keydown="onComposerKeydown"></textarea>
            <div class="composer-actions"><div><input ref="fileInput" class="sr-only" type="file" accept="image/png,image/jpeg,image/webp" :disabled="busy" @change="selectFile" /><button type="button" class="attach-button" :disabled="busy" @click="fileInput?.click()">＋ <span>이미지 첨부</span></button><span class="file-hint">최대 10MB</span></div><button type="submit" class="send-button" :disabled="!canSend" aria-label="메시지 전송">{{ busy ? '처리 중…' : '전송 ↑' }}</button></div>
          </form>
          <p v-if="composerError" class="feedback error" role="alert">{{ composerError }}</p>
          <p class="composer-note">대화는 새로고침하면 초기화됩니다. 공지·일정은 왼쪽 목록에서 확인하세요.</p>
          <p v-if="attachment && draft.trim()" class="composer-note">첨부 시 공지 이미지 분석을 진행합니다. 입력 문구는 대화에만 표시됩니다.</p>
        </footer>
      </div>
    </main>
  </div>
</template>
