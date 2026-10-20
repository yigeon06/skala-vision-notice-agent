<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8100'

const file = ref(null)
const previewUrl = ref('')
const imageId = ref('')
const extraction = ref(null)
const validation = ref(null)
const notices = ref([])
const selectedNotice = ref(null)
const loading = ref(false)
const listLoading = ref(false)
const message = ref('')
const error = ref('')

const canSave = computed(() => Boolean(imageId.value && extraction.value) && !loading.value)

function clearFeedback() {
  message.value = ''
  error.value = ''
}

async function api(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, options)
  const body = await response.json().catch(() => ({}))
  if (!response.ok) {
    throw new Error(body.detail || `요청 실패 (${response.status})`)
  }
  return body
}

function selectFile(event) {
  clearFeedback()
  const nextFile = event.target.files?.[0] || null
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
  file.value = nextFile
  previewUrl.value = nextFile ? URL.createObjectURL(nextFile) : ''
  imageId.value = ''
  extraction.value = null
  validation.value = null
}

async function extractImage() {
  if (!file.value) {
    error.value = '분석할 이미지를 선택하세요.'
    return
  }
  clearFeedback()
  loading.value = true
  try {
    const form = new FormData()
    form.append('file', file.value)
    const uploaded = await api('/images', { method: 'POST', body: form })
    imageId.value = uploaded.image_id
    const result = await api('/notices/extract', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ image_id: imageId.value }),
    })
    extraction.value = result.extraction
    validation.value = result.validation
    message.value = `분석 완료 · ${result.usage.elapsed_seconds ?? 0}초`
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}

async function saveNotice() {
  if (!canSave.value) return
  clearFeedback()
  loading.value = true
  try {
    const result = await api('/notices/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        image_id: imageId.value,
        request_id: crypto.randomUUID(),
        extraction: extraction.value,
      }),
    })
    message.value = result.created
      ? `공지 #${result.notice_id} 저장 완료`
      : '이미 저장된 요청입니다.'
    await loadNotices()
    await openNotice(result.notice_id)
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}

async function loadNotices() {
  listLoading.value = true
  try {
    const result = await api('/notices')
    notices.value = result.items
  } catch (err) {
    error.value = err.message
  } finally {
    listLoading.value = false
  }
}

async function openNotice(id) {
  clearFeedback()
  try {
    selectedNotice.value = await api(`/notices/${id}`)
  } catch (err) {
    error.value = err.message
  }
}

function formatDate(value) {
  if (!value) return '확인 필요'
  return new Intl.DateTimeFormat('ko-KR', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value))
}

const additionalCategoryLabels = {
  preferred_certification: '우대 자격증',
  required_document: '제출서류',
  disqualification: '불이익 조건',
  notice: '유의사항',
  other: '기타',
}

function additionalCategoryLabel(category) {
  return additionalCategoryLabels[category] || '기타'
}

onMounted(loadNotices)
onBeforeUnmount(() => {
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
})
</script>

<template>
  <header class="topbar">
    <div>
      <p class="eyebrow">LOCAL VISION AGENT</p>
      <h1>사내 공지·일정 관리</h1>
    </div>
    <span class="model-badge">Qwen3-VL 4B</span>
  </header>

  <main class="layout">
    <section class="panel upload-panel">
      <div class="section-heading">
        <div>
          <span class="step">01</span>
          <h2>공지 이미지 등록</h2>
        </div>
        <span class="hint">PNG · JPG · WEBP / 최대 10MB</span>
      </div>

      <label class="dropzone" :class="{ filled: previewUrl }">
        <input type="file" accept="image/png,image/jpeg,image/webp" @change="selectFile" />
        <img v-if="previewUrl" :src="previewUrl" alt="선택한 공지 미리보기" />
        <div v-else class="dropzone-copy">
          <span class="upload-icon">↑</span>
          <strong>분석할 이미지를 선택하세요</strong>
          <span>클릭해서 파일 열기</span>
        </div>
      </label>

      <button class="primary" :disabled="!file || loading" @click="extractImage">
        <span v-if="loading" class="spinner"></span>
        {{ loading ? 'Vision이 공지를 읽고 있습니다' : '이미지 분석하기' }}
      </button>

      <p v-if="message" class="feedback success">{{ message }}</p>
      <p v-if="error" class="feedback error">{{ error }}</p>

      <article v-if="extraction" class="result-card">
        <div class="result-title">
          <div>
            <span class="step">02</span>
            <h2>추출 결과</h2>
          </div>
          <span class="status" :class="validation?.status">
            {{ validation?.status === 'confirmed' ? '확인 완료' : '검토 필요' }}
          </span>
        </div>

        <dl class="summary-grid">
          <div class="wide">
            <dt>제목</dt>
            <dd>{{ extraction.title || '확인 필요' }}</dd>
          </div>
          <div>
            <dt>대상</dt>
            <dd>{{ extraction.target.join(', ') || '확인 필요' }}</dd>
          </div>
          <div>
            <dt>해야 할 일</dt>
            <dd>{{ extraction.action_required.join(', ') || '확인 필요' }}</dd>
          </div>
        </dl>

        <div class="event-list">
          <div v-for="(event, index) in extraction.events" :key="index" class="event-row">
            <span class="event-dot"></span>
            <div>
              <strong>{{ event.date_text || event.event_type }}</strong>
              <p>{{ event.location || event.evidence_text }}</p>
            </div>
          </div>
          <p v-if="!extraction.events.length" class="empty">추출된 일정이 없습니다.</p>
        </div>

        <section v-if="extraction.recruitment_positions?.length" class="position-list">
          <h3>모집 분야</h3>
          <article v-for="position in extraction.recruitment_positions" :key="position.name" class="position-card">
            <h4>{{ position.name }}</h4>
            <strong>수행업무</strong>
            <ul><li v-for="item in position.responsibilities" :key="item">{{ item }}</li></ul>
            <strong>우대사항</strong>
            <ul><li v-for="item in position.preferred_qualifications" :key="item">{{ item }}</li></ul>
          </article>
        </section>

        <section v-if="extraction.additional_information?.length" class="additional-list">
          <h3>기타 중요 정보</h3>
          <article v-for="(information, index) in extraction.additional_information" :key="`${information.category}-${index}`" class="additional-card">
            <div class="additional-heading">
              <span>{{ additionalCategoryLabel(information.category) }}</span>
              <span v-if="information.needs_review" class="review-badge">확인 필요</span>
            </div>
            <h4>{{ information.title }}</h4>
            <ul><li v-for="item in information.items" :key="item">{{ item }}</li></ul>
            <details><summary>근거 OCR</summary><pre>{{ information.evidence_text }}</pre></details>
          </article>
        </section>

        <details class="text-detail">
          <summary>정리된 전체 텍스트 보기</summary>
          <pre>{{ extraction.cleaned_text }}</pre>
        </details>
        <details class="text-detail raw-detail">
          <summary>원본 OCR 보기</summary>
          <pre>{{ extraction.raw_text }}</pre>
        </details>

        <ul v-if="validation?.issues?.length" class="issue-list">
          <li v-for="issue in validation.issues" :key="issue">{{ issue }}</li>
        </ul>

        <button class="save-button" :disabled="!canSave" @click="saveNotice">
          추출 결과 저장하기
        </button>
      </article>
    </section>

    <aside class="panel archive-panel">
      <div class="section-heading">
        <div>
          <span class="step">03</span>
          <h2>저장된 공지</h2>
        </div>
        <button class="refresh" :disabled="listLoading" @click="loadNotices">새로고침</button>
      </div>

      <div v-if="listLoading" class="empty">목록을 불러오는 중입니다.</div>
      <div v-else-if="!notices.length" class="empty-state">
        <span>□</span>
        <strong>저장된 공지가 없습니다</strong>
        <p>이미지를 분석하고 첫 공지를 저장해 보세요.</p>
      </div>
      <div v-else class="notice-list">
        <button
          v-for="notice in notices"
          :key="notice.id"
          class="notice-item"
          :class="{ active: selectedNotice?.id === notice.id }"
          @click="openNotice(notice.id)"
        >
          <span class="status-dot" :class="notice.status"></span>
          <span class="notice-copy">
            <strong>{{ notice.title }}</strong>
            <small>일정 {{ notice.event_count }}개 · {{ formatDate(notice.created_at) }}</small>
          </span>
          <span>›</span>
        </button>
      </div>

      <article v-if="selectedNotice" class="detail-card">
        <div class="detail-header">
          <span class="status" :class="selectedNotice.status">
            {{ selectedNotice.status === 'confirmed' ? '확인 완료' : '검토 필요' }}
          </span>
          <small>#{{ selectedNotice.id }}</small>
        </div>
        <h3>{{ selectedNotice.title }}</h3>
        <p class="detail-meta">{{ selectedNotice.target.join(', ') || '대상 미지정' }}</p>

        <div class="detail-events">
          <div v-for="event in selectedNotice.events" :key="event.id">
            <strong>{{ event.date_text }}</strong>
            <span>{{ formatDate(event.start_at) }}</span>
            <p>{{ event.location || event.evidence_text }}</p>
          </div>
        </div>

        <section v-if="selectedNotice.recruitment_positions?.length" class="position-list">
          <h3>모집 분야</h3>
          <article v-for="position in selectedNotice.recruitment_positions" :key="position.name" class="position-card">
            <h4>{{ position.name }}</h4>
            <strong>수행업무</strong>
            <ul><li v-for="item in position.responsibilities" :key="item">{{ item }}</li></ul>
            <strong>우대사항</strong>
            <ul><li v-for="item in position.preferred_qualifications" :key="item">{{ item }}</li></ul>
          </article>
        </section>

        <section v-if="selectedNotice.additional_information?.length" class="additional-list">
          <h3>기타 중요 정보</h3>
          <article v-for="(information, index) in selectedNotice.additional_information" :key="`${information.category}-${index}`" class="additional-card">
            <div class="additional-heading">
              <span>{{ additionalCategoryLabel(information.category) }}</span>
              <span v-if="information.needs_review" class="review-badge">확인 필요</span>
            </div>
            <h4>{{ information.title }}</h4>
            <ul><li v-for="item in information.items" :key="item">{{ item }}</li></ul>
            <details><summary>근거 OCR</summary><pre>{{ information.evidence_text }}</pre></details>
          </article>
        </section>

        <details class="text-detail" open>
          <summary>정리된 전체 텍스트</summary>
          <pre>{{ selectedNotice.cleaned_text }}</pre>
        </details>
        <details class="text-detail raw-detail">
          <summary>원본 OCR 보기</summary>
          <pre>{{ selectedNotice.raw_text }}</pre>
        </details>
      </article>
    </aside>
  </main>
</template>
