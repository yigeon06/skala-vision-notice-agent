<script setup>
defineProps({ notice: Object })
function formatDate(value) {
  if (!value) return '확인 필요'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('ko-KR', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'Asia/Seoul' }).format(date)
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
      <article v-if="notice" class="detail-card">
        <div class="detail-header">
          <span class="status" :class="notice.status">
            {{ notice.status === 'confirmed' ? '확인 완료' : '검토 필요' }}
          </span>
          <small>#{{ notice.id }}</small>
        </div>
        <h3>{{ notice.title }}</h3>
        <p class="detail-meta">{{ notice.target.join(', ') || '대상 미지정' }}</p>

        <p v-if="notice.application_method" class="detail-meta">신청 방법: {{ notice.application_method }}</p>
        <p v-if="notice.action_required?.length" class="detail-meta">해야 할 일: {{ notice.action_required.join(', ') }}</p>

        <div class="detail-events">
          <div v-for="event in notice.events" :key="event.id">
            <strong>{{ event.date_text }}</strong>
            <span>{{ formatDate(event.start_at) }}<template v-if="event.end_at"> ~ {{ formatDate(event.end_at) }}</template><template v-if="event.all_day"> · 종일</template></span>
            <p>{{ event.location || event.evidence_text }}</p>
          </div>
        </div>

        <section v-if="notice.recruitment_positions?.length" class="position-list">
          <h3>모집 분야</h3>
          <article v-for="position in notice.recruitment_positions" :key="position.name" class="position-card">
            <h4>{{ position.name }}</h4>
            <strong>수행업무</strong>
            <ul><li v-for="item in position.responsibilities" :key="item">{{ item }}</li></ul>
            <strong>우대사항</strong>
            <ul><li v-for="item in position.preferred_qualifications" :key="item">{{ item }}</li></ul>
          </article>
        </section>

        <section v-if="notice.additional_information?.length" class="additional-list">
          <h3>기타 중요 정보</h3>
          <article v-for="(information, index) in notice.additional_information" :key="`${information.category}-${index}`" class="additional-card">
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
          <pre>{{ notice.cleaned_text }}</pre>
        </details>
        <details class="text-detail raw-detail">
          <summary>원본 OCR 보기</summary>
          <pre>{{ notice.raw_text }}</pre>
        </details>
      </article>
</template>
