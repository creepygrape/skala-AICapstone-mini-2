<script setup>
import { computed } from 'vue'
import { resultHeading, resultNotices, EVIDENCE_TAGS } from '../api/resultText'
import { thumbnailUrl } from '../api/media'
import { timestamp, groupByVideo } from '../api/search'
import { evidenceKey } from '../stores/conversations'

const props = defineProps({ response: Object, selectedKey: String })
defineEmits(['select'])

// One card per video; its moments are listed in rank order, and videos follow their best moment.
const groups = computed(() => groupByVideo(props.response.results))
const best = computed(() => props.response.results[0])
const countLabel = computed(() => groups.value.length === props.response.results.length
  ? `영상 ${groups.value.length}개` : `영상 ${groups.value.length}개 · 시점 ${props.response.results.length}개`)
const hasSelection = group => group.items.some(item => evidenceKey(item) === props.selectedKey)
</script>

<template>
  <section class="results" aria-live="polite">
    <h3>{{ resultHeading(response) }}<template v-if="response.results.length"> ({{ countLabel }})</template></h3>
    <p v-for="note in resultNotices(response)" :key="note" class="notice">{{ note }}</p>
    <ol v-if="response.results.length">
      <li v-for="(group, g) in groups" :key="group.video_id">
        <article class="card" :class="{ selected: hasSelection(group) }">
          <span class="thumb">
            <img v-if="thumbnailUrl(group.video_id)" :src="thumbnailUrl(group.video_id)" alt="" loading="lazy" />
            <span class="rank">{{ g + 1 }}</span>
            <span v-if="group.items.length > 1" class="count">시점 {{ group.items.length }}개</span>
          </span>
          <div class="body">
            <span class="video">{{ group.title }}</span>
            <ul class="stamps">
              <li v-for="item in group.items" :key="evidenceKey(item)">
                <button type="button" class="stamp" :class="{ selected: evidenceKey(item) === selectedKey }"
                        :aria-pressed="evidenceKey(item) === selectedKey" :aria-label="`${timestamp(item.start_seconds)} 시점 선택`"
                        @click="$emit('select', item)">
                  <span class="t">{{ timestamp(item.start_seconds) }}</span>
                  <span class="stext">
                    <span class="top">
                      <span class="tag">{{ EVIDENCE_TAGS[item.evidence_type] || EVIDENCE_TAGS.unknown }}</span>
                      <span v-if="item === best && response.results.length > 1" class="top-pick">가장 유력</span>
                    </span>
                    <span class="quote">“{{ item.evidence_text }}”</span>
                  </span>
                </button>
              </li>
            </ul>
            <span class="explain">{{ group.items[0].explanation_ko }}</span>
          </div>
        </article>
      </li>
    </ol>
  </section>
</template>
