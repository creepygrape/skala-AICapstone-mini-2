<script setup>
import { resultHeading, resultNotices, EVIDENCE_TAGS } from '../api/resultText'
import { thumbnailUrl } from '../api/media'
import { timestamp } from '../api/search'
import { evidenceKey } from '../stores/conversations'

defineProps({ response: Object, selectedKey: String })
defineEmits(['select'])
</script>

<template>
  <section class="results" aria-live="polite">
    <h3>{{ resultHeading(response) }}<template v-if="response.results.length"> ({{ response.results.length }})</template></h3>
    <p v-for="note in resultNotices(response)" :key="note" class="notice">{{ note }}</p>
    <ol v-if="response.results.length">
      <li v-for="(item, i) in response.results" :key="evidenceKey(item)">
        <button type="button" class="card" :class="{ selected: evidenceKey(item) === selectedKey }"
                :aria-pressed="evidenceKey(item) === selectedKey" @click="$emit('select', item)">
          <span class="thumb">
            <img v-if="thumbnailUrl(item.video_id)" :src="thumbnailUrl(item.video_id)" alt="" loading="lazy" />
            <span class="rank">{{ i + 1 }}</span>
            <span class="at">{{ timestamp(item.start_seconds) }}</span>
          </span>
          <span class="body">
            <span class="top">
              <span class="tag">{{ EVIDENCE_TAGS[item.evidence_type] || EVIDENCE_TAGS.unknown }}</span>
              <span v-if="i === 0 && response.results.length > 1" class="top-pick">가장 유력</span>
            </span>
            <span class="video">{{ item.title }}</span>
            <span class="quote">“{{ item.evidence_text }}”</span>
            <span class="explain">{{ item.explanation_ko }}</span>
          </span>
        </button>
      </li>
    </ol>
  </section>
</template>
