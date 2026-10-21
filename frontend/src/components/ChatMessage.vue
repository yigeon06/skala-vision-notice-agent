<script setup>
defineProps({ role: String })
</script>
<template>
  <article class="chat-message" :class="role">
    <div class="message-avatar" aria-hidden="true">{{ role === 'user' ? '나' : 'N' }}</div>
    <div class="message-body">
      <span class="message-author">{{ role === 'user' ? '나' : '공지 도우미' }}</span>
      <slot />
    </div>
  </article>
</template>
