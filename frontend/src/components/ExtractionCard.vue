<script setup>
import { ref, watch } from 'vue'
const props = defineProps({ value: { type: Object, required: true }, validation: Object, busy: Boolean, saved: Boolean, locked: Boolean })
const emit = defineEmits(['save'])
const extraction = ref(clone(props.value))
const edited = ref(false)
const editing = ref(false)
const extractionBeforeEdit = ref(null)
watch(() => props.value, value => { extraction.value = clone(value) })
function save() { if (props.busy || editing.value || props.saved) return; emit('save', clone(extraction.value)) }
function clone(value) { return JSON.parse(JSON.stringify(value)) }

function beginEditing() {
  extractionBeforeEdit.value = clone(extraction.value)
  editing.value = true
}

function cancelEditing() {
  extraction.value = extractionBeforeEdit.value
  extractionBeforeEdit.value = null
  editing.value = false
}

function finishEditing() {
  edited.value = true
  editing.value = false
  extractionBeforeEdit.value = null

}

function lines(value) { return (value || []).join('\n') }

function setLines(target, key, value) {
  target[key] = value.split('\n').map((item) => item.trim()).filter(Boolean)
}

function dateTimeLocal(value) { return value ? value.slice(0, 16) : '' }

function setDateTime(event, key, value) {
  event[key] = value ? `${value}:00+09:00` : null
}

function addEvent() {
  extraction.value.events.push({ event_type: 'other', date_text: '', start_at: null, end_at: null, all_day: false, location: null, evidence_text: '', confidence: 1 })
}

function addPosition() {
  extraction.value.recruitment_positions.push({ name: '', responsibilities: [], preferred_qualifications: [] })
}

function addAdditionalInformation() {
  extraction.value.additional_information.push({ category: 'other', title: '', items: [], evidence_text: '', confidence: 1, needs_review: false })
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

</script>

<template>
      <article class="result-card">
        <div class="result-title">
          <div>
            <span class="step">02</span>
            <h2>추출 결과</h2>
          </div>
          <span class="status" :class="saved ? validation?.status : edited ? 'needs_review' : validation?.status">
            {{ saved ? '저장 완료' : edited ? '수정됨 · 저장 시 검증' : validation?.status === 'confirmed' ? '추출 검증 완료' : '검토 필요' }}
          </span>
        </div>

        <fieldset class="edit-actions" :disabled="busy || saved || locked">
          <template v-if="editing">
            <button class="secondary-button" type="button" @click="cancelEditing">수정 취소</button>
            <button class="edit-button" type="button" @click="finishEditing">수정 완료</button>
          </template>
          <button v-else class="edit-button" type="button" @click="beginEditing">추출 결과 수정하기</button>
        </fieldset>

        <div v-if="editing" class="edit-form">
          <label class="wide-field">제목<input v-model="extraction.title" type="text" /></label>
          <label>대상 (한 줄에 하나)<textarea :value="lines(extraction.target)" @input="setLines(extraction, 'target', $event.target.value)"></textarea></label>
          <label>해야 할 일 (한 줄에 하나)<textarea :value="lines(extraction.action_required)" @input="setLines(extraction, 'action_required', $event.target.value)"></textarea></label>
          <label class="wide-field">신청 방법<input v-model="extraction.application_method" type="text" /></label>
        </div>

        <dl v-else class="summary-grid">
          <div class="wide">
            <dt>제목</dt>
            <dd>{{ extraction.title || '확인 필요' }}</dd>
          </div>
          <div>
            <dt>대상</dt>
            <dd>{{ extraction.target.join(', ') || '확인 필요' }}</dd>
          </div>
          <div class="wide">
            <dt>신청 방법</dt>
            <dd>{{ extraction.application_method || '별도 안내 없음' }}</dd>
          </div>
          <div>
            <dt>해야 할 일</dt>
            <dd>{{ extraction.action_required.join(', ') || '확인 필요' }}</dd>
          </div>
        </dl>

        <section v-if="editing" class="editable-section">
          <div class="editable-section-heading"><h3>일정</h3><button type="button" @click="addEvent">+ 일정 추가</button></div>
          <article v-for="(event, index) in extraction.events" :key="index" class="edit-card">
            <div class="edit-card-heading"><strong>일정 {{ index + 1 }}</strong><button class="remove-button" type="button" @click="extraction.events.splice(index, 1)">삭제</button></div>
            <label>종류<select v-model="event.event_type"><option value="application_deadline">신청 마감</option><option value="event">행사</option><option value="submission_deadline">제출 마감</option><option value="announcement">발표</option><option value="other">기타</option></select></label>
            <label>날짜 표시 문구<input v-model="event.date_text" type="text" /></label>
            <div class="two-columns"><label>시작 일시<input type="datetime-local" :value="dateTimeLocal(event.start_at)" @input="setDateTime(event, 'start_at', $event.target.value)" /></label><label>종료 일시<input type="datetime-local" :value="dateTimeLocal(event.end_at)" @input="setDateTime(event, 'end_at', $event.target.value)" /></label></div>
            <label>장소<input v-model="event.location" type="text" /></label>
            <label class="check-field"><input v-model="event.all_day" type="checkbox" /> 종일 일정</label>
            <details><summary>근거 OCR (읽기 전용)</summary><pre>{{ event.evidence_text || '추가된 일정에는 근거 OCR이 없습니다.' }}</pre></details>
          </article>
        </section>

        <div v-else class="event-list">
          <div v-for="(event, index) in extraction.events" :key="index" class="event-row">
            <span class="event-dot"></span>
            <div>
              <strong>{{ event.date_text || event.event_type }}</strong>
              <p>{{ event.location || event.evidence_text }}</p>
            </div>
          </div>
          <p v-if="!extraction.events.length" class="empty">추출된 일정이 없습니다.</p>
        </div>

        <section v-if="editing" class="editable-section">
          <div class="editable-section-heading"><h3>모집 분야</h3><button type="button" @click="addPosition">+ 분야 추가</button></div>
          <article v-for="(position, index) in extraction.recruitment_positions" :key="index" class="edit-card">
            <div class="edit-card-heading"><strong>모집 분야 {{ index + 1 }}</strong><button class="remove-button" type="button" @click="extraction.recruitment_positions.splice(index, 1)">삭제</button></div>
            <label>분야명<input v-model="position.name" type="text" /></label>
            <label>수행업무 (한 줄에 하나)<textarea :value="lines(position.responsibilities)" @input="setLines(position, 'responsibilities', $event.target.value)"></textarea></label>
            <label>우대사항 (한 줄에 하나)<textarea :value="lines(position.preferred_qualifications)" @input="setLines(position, 'preferred_qualifications', $event.target.value)"></textarea></label>
          </article>
        </section>

        <section v-else-if="extraction.recruitment_positions?.length" class="position-list">
          <h3>모집 분야</h3>
          <article v-for="position in extraction.recruitment_positions" :key="position.name" class="position-card">
            <h4>{{ position.name }}</h4>
            <strong>수행업무</strong>
            <ul><li v-for="item in position.responsibilities" :key="item">{{ item }}</li></ul>
            <strong>우대사항</strong>
            <ul><li v-for="item in position.preferred_qualifications" :key="item">{{ item }}</li></ul>
          </article>
        </section>

        <section v-if="editing" class="editable-section">
          <div class="editable-section-heading"><h3>기타 중요 정보</h3><button type="button" @click="addAdditionalInformation">+ 정보 추가</button></div>
          <article v-for="(information, index) in extraction.additional_information" :key="index" class="edit-card">
            <div class="edit-card-heading"><strong>정보 {{ index + 1 }}</strong><button class="remove-button" type="button" @click="extraction.additional_information.splice(index, 1)">삭제</button></div>
            <label>분류<select v-model="information.category"><option v-for="(label, category) in additionalCategoryLabels" :key="category" :value="category">{{ label }}</option></select></label>
            <label>제목<input v-model="information.title" type="text" /></label>
            <label>내용 (한 줄에 하나)<textarea :value="lines(information.items)" @input="setLines(information, 'items', $event.target.value)"></textarea></label>
            <label class="check-field"><input v-model="information.needs_review" type="checkbox" /> 확인 필요</label>
            <details><summary>근거 OCR (읽기 전용)</summary><pre>{{ information.evidence_text || '추가된 정보에는 근거 OCR이 없습니다.' }}</pre></details>
          </article>
        </section>

        <section v-else-if="extraction.additional_information?.length" class="additional-list">
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

        <label v-if="editing" class="cleaned-text-editor">정리된 전체 텍스트<textarea v-model="extraction.cleaned_text"></textarea></label>
        <details v-else class="text-detail">
          <summary>정리된 전체 텍스트 보기</summary>
          <pre>{{ extraction.cleaned_text }}</pre>
        </details>
        <details class="text-detail raw-detail">
          <summary>원본 OCR 보기</summary>
          <pre>{{ extraction.raw_text }}</pre>
        </details>

        <p v-if="edited && !saved" class="hint">수정 결과는 저장할 때 다시 검증합니다.</p>
        <ul v-if="(!edited || saved) && validation?.issues?.length" class="issue-list">
          <li v-for="issue in validation.issues" :key="issue">{{ issue }}</li>
        </ul>

        <button class="save-button" :disabled="busy || editing || saved" @click="save">
          {{ saved ? "저장 완료" : busy ? "처리 중…" : "추출 결과 저장하기" }}
        </button>
      </article>
</template>
