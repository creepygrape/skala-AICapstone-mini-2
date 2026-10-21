<script setup>
defineProps({ conversations: Array, activeId: String, busy: Boolean })
defineEmits(['new', 'open', 'remove'])
const when = ms => new Date(ms).toLocaleString('ko-KR', { month: 'numeric', day: 'numeric', hour: 'numeric', minute: '2-digit' })
</script>

<template>
  <aside class="sidebar" aria-label="검색 기록">
    <a class="brand" href="/">WISH FINDER<span>기억 속 장면 찾기</span></a>
    <button type="button" class="new-chat" :disabled="busy" @click="$emit('new')">＋ 새 대화</button>
    <h2>최근 대화</h2>
    <p v-if="!conversations.length" class="empty">아직 검색 기록이 없어요.</p>
    <ul v-else>
      <li v-for="c in conversations" :key="c.id" :class="{ active: c.id === activeId }">
        <button type="button" class="open" :disabled="busy" :aria-current="c.id === activeId ? 'true' : null" @click="$emit('open', c.id)">
          <span class="title">{{ c.title }}</span>
          <span class="meta">{{ when(c.updatedAt) }} · {{ c.turns.length }}개 질문</span>
        </button>
        <button type="button" class="remove" :disabled="busy" :aria-label="`${c.title} 대화 삭제`" @click="$emit('remove', c.id)">✕</button>
      </li>
    </ul>
    <p class="privacy">검색 기록은 이 브라우저에만 저장돼요.</p>
  </aside>
</template>
