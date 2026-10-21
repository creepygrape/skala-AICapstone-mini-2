<script setup>
import { computed } from 'vue'
import { STEP_LABELS, totalDuration } from '../api/steps'
import { formatElapsed } from '../api/search'

const props = defineProps({ steps: Array, busy: Boolean, now: Number, doneMs: Number })
const MARKS = { done: '✓', failed: '✕', aborted: '–' }
const label = step => STEP_LABELS[step.event][step.state === 'done' ? 1 : step.state === 'failed' ? 2 : 0]
const elapsed = step => step.state === 'running' ? formatElapsed(props.now - step.clientStart)
  : step.state === 'aborted' ? '중단' : step.state === 'failed' ? '실패' : `${formatElapsed(step.durationMs)} 소요`
const total = computed(() => formatElapsed(totalDuration(props.steps, props.doneMs)))
</script>

<template>
  <div class="progress" aria-label="검색 진행 상황">
    <p v-if="busy && !steps.length" role="status" class="waiting">검색을 준비하고 있어요.</p>
    <details v-else-if="!busy && steps.length" class="finished">
      <summary>검색 진행 과정 보기 <span class="total">총 {{ total }}</span></summary>
      <ol>
        <li v-for="(step, i) in steps" :key="i" :class="step.state">
          <span class="mark" aria-hidden="true">{{ MARKS[step.state] || '…' }}</span>
          <span>{{ label(step) }}<template v-if="step.attempt !== undefined && step.event !== 'routing'"> ({{ step.attempt + 1 }}차)</template></span>
          <span class="elapsed">{{ elapsed(step) }}</span>
        </li>
      </ol>
    </details>
    <ol v-else-if="steps.length">
      <li v-for="(step, i) in steps" :key="i" :class="step.state">
        <span class="mark" aria-hidden="true">{{ MARKS[step.state] || '…' }}</span>
        <span>{{ label(step) }}<template v-if="step.attempt !== undefined && step.event !== 'routing'"> ({{ step.attempt + 1 }}차)</template></span>
        <span class="elapsed">{{ elapsed(step) }}</span>
      </li>
    </ol>
  </div>
</template>
